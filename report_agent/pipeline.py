"""Downstream-facing search + report API.

The public function in this module intentionally keeps search configuration out
of the call surface. Search uses the same environment defaults as
`run_similar_product_reports.py`; downstream callers only provide the business
input and optional report-generation settings.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from report_agent.core import run_writing_agent
from report_agent.models import ReportPackage, WritingAgentConfig
from report_agent.search_adapter import ReportSearchConfig, search_for_report


PathLike = Union[str, Path]


@dataclass
class SearchReportResult:
    """Return value for downstream search + report calls."""

    task_id: str
    product_description: str
    competitors: List[str]
    queries: List[str]
    search_results: List[Any]
    search_errors: List[str]
    report_package: ReportPackage
    output_paths: Dict[str, str] = field(default_factory=dict)

    @property
    def search_result_count(self) -> int:
        return len(self.search_results)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "product_description": self.product_description,
            "competitors": self.competitors,
            "queries": self.queries,
            "search_result_count": self.search_result_count,
            "search_results": [
                _search_result_to_dict(item) for item in self.search_results
            ],
            "search_errors": self.search_errors,
            "report_package": self.report_package.to_dict(),
            "output_paths": self.output_paths,
        }


def run_search_and_report(
    product_description: str,
    *,
    competitors: Optional[Sequence[str]] = None,
    task_id: str = "search_report_task",
    target_domain: str = "",
    analysis_goal: str = "",
    writing_config: Optional[WritingAgentConfig] = None,
    output_dir: Optional[PathLike] = None,
    progress_printer: Optional[Callable[[str], None]] = None,
) -> SearchReportResult:
    """Run default upstream search and then report_agent.

    Args:
        product_description: Product direction or research need.
        competitors: Optional known competitor names. If provided, search
            queries are centered on these competitors.
        task_id: External task id copied into the report package.
        target_domain: Optional report domain. Defaults to product_description.
        analysis_goal: Optional report goal. Defaults to a competitor-analysis
            goal derived from product_description.
        writing_config: Optional report-agent config. This only controls the
            report stage; search parameters are not exposed here.
        output_dir: Optional directory for markdown, package JSON, and search
            result JSON files.
        progress_printer: Optional logging callback.

    Returns:
        SearchReportResult with raw search results, generated ReportPackage, and
        optional output paths.
    """

    description = _clean_required(product_description, "product_description")
    competitor_list = _clean_competitors(competitors)
    printer = progress_printer or print

    search_config = ReportSearchConfig.from_env()
    search_config.progress_printer = printer

    _log(printer, f"[pipeline] task_id={task_id}")
    _log(printer, f"[pipeline] product_description={description}")
    if competitor_list:
        _log(printer, f"[pipeline] competitors={', '.join(competitor_list)}")

    bundle = search_for_report(
        description,
        competitors=competitor_list,
        config=search_config,
    )
    if not bundle.results:
        detail = "; ".join(bundle.errors) if bundle.errors else "none"
        raise RuntimeError(f"No search results available. Search errors: {detail}")

    active_writing_config = writing_config or build_writing_config_from_env()
    if progress_printer:
        active_writing_config = replace(
            active_writing_config,
            progress_printer=printer,
        )

    report_goal = (
        analysis_goal.strip()
        or f"基于搜索结果，为 {description} 生成竞品分析报告"
    )
    report_domain = target_domain.strip() or description
    package = run_writing_agent(
        bundle.results,
        config=active_writing_config,
        task_id=task_id,
        analysis_goal=report_goal,
        target_domain=report_domain,
        competitors=competitor_list,
    )

    output_paths: Dict[str, str] = {}
    if output_dir:
        output_paths = write_search_report_outputs(
            package=package,
            search_results=bundle.results,
            queries=bundle.queries,
            search_errors=bundle.errors,
            output_dir=Path(output_dir),
            task_id=task_id,
        )

    return SearchReportResult(
        task_id=task_id,
        product_description=description,
        competitors=competitor_list,
        queries=bundle.queries,
        search_results=bundle.results,
        search_errors=bundle.errors,
        report_package=package,
        output_paths=output_paths,
    )


def build_writing_config_from_env(
    *, use_llm: Optional[bool] = None
) -> WritingAgentConfig:
    """Build report-agent LLM config from the same provider env convention."""

    api_key, base_url, model = _provider_llm_config()
    api_key = os.getenv("REPORT_LLM_API_KEY") or api_key
    base_url = os.getenv("REPORT_LLM_BASE_URL") or base_url
    model = os.getenv("REPORT_LLM_MODEL") or model
    enabled = bool(api_key and base_url and model)
    if use_llm is not None:
        enabled = enabled and use_llm
    return WritingAgentConfig(
        llm_api_key=api_key,
        llm_base_url=base_url,
        llm_model=model,
        use_llm=enabled,
        max_tokens=int(os.getenv("REPORT_AGENT_MAX_TOKENS", "0")),
        max_source_chars=int(os.getenv("REPORT_AGENT_SOURCE_MAX_CHARS", "0")),
        max_prompt_sources=int(os.getenv("REPORT_AGENT_MAX_PROMPT_SOURCES", "0")),
        max_evidence_cards=int(os.getenv("REPORT_AGENT_MAX_EVIDENCE_CARDS", "0")),
        llm_timeout=int(os.getenv("REPORT_AGENT_LLM_TIMEOUT", "300")),
        llm_batch_workers=_env_int("REPORT_AGENT_BATCH_WORKERS", 8),
        table_gap_search_enabled=os.getenv(
            "REPORT_AGENT_TABLE_GAP_SEARCH", "1"
        ).strip()
        != "0",
        table_gap_search_max_queries=_env_int(
            "REPORT_AGENT_TABLE_GAP_SEARCH_MAX_QUERIES", 12
        ),
        table_gap_search_all_pending=os.getenv(
            "REPORT_AGENT_TABLE_GAP_SEARCH_ALL_PENDING", "1"
        ).strip()
        != "0",
        table_gap_search_results_per_query=_env_int(
            "REPORT_AGENT_TABLE_GAP_SEARCH_RESULTS", 3
        ),
        table_gap_search_crawl_max_chars=_env_int(
            "REPORT_AGENT_TABLE_GAP_SEARCH_CRAWL_CHARS", 2500
        ),
        table_gap_search_max_rounds=_env_int(
            "REPORT_AGENT_TABLE_GAP_SEARCH_MAX_ROUNDS", 3
        ),
        table_gap_search_workers=_env_int("REPORT_AGENT_TABLE_GAP_SEARCH_WORKERS", 5),
        search_source=os.getenv("SEARCH_SOURCE", "bocha"),
        search_bocha_api_key=os.getenv("BOCHA_API_KEY", ""),
        search_google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        search_google_cx_id=os.getenv("GOOGLE_CX_ID", ""),
        search_proxy=os.getenv("HTTP_PROXY", ""),
        search_backend=_env_int("SEARCH_BACKEND", 0),
        evidence_structurer_mode=int(os.getenv("REPORT_AGENT_EVIDENCE_MODE", "1")),
        export_comparison_tables=os.getenv("REPORT_AGENT_EXPORT_TABLES", "1").strip()
        != "0",
        table_export_dir=os.getenv(
            "REPORT_AGENT_TABLE_EXPORT_DIR", "reports/report_agent_tables"
        ),
        verbose=True,
    )


def write_search_report_outputs(
    *,
    package: ReportPackage,
    search_results: Sequence[Any],
    queries: Sequence[str],
    search_errors: Sequence[str],
    output_dir: Path,
    task_id: str,
) -> Dict[str, str]:
    """Persist report markdown, ReportPackage JSON, and raw search payload."""

    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_safe_filename(task_id)}"
    report_path = output_dir / f"{prefix}_report.md"
    package_path = output_dir / f"{prefix}_report_package.json"
    search_path = output_dir / f"{prefix}_search_results.json"

    report_path.write_text(package.report_markdown, encoding="utf-8")
    package_path.write_text(package.to_json(), encoding="utf-8")
    search_payload = {
        "queries": list(queries),
        "search_errors": list(search_errors),
        "search_results": [_search_result_to_dict(item) for item in search_results],
    }
    search_path.write_text(
        _json_dumps(search_payload),
        encoding="utf-8",
    )
    return {
        "report_markdown": str(report_path),
        "report_package": str(package_path),
        "search_results": str(search_path),
    }


def _provider_llm_config() -> tuple[str, str, str]:
    provider = int(os.getenv("LLM_PROVIDER", "0"))
    if provider == 0:
        return (
            os.getenv("LLM0_API_KEY")
            or os.getenv("ARK_API_KEY")
            or "",
            os.getenv("LLM0_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
            os.getenv("LLM0_MODEL", "ep-20260514111325-xjmj7"),
        )
    if provider == 1:
        return (
            os.getenv("LLM1_API_KEY") or os.getenv("LLM_API_KEY", ""),
            os.getenv("LLM1_BASE_URL")
            or os.getenv(
                "LLM_BASE_URL",
                "https://api.siliconflow.cn/v1/chat/completions",
            ),
            os.getenv("LLM1_MODEL")
            or os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
        )
    if provider == 2:
        return (
            os.getenv("LLM2_API_KEY") or os.getenv("MIMO_API_KEY", ""),
            os.getenv(
                "LLM2_BASE_URL",
                "https://token-plan-cn.xiaomimimo.com/v1",
            ),
            os.getenv("LLM2_MODEL", "mimo-v2.5-pro"),
        )
    raise ValueError("LLM_PROVIDER must be 0, 1, or 2")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _search_result_to_dict(item: Any) -> Dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    if is_dataclass(item):
        return asdict(item)
    return {
        "title": getattr(item, "title", ""),
        "url": getattr(item, "url", ""),
        "snippet": getattr(item, "snippet", ""),
        "content": getattr(item, "content", ""),
        "source": getattr(item, "source", ""),
        "content_source": getattr(item, "content_source", ""),
    }


def _clean_required(value: str, field_name: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        raise ValueError(f"{field_name} cannot be empty")
    return text


def _clean_competitors(values: Optional[Sequence[str]]) -> List[str]:
    results: List[str] = []
    seen: set[str] = set()
    for value in values or []:
        item = re.sub(r"\s+", " ", str(value or "")).strip()
        if item and item not in seen:
            seen.add(item)
            results.append(item)
    return results


def _safe_filename(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "_", value).strip("._")[:80] or "report"


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)


def _log(printer: Callable[[str], None], message: str) -> None:
    printer(message)

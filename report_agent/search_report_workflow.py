"""Search + report workflow owned by report_agent.

Workflow boundary:
1. Call upstream search through `report_agent.search_adapter`.
2. Pass search results into `report_agent.run_writing_agent`.

No downstream quality-agent dependency is used here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Sequence

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from report_agent.core import run_writing_agent
from report_agent.models import ReportPackage, WritingAgentConfig
from report_agent.search_adapter import (
    ReportSearchConfig,
    SearchBundle,
    search_for_report,
)

# Keep these defaults aligned with run_similar_product_reports.py.
LLM_PROVIDER = int(os.getenv("LLM_PROVIDER", "0"))

LLM0_API_KEY = (
    os.getenv("LLM0_API_KEY")
    or os.getenv("ARK_API_KEY")
    or ""
)
LLM0_BASE_URL = os.getenv("LLM0_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
LLM0_MODEL = os.getenv("LLM0_MODEL", "ep-20260514111325-xjmj7")

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL", "https://api.siliconflow.cn/v1/chat/completions"
)
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")

LLM2_API_KEY = os.getenv("LLM2_API_KEY") or os.getenv("MIMO_API_KEY") or ""
LLM2_BASE_URL = os.getenv("LLM2_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
LLM2_MODEL = os.getenv("LLM2_MODEL", "mimo-v2.5-pro")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_DIR = Path(__file__).resolve().parent / "logs"
DEFAULT_LATEST_LOG_PATH = DEFAULT_LOG_DIR / "latest_search_report_workflow.log"

_PROGRESS_PRINTER: Callable[[str], None] = lambda message: print(
    message, flush=True
)


@dataclass
class SearchReportWorkflowResult:
    """Output of the two-step search + report workflow."""

    task_id: str
    queries: List[str]
    search_result_count: int
    report_package: ReportPackage
    search_errors: List[str]
    output_paths: dict[str, str]


@dataclass
class WorkflowLogger:
    """Line-buffered workflow logger that mirrors terminal output to a file."""

    log_path: Path
    latest_log_path: Optional[Path] = None
    started_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.latest_log_path:
            self.latest_log_path.parent.mkdir(parents=True, exist_ok=True)
            self.latest_log_path.write_text("", encoding="utf-8")

    def log(self, message: str) -> None:
        elapsed = time.time() - self.started_at
        line = (
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            f"[+{elapsed:7.1f}s] {message}"
        )
        print(line, flush=True)
        log_paths = [self.log_path]
        if self.latest_log_path and self.latest_log_path != self.log_path:
            log_paths.append(self.latest_log_path)
        for log_path in log_paths:
            with log_path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")


def run_search_report_workflow(
    product_description: str,
    *,
    competitors: Optional[Sequence[str]] = None,
    search_config: Optional[ReportSearchConfig] = None,
    writing_config: Optional[WritingAgentConfig] = None,
    search_results: Optional[Iterable[Any]] = None,
    task_id: str = "search_report_task",
    target_domain: str = "",
    output_dir: Optional[Path] = None,
    progress_printer: Optional[Callable[[str], None]] = None,
) -> SearchReportWorkflowResult:
    """Run upstream search and then generate a ReportPackage."""

    if progress_printer:
        set_progress_printer(progress_printer)

    description = product_description.strip()
    if not description:
        raise ValueError("product_description cannot be empty")

    _log(f"[workflow] task_id={task_id}")
    _log(f"[workflow] product_description={description}")
    if competitors:
        _log(f"[workflow] competitors={', '.join(competitors)}")

    if search_results is None:
        active_search_config = search_config or ReportSearchConfig.from_env()
        active_search_config.progress_printer = _log
        _log("[workflow] step 1/2 search started")
        bundle = search_for_report(
            description,
            competitors=competitors,
            config=active_search_config,
        )
        results = bundle.results
        queries = bundle.queries
        errors = bundle.errors
    else:
        _log("[workflow] step 1/2 search skipped, using provided search_results")
        results = list(search_results)
        queries = []
        errors = []
        bundle = SearchBundle(queries=queries, results=results, errors=errors)
        del bundle
    _log(f"[workflow] search ready: results={len(results)} errors={len(errors)}")
    _log_search_results(results)

    if not results:
        raise RuntimeError(
            "No search results available for report generation. "
            f"Search errors: {'; '.join(errors) if errors else 'none'}"
        )

    active_writing_config = writing_config or build_writing_config_from_env()
    if progress_printer:
        active_writing_config.progress_printer = _log
    _log(
        "[workflow] step 2/2 report generation started "
        f"use_llm={active_writing_config.use_llm} model={active_writing_config.llm_model or 'none'}"
    )
    active_target_domain = target_domain or description
    package = run_writing_agent(
        results,
        config=active_writing_config,
        task_id=task_id,
        analysis_goal=f"基于搜索结果，为 {description} 生成竞品分析报告",
        target_domain=active_target_domain,
        competitors=list(competitors or []),
    )
    _log(
        "[workflow] report generation done "
        f"chars={len(package.report_markdown)} claims={len(package.claim_evidence_map)}"
    )

    output_paths = _write_outputs(package, output_dir, task_id) if output_dir else {}
    if output_paths:
        _log(
            f"[workflow] outputs written: {json.dumps(output_paths, ensure_ascii=False)}"
        )
    return SearchReportWorkflowResult(
        task_id=task_id,
        queries=queries,
        search_result_count=len(results),
        report_package=package,
        search_errors=errors,
        output_paths=output_paths,
    )


def build_writing_config_from_env(
    *, use_llm: Optional[bool] = None
) -> WritingAgentConfig:
    """Build report_agent LLM config without importing other workflow modules."""

    api_key, base_url, model = provider_llm_config()
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
            "REPORT_AGENT_TABLE_GAP_SEARCH_MAX_QUERIES", 6
        ),
        table_gap_search_all_pending=os.getenv(
            "REPORT_AGENT_TABLE_GAP_SEARCH_ALL_PENDING", "1"
        ).strip()
        != "0",
        table_gap_search_results_per_query=_env_int(
            "REPORT_AGENT_TABLE_GAP_SEARCH_RESULTS", 8
        ),
        table_gap_search_crawl_max_chars=_env_int(
            "REPORT_AGENT_TABLE_GAP_SEARCH_CRAWL_CHARS", 2500
        ),
        table_gap_search_timeout=_env_int("REPORT_AGENT_TABLE_GAP_SEARCH_TIMEOUT", 8),
        table_gap_search_max_rounds=_env_int(
            "REPORT_AGENT_TABLE_GAP_SEARCH_MAX_ROUNDS", 3
        ),
        table_gap_search_workers=_env_int("REPORT_AGENT_TABLE_GAP_SEARCH_WORKERS", 5),
        evidence_structurer_mode=int(os.getenv("REPORT_AGENT_EVIDENCE_MODE", "1")),
        export_comparison_tables=os.getenv("REPORT_AGENT_EXPORT_TABLES", "1").strip()
        != "0",
        table_export_dir=os.getenv(
            "REPORT_AGENT_TABLE_EXPORT_DIR", "reports/report_agent_tables"
        ),
        verbose=True,
    )


def set_progress_printer(progress_printer: Callable[[str], None]) -> None:
    global _PROGRESS_PRINTER
    _PROGRESS_PRINTER = progress_printer


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def provider_llm_config() -> tuple[str, str, str]:
    """Return LLM config using the same provider rules as the root workflow."""

    if LLM_PROVIDER == 0:
        return LLM0_API_KEY, LLM0_BASE_URL, LLM0_MODEL
    if LLM_PROVIDER == 1:
        return (
            os.getenv("LLM1_API_KEY") or LLM_API_KEY,
            os.getenv("LLM1_BASE_URL") or LLM_BASE_URL,
            os.getenv("LLM1_MODEL") or LLM_MODEL,
        )
    if LLM_PROVIDER == 2:
        return LLM2_API_KEY, LLM2_BASE_URL, LLM2_MODEL
    raise ValueError("LLM_PROVIDER must be 0, 1, or 2")


def provider_name(provider: int) -> str:
    names = {
        0: "豆包/火山 Ark",
        1: "SiliconFlow",
        2: "小米 MiMo",
    }
    return names.get(provider, "未知 provider")


def mask_key(key: str) -> str:
    if not key:
        return "未配置"
    if len(key) <= 10:
        return "*" * len(key)
    return f"{key[:6]}...{key[-4:]}"


def search_backend_name(backend: int) -> str:
    if backend == 0:
        return "博查搜索 + 传统爬虫抓正文"
    if backend == 1:
        return "博查搜索 + Playwright 抓正文"
    if backend == 2:
        return "博查搜索 + Crawl4AI 抓正文"
    return "未知搜索后端"


def print_startup_banner(
    *,
    args: argparse.Namespace,
    search_config: ReportSearchConfig,
    writing_config: WritingAgentConfig,
    logger: WorkflowLogger,
) -> None:
    _log("===== Report Agent Search + Report Workflow =====")
    _log(f"log_file: {logger.log_path}")
    if logger.latest_log_path:
        _log(f"latest_log_file: {logger.latest_log_path}")
    _log(
        "提示: 如果使用 conda run 且终端不实时输出，请加 "
        "`conda run --no-capture-output -n bytedance-ai-competition ...`"
    )
    if logger.latest_log_path:
        _log(f"也可以另开终端监控: tail -f {logger.latest_log_path}")
    _log("")
    _log("===== 输入参数 =====")
    _log(f"product_description: {args.product_description}")
    _log(f"competitors: {args.competitors or '未指定'}")
    _log(f"task_id: {args.task_id}")
    _log(f"target_domain: {args.target_domain or args.product_description}")
    _log(f"output_dir: {args.output_dir or '不落盘'}")
    _log(f"offline_smoke_test: {args.offline_smoke_test}")
    _log(f"no_llm: {args.no_llm}")
    _log("")
    _log("===== LLM API 提供商 =====")
    _log(f"provider: {LLM_PROVIDER} ({provider_name(LLM_PROVIDER)})")
    _log(f"base_url: {writing_config.llm_base_url or '未配置'}")
    _log(f"model: {writing_config.llm_model or '未配置'}")
    _log(f"api_key: {mask_key(writing_config.llm_api_key)}")
    _log(f"use_llm: {writing_config.use_llm}")
    _log("")
    _log("===== 搜索后端 =====")
    _log(f"search_source: {search_config.source}")
    _log(f"bocha_api_key: {mask_key(search_config.bocha_api_key)}")
    _log(f"google_api_key: {mask_key(search_config.google_api_key)}")
    _log(f"google_cx_id: {'已配置' if search_config.google_cx_id else '未配置'}")
    _log(f"proxy: {search_config.proxy or '未配置'}")
    _log(
        f"crawl_backend: {search_config.crawl_backend} "
        f"({search_backend_name(search_config.crawl_backend)})"
    )
    _log(f"query_count_per_competitor: {search_config.query_count}")
    _log(f"results_per_query: {search_config.results_per_query}")
    _log(f"max_search_results: {search_config.max_search_results}")
    _log(f"crawl_max_chars: {search_config.crawl_max_chars}")
    _log(f"crawl_min_chars: {search_config.crawl_min_chars}")
    _log(f"timeout: {search_config.timeout}s")
    _log("")


def mock_search_results() -> List[dict[str, Any]]:
    """Offline smoke-test data shaped like upstream SearchResult."""

    return [
        {
            "title": "AgentFlow 企业版产品介绍",
            "url": "https://example.com/agentflow",
            "snippet": "AgentFlow 面向企业团队，强调多步骤任务规划、工具调用和审批日志。",
            "content": (
                "AgentFlow 面向企业团队，支持把调研、数据整理和报告生成拆成多步骤任务。"
                "产品提供工具调用、执行状态展示、审批日志和权限控制，帮助团队在自动化执行时保留人工确认。"
            ),
            "source": "mock",
            "content_source": "offline smoke test",
        },
        {
            "title": "ResearchPilot 竞品调研 Agent 评测",
            "url": "https://example.com/researchpilot-review",
            "snippet": "ResearchPilot 模板丰富，但高级配置需要理解 API 和数据源权限。",
            "content": (
                "ResearchPilot 提供竞品调研模板、资料归纳和引用导出。"
                "它适合产品经理快速生成初稿，但连接企业内部数据源时配置较复杂。"
            ),
            "source": "mock",
            "content_source": "offline smoke test",
        },
        {
            "title": "AutoPM Agent 定价与集成说明",
            "url": "https://example.com/autopm-pricing",
            "snippet": "AutoPM Agent 提供团队订阅和企业套餐，支持 API、Slack 与知识库集成。",
            "content": (
                "AutoPM Agent 采用团队订阅和企业套餐，主打 API、Slack、知识库和项目管理工具集成。"
                "企业套餐强调审计、权限、专属支持和数据隔离。"
            ),
            "source": "mock",
            "content_source": "offline smoke test",
        },
    ]


def _write_outputs(
    package: ReportPackage,
    output_dir: Path,
    task_id: str,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_safe_filename(task_id)}"
    report_path = output_dir / f"{prefix}_report.md"
    package_path = output_dir / f"{prefix}_report_package.json"
    report_path.write_text(package.report_markdown, encoding="utf-8")
    package_path.write_text(package.to_json(), encoding="utf-8")
    return {
        "report_markdown": str(report_path),
        "report_package": str(package_path),
    }


def _log_search_results(results: List[Any], limit: int = 12) -> None:
    if not results:
        return
    _log("===== 搜索结果概览 =====")
    for index, result in enumerate(results[:limit], 1):
        title = _compact(_item_value(result, "title"), 90)
        url = _compact(_item_value(result, "url"), 120)
        content = _item_value(result, "content") or ""
        snippet = _item_value(result, "snippet") or ""
        content_source = _item_value(result, "content_source") or "unknown"
        _log(
            f"[source {index:02d}] title={title} "
            f"content_chars={len(content)} snippet_chars={len(snippet)} "
            f"content_source={content_source}"
        )
        _log(f"[source {index:02d}] url={url}")
    if len(results) > limit:
        _log(f"... 还有 {len(results) - limit} 条搜索结果未展示")
    _log("")


def _safe_filename(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "_", value).strip("._")[:80] or "report"


def _split_csv(value: str) -> List[str]:
    return [part.strip() for part in re.split(r"[,，、;\n]+", value) if part.strip()]


def _log(message: str) -> None:
    _PROGRESS_PRINTER(message)


def _compact(value: object, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > max_chars:
        return text[: max_chars - 3] + "..."
    return text


def _item_value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _default_log_path(task_id: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_LOG_DIR / f"{timestamp}_{_safe_filename(task_id)}.log"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run report_agent search+report workflow"
    )
    parser.add_argument("product_description", help="产品方向或竞品分析需求")
    parser.add_argument("--competitors", default="", help="已知竞品名，逗号分隔")
    parser.add_argument(
        "--search-source",
        choices=["bocha", "google", "duckduckgo"],
        default=None,
        help="搜索来源；默认读取 SEARCH_SOURCE 环境变量",
    )
    parser.add_argument("--task-id", default="search_report_task")
    parser.add_argument("--target-domain", default="")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--offline-smoke-test", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--log-file", type=Path, help="写入详细运行日志的路径")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    logger = WorkflowLogger(
        args.log_file or _default_log_path(args.task_id),
        latest_log_path=DEFAULT_LATEST_LOG_PATH,
    )
    set_progress_printer(logger.log)

    search_config = ReportSearchConfig.from_env()
    if args.search_source:
        search_config.source = args.search_source
    search_config.progress_printer = logger.log
    writing_config = build_writing_config_from_env(use_llm=not args.no_llm)

    print_startup_banner(
        args=args,
        search_config=search_config,
        writing_config=writing_config,
        logger=logger,
    )

    result = run_search_report_workflow(
        args.product_description,
        competitors=_split_csv(args.competitors),
        search_config=search_config,
        writing_config=writing_config,
        search_results=mock_search_results() if args.offline_smoke_test else None,
        task_id=args.task_id,
        target_domain=args.target_domain,
        output_dir=args.output_dir,
        progress_printer=logger.log,
    )

    _log("===== WORKFLOW SUMMARY =====")
    _log(json.dumps(_summary(result), ensure_ascii=False, indent=2))


def _summary(result: SearchReportWorkflowResult) -> dict[str, Any]:
    return {
        "task_id": result.task_id,
        "queries": result.queries,
        "search_result_count": result.search_result_count,
        "search_errors": result.search_errors,
        "report_chars": len(result.report_package.report_markdown),
        "claim_count": len(result.report_package.claim_evidence_map),
        "missing_info": result.report_package.missing_info,
        "low_confidence_claims": result.report_package.low_confidence_claims,
        "output_paths": result.output_paths,
    }


if __name__ == "__main__":
    main()

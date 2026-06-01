"""写作 Agent 的数据模型。

本模块只定义跨节点传递的数据结构，不包含业务逻辑。这样做可以让
Evidence/Insight/SWOT/Report 各节点的输入输出边界保持稳定，也方便
下游质检 Agent 直接消费 `ReportPackage`。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


@dataclass
class WritingAgentConfig:
    """Runtime configuration for the writing agent.

    `use_llm=False` makes the whole workflow deterministic and offline. This is
    the default used by the smoke test so the test never calls a cloud API.
    """

    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    use_llm: bool = True
    temperature: float = 0.2
    max_tokens: int = 0
    llm_timeout: int = 300
    llm_batch_workers: int = field(
        default_factory=lambda: _env_int("REPORT_AGENT_BATCH_WORKERS", 8)
    )
    table_gap_search_enabled: bool = field(
        default_factory=lambda: _env_bool("REPORT_AGENT_TABLE_GAP_SEARCH", True)
    )
    table_gap_search_max_queries: int = field(
        default_factory=lambda: _env_int("REPORT_AGENT_TABLE_GAP_SEARCH_MAX_QUERIES", 6)
    )
    table_gap_search_all_pending: bool = field(
        default_factory=lambda: _env_bool("REPORT_AGENT_TABLE_GAP_SEARCH_ALL_PENDING", True)
    )
    table_gap_search_results_per_query: int = field(
        default_factory=lambda: _env_int("REPORT_AGENT_TABLE_GAP_SEARCH_RESULTS", 8)
    )
    table_gap_search_crawl_max_chars: int = field(
        default_factory=lambda: _env_int("REPORT_AGENT_TABLE_GAP_SEARCH_CRAWL_CHARS", 5500)
    )
    table_gap_search_timeout: int = field(
        default_factory=lambda: _env_int("REPORT_AGENT_TABLE_GAP_SEARCH_TIMEOUT", 8)
    )
    table_gap_query_timeout: int = field(
        default_factory=lambda: _env_int("REPORT_AGENT_TABLE_GAP_QUERY_TIMEOUT", 45)
    )
    table_gap_search_max_rounds: int = field(
        default_factory=lambda: _env_int("REPORT_AGENT_TABLE_GAP_SEARCH_MAX_ROUNDS", 3)
    )
    table_gap_search_workers: int = field(
        default_factory=lambda: _env_int("REPORT_AGENT_TABLE_GAP_SEARCH_WORKERS", 5)
    )
    search_source: str = field(default_factory=lambda: os.getenv("SEARCH_SOURCE", "bocha"))
    search_bocha_api_key: str = field(default_factory=lambda: os.getenv("BOCHA_API_KEY", ""))
    search_google_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_API_KEY", ""))
    search_google_cx_id: str = field(default_factory=lambda: os.getenv("GOOGLE_CX_ID", ""))
    search_proxy: str = field(default_factory=lambda: os.getenv("HTTP_PROXY", ""))
    search_backend: int = field(default_factory=lambda: _env_int("SEARCH_BACKEND", 0))
    max_source_chars: int = 0
    max_prompt_sources: int = 0
    max_evidence_cards: int = 0
    # 0 = rules only, 1 = rule sections + LLM schema adapter, 2 = whole-source LLM first.
    evidence_structurer_mode: int = 1
    use_llm_report_composer: bool = False
    print_comparison_tables: bool = field(
        default_factory=lambda: _env_bool("REPORT_AGENT_PRINT_TABLES", True)
    )
    export_comparison_tables: bool = field(
        default_factory=lambda: _env_bool("REPORT_AGENT_EXPORT_TABLES", True)
    )
    table_export_dir: str = field(
        default_factory=lambda: os.getenv(
            "REPORT_AGENT_TABLE_EXPORT_DIR", "reports/report_agent_tables"
        )
    )
    verbose: bool = True
    progress_printer: Optional[Callable[[str], None]] = print


@dataclass
class SourceRecord:
    """上游搜索结果的标准化形态。

    上游可能传入 SearchResult、dict 或任意对象；进入写作链路前统一转成
    SourceRecord，后续所有 evidence 都通过 `source_id` 回溯到这里。
    """

    source_id: str
    title: str
    url: str
    snippet: str = ""
    content: str = ""
    source: str = ""
    content_source: str = ""
    publish_date: Optional[str] = None
    retrieved_at: Optional[str] = None
    credibility_score: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceCard:
    """最小证据单元。

    一张卡只表达一个 claim，并保留原文片段。后续洞察、SWOT、策略建议都
    必须绑定 evidence_id，避免报告变成无来源的自然语言总结。
    """

    evidence_id: str
    source_id: str
    competitor: Optional[str]
    dimension: str
    claim: str
    raw_excerpt: str
    confidence: float
    freshness: str = "unknown"
    importance_for_pm: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PMInsight:
    """产品经理可消费的结构化洞察。"""

    insight_id: str
    type: str
    title: str
    description: str
    related_competitors: List[str]
    evidence_ids: List[str]
    pm_value: str
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SWOTItem:
    """SWOT 条目。

    每条 SWOT 都需要说明结论、影响、PM 启发和证据来源，防止生成空泛模板。
    """

    point: str
    why_it_matters: str
    evidence_ids: List[str]
    pm_implication: str
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SWOTResult:
    strengths: List[SWOTItem] = field(default_factory=list)
    weaknesses: List[SWOTItem] = field(default_factory=list)
    opportunities: List[SWOTItem] = field(default_factory=list)
    threats: List[SWOTItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProductRecommendation:
    """面向产品行动的策略建议，默认用于 30/60/90 天路线图。"""

    priority: str
    timeframe: str
    action: str
    reason: str
    expected_impact: str
    risk: str
    evidence_ids: List[str]
    success_metric: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReportState:
    """写作链路内部状态。

    ReportState 是中间态，允许各 agent 逐步补齐结构化字段；最终对外只暴露
    ReportPackage，避免下游依赖内部实现细节。
    """

    task_id: str
    analysis_goal: str
    target_domain: str
    competitors: List[str]
    sources: List[SourceRecord]
    evidence_cards: List[EvidenceCard] = field(default_factory=list)
    pm_insights: List[PMInsight] = field(default_factory=list)
    competitor_profiles: List[Dict[str, Any]] = field(default_factory=list)
    comparison_tables: List[Dict[str, Any]] = field(default_factory=list)
    swot: SWOTResult = field(default_factory=SWOTResult)
    recommendations: List[ProductRecommendation] = field(default_factory=list)
    report_markdown: str = ""
    claim_evidence_map: List[Dict[str, Any]] = field(default_factory=list)
    generation_trace: List[Dict[str, Any]] = field(default_factory=list)
    missing_info: List[str] = field(default_factory=list)
    low_confidence_claims: List[str] = field(default_factory=list)


@dataclass
class ReportPackage:
    """写作 Agent 的最终输出包。

    下游检测模块需要的不只是 Markdown，还包括结构化分析、证据映射和生成轨迹。
    """

    task_id: str
    report_markdown: str
    structured_analysis: Dict[str, Any]
    claim_evidence_map: List[Dict[str, Any]]
    generation_trace: List[Dict[str, Any]]
    sources: List[Dict[str, Any]]
    missing_info: List[str] = field(default_factory=list)
    low_confidence_claims: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, *, ensure_ascii: bool = False, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=ensure_ascii, indent=indent)

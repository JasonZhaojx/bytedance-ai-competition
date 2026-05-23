"""Multi-Agent orchestration system for competitive product analysis."""

from .search_agent.crawler import fetch_page_text
from .search_agent.llm_agent import AgentConfig, AgentEvent, run_agent, run_agent_generator
from .search_agent.recursive_search_workflow import (
    EvidenceItem,
    RecursiveSearchConfig,
    RecursiveSearchResult,
    SearchNode,
    TreeSearchResult,
    render_tree_summary,
    run_recursive_search,
    run_tree_search,
)
from .search_agent.search import SearchConfig, SearchResult, SearchSource, search, unified_search
from .analysis_agent.positioning_product_workflow import (
    PositioningProductConfig,
    PositioningProductResult,
    collect_search_results,
    extract_product_names,
    rewrite_search_queries,
    run_positioning_product_search,
)
from .analysis_agent.product_workflow import ProductWorkflowConfig, ProductWorkflowResult, run_product_workflow
from .quality_agent.quality_agent import (
    ConfidenceLevel,
    IssueSeverity,
    IssueType,
    QualityConfig,
    QualityIssue,
    QualityReport,
    inspect_quality,
    llm_enhanced_inspect,
)

__all__ = [
    "AgentConfig",
    "AgentEvent",
    "ConfidenceLevel",
    "EvidenceItem",
    "IssueSeverity",
    "IssueType",
    "PositioningProductConfig",
    "PositioningProductResult",
    "ProductWorkflowConfig",
    "ProductWorkflowResult",
    "QualityConfig",
    "QualityIssue",
    "QualityReport",
    "RecursiveSearchConfig",
    "RecursiveSearchResult",
    "SearchNode",
    "SearchConfig",
    "SearchResult",
    "SearchSource",
    "TreeSearchResult",
    "collect_search_results",
    "extract_product_names",
    "fetch_page_text",
    "inspect_quality",
    "llm_enhanced_inspect",
    "render_tree_summary",
    "rewrite_search_queries",
    "run_agent",
    "run_agent_generator",
    "run_positioning_product_search",
    "run_product_workflow",
    "run_recursive_search",
    "run_tree_search",
    "search",
    "unified_search",
]

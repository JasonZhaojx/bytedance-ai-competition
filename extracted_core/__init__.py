"""Reusable core for recursive web search agents."""

from agents.search_agent.crawler import fetch_page_text
from agents.search_agent.llm_agent import AgentConfig, AgentEvent, run_agent, run_agent_generator
from agents.analysis_agent.positioning_product_workflow import (
    PositioningProductConfig,
    PositioningProductResult,
    collect_search_results,
    extract_product_names,
    rewrite_search_queries,
    run_positioning_product_search,
)
from agents.analysis_agent.product_workflow import ProductWorkflowConfig, ProductWorkflowResult, run_product_workflow
from agents.quality_agent.core import QualityConfig, QualityIssue, QualityReport, IssueSeverity, IssueType, inspect_quality, llm_enhanced_inspect
from agents.search_agent.recursive_search_workflow import (
    EvidenceItem,
    RecursiveSearchConfig,
    RecursiveSearchResult,
    SearchNode,
    TreeSearchResult,
    render_tree_summary,
    run_recursive_search,
    run_tree_search,
)
from agents.search_agent.search import SearchConfig, SearchResult, SearchSource, search, unified_search

__all__ = [
    "AgentConfig",
    "AgentEvent",
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

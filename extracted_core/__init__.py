"""Reusable core for recursive web search agents."""

from .crawler import fetch_page_text
from .llm_agent import AgentConfig, AgentEvent, run_agent, run_agent_generator
from .positioning_product_workflow import (
    PositioningProductConfig,
    PositioningProductResult,
    collect_search_results,
    extract_product_names,
    rewrite_search_queries,
    run_positioning_product_search,
)
from .recursive_search_workflow import (
    EvidenceItem,
    RecursiveSearchConfig,
    RecursiveSearchResult,
    SearchNode,
    TreeSearchResult,
    render_tree_summary,
    run_recursive_search,
    run_tree_search,
)
from .search import SearchConfig, SearchResult, SearchSource, search, unified_search

__all__ = [
    "AgentConfig",
    "AgentEvent",
    "EvidenceItem",
    "PositioningProductConfig",
    "PositioningProductResult",
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
    "render_tree_summary",
    "rewrite_search_queries",
    "run_agent",
    "run_agent_generator",
    "run_positioning_product_search",
    "run_recursive_search",
    "run_tree_search",
    "search",
    "unified_search",
]

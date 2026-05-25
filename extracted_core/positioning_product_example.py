"""Simple CLI for product-positioning search."""

from __future__ import annotations

import os
import sys
from pathlib import Path


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extracted_core.positioning_product_workflow import (
    PositioningProductConfig,
    run_positioning_product_search,
)
from extracted_core.search import SearchConfig, SearchSource


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def main() -> None:
    product_description = " ".join(sys.argv[1:]).strip() or env(
        "PRODUCT_DESCRIPTION",
        "AI coding agent for local repositories",
    )

    source = SearchSource(env("SEARCH_SOURCE", SearchSource.BOCHA.value))
    search_config = SearchConfig(
        source=source,
        bocha_api_key=env("BOCHA_API_KEY"),
        google_api_key=env("GOOGLE_API_KEY"),
        google_cx_id=env("GOOGLE_CX_ID"),
        proxy=env("HTTP_PROXY") or None,
        count=int(env("SEARCH_COUNT", "5")),
        max_search_results=int(env("SEARCH_COUNT", "5")),
        crawl_max_chars=int(env("CRAWL_MAX_CHARS", "2500")),
        crawl_min_chars=120,
        timeout=int(env("SEARCH_TIMEOUT", "20")),
    )

    config = PositioningProductConfig(
        llm_api_key=env("LLM_API_KEY") or env("ARK_API_KEY"),
        llm_base_url=env("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        llm_model=env("LLM_MODEL", "Doubao-Seed-2.0-lite"),
        search_config=search_config,
        results_per_query=int(env("SEARCH_COUNT", "5")),
    )

    if not config.llm_api_key:
        raise RuntimeError("Please set LLM_API_KEY or ARK_API_KEY.")
    if source == SearchSource.BOCHA and not search_config.bocha_api_key:
        raise RuntimeError("Please set BOCHA_API_KEY, or set SEARCH_SOURCE=duckduckgo/google.")

    result = run_positioning_product_search(product_description, config)

    print("\n===== QUERIES =====")
    for query in result.queries:
        print(f"- {query}")

    print("\n===== SUMMARY =====")
    print(result.summary)


if __name__ == "__main__":
    main()

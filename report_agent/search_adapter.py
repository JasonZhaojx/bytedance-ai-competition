"""Search adapter for report_agent.

This file is the only place where report_agent touches the upstream search
module. It imports and calls `extracted_core.search` functions, but does not
modify upstream source code. Defaults stay aligned with
`run_similar_product_reports.py`; downstream callers should not tune search
parameters through report_agent.
"""

from __future__ import annotations

import os
import re
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Sequence

try:
    from extracted_core.search import (
        SearchConfig,
        SearchResult,
        SearchSource,
        search,
    )
except ImportError as exc:  # pragma: no cover - import error should be explicit.
    raise ImportError(
        "report_agent.search_adapter requires extracted_core.search to be importable"
    ) from exc


@dataclass
class ReportSearchConfig:
    """Internal runtime config mirroring the root search defaults.

    The fields exist so report_agent can pass credentials and logging callbacks
    into upstream search. They are not intended as a downstream tuning surface.
    """

    source: str = "bocha"
    bocha_api_key: str = ""
    google_api_key: str = ""
    google_cx_id: str = ""
    proxy: Optional[str] = None
    query_count: int = 3
    results_per_query: int = 3
    max_search_results: int = 3
    crawl_max_chars: int = 0
    crawl_min_chars: int = 120
    crawl_backend: int = 0
    timeout: int = 20
    gap_query_timeout: int = 45
    workers: int = 0
    verbose: bool = True
    progress_printer: Optional[Callable[[str], None]] = print

    @classmethod
    def from_env(cls) -> "ReportSearchConfig":
        search_count = int(os.getenv("SEARCH_COUNT", "3"))
        return cls(
            source=os.getenv("SEARCH_SOURCE", "bocha"),
            bocha_api_key=os.getenv("BOCHA_API_KEY", ""),
            google_api_key=os.getenv("GOOGLE_API_KEY", ""),
            google_cx_id=os.getenv("GOOGLE_CX_ID", ""),
            proxy=os.getenv("HTTP_PROXY") or None,
            query_count=int(os.getenv("QUERY_COUNT", "3")),
            results_per_query=search_count,
            max_search_results=search_count,
            crawl_max_chars=int(os.getenv("REPORT_AGENT_CRAWL_MAX_CHARS", "0")),
            crawl_min_chars=120,
            crawl_backend=int(os.getenv("SEARCH_BACKEND", "0")),
            timeout=20,
            gap_query_timeout=int(os.getenv("REPORT_AGENT_TABLE_GAP_QUERY_TIMEOUT", "45")),
            workers=int(os.getenv("REPORT_AGENT_TABLE_GAP_SEARCH_WORKERS", "5")),
        )


@dataclass
class SearchBundle:
    """Search output passed into report_agent."""

    queries: List[str]
    results: List[SearchResult]
    errors: List[str] = field(default_factory=list)


def search_for_report(
    product_description: str,
    *,
    competitors: Optional[Sequence[str]] = None,
    config: Optional[ReportSearchConfig] = None,
) -> SearchBundle:
    """Run upstream search and return deduplicated results for report_agent."""

    runtime_config = config or ReportSearchConfig.from_env()
    queries = build_report_queries(
        product_description,
        competitors=competitors,
        query_count=runtime_config.query_count,
    )
    search_config = to_upstream_search_config(runtime_config)
    _log(
        runtime_config,
        "[search] source={source} queries={query_count} results_per_query={count} "
        "crawl_backend={backend} timeout={timeout}s".format(
            source=runtime_config.source,
            query_count=len(queries),
            count=runtime_config.results_per_query,
            backend=runtime_config.crawl_backend,
            timeout=runtime_config.timeout,
        ),
    )

    results: List[SearchResult] = []
    errors: List[str] = []
    seen_urls: set[str] = set()
    for index, query in enumerate(queries, 1):
        _log(runtime_config, f"[search] query {index}/{len(queries)} start: {query}")
        try:
            query_results = search(query, search_config)
        except Exception as exc:
            errors.append(f"{query}: {exc}")
            _log(runtime_config, f"[search] query {index}/{len(queries)} failed: {exc}")
            continue
        added = 0
        for result in query_results:
            normalized_url = (result.url or "").split("#", 1)[0].rstrip("/")
            dedupe_key = normalized_url or f"{result.title}:{result.snippet}"
            if not dedupe_key or dedupe_key in seen_urls:
                continue
            seen_urls.add(dedupe_key)
            results.append(result)
            added += 1
        _log(
            runtime_config,
            f"[search] query {index}/{len(queries)} done: raw={len(query_results)} added={added} total={len(results)}",
        )
    _log(runtime_config, f"[search] finished: results={len(results)} errors={len(errors)}")
    return SearchBundle(queries=queries, results=results, errors=errors)


def search_queries_for_report(
    queries: Sequence[str],
    *,
    config: Optional[ReportSearchConfig] = None,
) -> SearchBundle:
    """Run exact LLM-planned queries through extracted_core.search."""

    runtime_config = config or ReportSearchConfig.from_env()
    query_count = int(getattr(runtime_config, "query_count", 0) or 0)
    clean_queries = _dedupe(queries)
    if query_count > 0:
        clean_queries = clean_queries[:query_count]
    if not clean_queries:
        return SearchBundle(queries=[], results=[], errors=[])
    search_config = to_upstream_search_config(runtime_config)
    results: List[SearchResult] = []
    errors: List[str] = []
    seen_urls: set[str] = set()
    configured_workers = int(getattr(runtime_config, "workers", 0) or 0)
    if configured_workers <= 0:
        max_workers = min(len(clean_queries), 5)
    else:
        max_workers = min(len(clean_queries), max(1, configured_workers), 5)
    _log(
        runtime_config,
        "[search] exact queries={query_count} results_per_query={count} "
        "crawl_backend={backend} timeout={timeout}s query_timeout={query_timeout}s workers={workers}".format(
            query_count=len(clean_queries),
            count=runtime_config.results_per_query,
            backend=runtime_config.crawl_backend,
            timeout=runtime_config.timeout,
            query_timeout=runtime_config.gap_query_timeout,
            workers=max_workers,
        ),
    )

    def run_one(index_query: tuple[int, str]) -> tuple[int, str, List[SearchResult], Optional[str]]:
        index, query = index_query
        _log(runtime_config, f"[search] gap query {index}/{len(clean_queries)} start: {query}")
        try:
            query_results = search(query, search_config)
        except Exception as exc:
            _log(runtime_config, f"[search] gap query {index}/{len(clean_queries)} failed: {exc}")
            return index, query, [], str(exc)
        return index, query, query_results, None

    query_results_by_index: List[tuple[int, str, List[SearchResult], Optional[str]]] = []
    query_timeout = max(1, int(getattr(runtime_config, "gap_query_timeout", 45) or 45))
    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="report-gap-search")
    future_map = {
        executor.submit(run_one, item): item
        for item in enumerate(clean_queries, 1)
    }
    started_at = {future: time.monotonic() for future in future_map}
    pending = set(future_map)
    try:
        while pending:
            done, pending = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
            for future in done:
                query_results_by_index.append(future.result())
            now = time.monotonic()
            for future in list(pending):
                if now - started_at[future] < query_timeout:
                    continue
                index, query = future_map[future]
                pending.remove(future)
                future.cancel()
                _log(
                    runtime_config,
                    f"[search] gap query {index}/{len(clean_queries)} timeout after {query_timeout}s",
                )
                query_results_by_index.append((index, query, [], f"timeout after {query_timeout}s"))
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    for index, query, query_results, error in sorted(query_results_by_index, key=lambda item: item[0]):
        if error:
            errors.append(f"{query}: {error}")
            continue
        added = 0
        for result in query_results:
            normalized_url = (result.url or "").split("#", 1)[0].rstrip("/")
            dedupe_key = normalized_url or f"{result.title}:{result.snippet}"
            if not dedupe_key or dedupe_key in seen_urls:
                continue
            seen_urls.add(dedupe_key)
            results.append(result)
            added += 1
        _log(
            runtime_config,
            f"[search] gap query {index}/{len(clean_queries)} done: raw={len(query_results)} added={added} total={len(results)}",
        )
    _log(runtime_config, f"[search] gap search finished: results={len(results)} errors={len(errors)}")
    return SearchBundle(queries=clean_queries, results=results, errors=errors)


def build_report_queries(
    product_description: str,
    *,
    competitors: Optional[Sequence[str]] = None,
    query_count: int = 3,
) -> List[str]:
    """Build conservative product-report search queries."""

    description = _clean(product_description)
    competitor_names = [_clean(name) for name in competitors or [] if _clean(name)]

    queries: List[str] = []
    if competitor_names:
        for name in competitor_names:
            candidates = [
                f"{name} {description} 功能 定价 官方 文档",
                f"{name} AI 编程助手 评测 用户评价 优势 缺点",
                f"{name} AI IDE 使用场景 企业版 数据安全 集成",
                f"{name} pricing features review AI coding assistant",
            ]
            queries.extend(candidates[: max(1, query_count)])
    else:
        queries.extend(
            [
                f"{description} 竞品 对比",
                f"{description} 功能 定价 用户评价",
                f"{description} 替代品 优势 短板",
            ]
        )
        return _dedupe(queries)[: max(1, query_count)]

    return _dedupe(queries)


def to_upstream_search_config(config: ReportSearchConfig) -> SearchConfig:
    """Convert report_agent config into extracted_core.search.SearchConfig."""

    return SearchConfig(
        source=SearchSource(config.source),
        bocha_api_key=config.bocha_api_key,
        google_api_key=config.google_api_key,
        google_cx_id=config.google_cx_id,
        proxy=config.proxy,
        count=config.results_per_query,
        max_search_results=config.max_search_results,
        crawl_max_chars=config.crawl_max_chars,
        crawl_min_chars=config.crawl_min_chars,
        crawl_backend=config.crawl_backend,
        timeout=config.timeout,
        total_timeout=getattr(config, "gap_query_timeout", 0),
    )


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _dedupe(values: Iterable[str]) -> List[str]:
    results: List[str] = []
    seen: set[str] = set()
    for value in values:
        item = _clean(value)
        if item and item not in seen:
            seen.add(item)
            results.append(item)
    return results


def _log(config: ReportSearchConfig, message: str) -> None:
    if config.verbose and config.progress_printer:
        config.progress_printer(message)
        sys.stdout.flush()

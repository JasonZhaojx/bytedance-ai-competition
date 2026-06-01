"""LLM query rewrite + search + product-name extraction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, List, Optional

from .llm_client import chat_content
from .search import SearchConfig, SearchResult, search


@dataclass
class PositioningProductConfig:
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    search_config: SearchConfig
    query_count: int = 3
    results_per_query: int = 5
    max_search_text_chars: int = 8000
    temperature: float = 0.2
    max_tokens: int = 1200
    llm_timeout: int = 240
    verbose: bool = True
    progress_printer: Optional[Callable[[str], None]] = print
    search_func: Optional[Callable[[str, SearchConfig], List[SearchResult]]] = None


@dataclass
class PositioningProductResult:
    product_description: str
    queries: List[str]
    search_results: List[SearchResult]
    product_names: List[str]


def _log(config: PositioningProductConfig, message: str) -> None:
    if config.verbose and config.progress_printer:
        config.progress_printer(message)


def _json_list_from_text(text: str) -> List[str]:
    cleaned = text.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", cleaned, flags=re.DOTALL)
        if not match:
            return []
        data = json.loads(match.group(0))

    if not isinstance(data, list):
        return []
    values = []
    seen = set()
    for item in data:
        if not isinstance(item, str):
            continue
        value = " ".join(item.split())
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def rewrite_search_queries(product_description: str, config: PositioningProductConfig) -> List[str]:
    prompt = f"""
你是搜索关键词改写助手。

用户输入：
{product_description}

任务：
把用户输入改写成适合搜索“类似产品/同类产品/竞品/替代品”的搜索关键词。

要求：
- 返回 {config.query_count} 个搜索关键词。
- 关键词要短，适合直接放进搜索引擎。
- 尽量覆盖产品定位、目标用户、使用场景、替代品/竞品这些角度。
- 不要解释，不要 Markdown。
- 只返回 JSON 数组，例如：
["关键词1", "关键词2", "关键词3"]
""".strip()

    _log(config, "[llm] rewrite search queries")
    content = chat_content(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
        messages=[
            {"role": "system", "content": "你只输出 JSON 数组。"},
            {"role": "user", "content": prompt},
        ],
        temperature=config.temperature,
        max_tokens=500,
        timeout=config.llm_timeout,
    )
    queries = _json_list_from_text(content)
    if queries:
        return queries[: config.query_count]

    product = " ".join(product_description.split())
    return [
        f"{product} 类似产品",
        f"{product} 同类产品",
        f"{product} 竞品 替代品",
    ][: config.query_count]


def collect_search_results(
    queries: List[str],
    config: PositioningProductConfig,
) -> List[SearchResult]:
    results: List[SearchResult] = []
    seen_urls = set()
    original_count = config.search_config.count
    original_max_results = config.search_config.max_search_results

    try:
        config.search_config.count = config.results_per_query
        config.search_config.max_search_results = max(
            config.search_config.max_search_results,
            config.results_per_query,
        )

        for query in queries:
            _log(config, f"[search] {query}")
            try:
                search_runner = config.search_func or search
                for item in search_runner(query, config.search_config):
                    url = (item.url or "").split("#", 1)[0].rstrip("/")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    results.append(item)
            except Exception as exc:
                _log(config, f"[search] failed: {exc}")
    finally:
        config.search_config.count = original_count
        config.search_config.max_search_results = original_max_results

    _log(config, f"[search] kept {len(results)} results")
    return results


def _format_search_results(results: List[SearchResult], max_chars: int) -> str:
    sections = []
    used_chars = 0
    for index, item in enumerate(results, 1):
        text = item.content or item.snippet
        section = "\n".join(
            [
                f"[{index}] {item.title}",
                f"URL: {item.url}",
                f"Text: {text}",
            ]
        )
        if max_chars and used_chars + len(section) > max_chars:
            section = section[: max(0, max_chars - used_chars)]
        if not section:
            break
        sections.append(section)
        used_chars += len(section)
        if max_chars and used_chars >= max_chars:
            break
    return "\n\n".join(sections)


def extract_product_names(
    product_description: str,
    results: List[SearchResult],
    config: PositioningProductConfig,
) -> List[str]:
    if not results:
        return []

    prompt = f"""
你是产品名抽取助手。

用户想找：
{product_description}

搜索结果：
{_format_search_results(results, config.max_search_text_chars)}

任务：
从搜索结果中提取和用户需求相关的产品名称。

要求：
- 只返回产品名称列表。
- 不要返回公司名、文章标题、泛泛的类别词。
- 不要编造搜索结果里没有出现的产品。
- 优先保留真实产品、工具、平台、插件或服务名称；如果同名产品明显不是同一类，只保留和用户需求相关的那个名称。
- 去重。
- 最多返回 20 个。
- 只返回 JSON 数组，例如：
["产品A", "产品B", "产品C"]
""".strip()

    _log(config, "[llm] extract product names")
    content = chat_content(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
        messages=[
            {"role": "system", "content": "你只输出 JSON 数组。"},
            {"role": "user", "content": prompt},
        ],
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        timeout=config.llm_timeout,
    )
    print("[test]",prompt)
    return _json_list_from_text(content)


def run_positioning_product_search(
    product_description: str,
    config: PositioningProductConfig,
) -> PositioningProductResult:
    queries = rewrite_search_queries(product_description, config)
    results = collect_search_results(queries, config)
    product_names = extract_product_names(product_description, results, config)
    return PositioningProductResult(
        product_description=product_description,
        queries=queries,
        search_results=results,
        product_names=product_names,
    )

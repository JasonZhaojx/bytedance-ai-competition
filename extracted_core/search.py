"""Core search providers plus crawl-enriched result formatting."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Iterable, List, Optional
import asyncio
import re
import time

import requests
from duckduckgo_search import DDGS

from .crawler import fetch_page_text


class SearchSource(str, Enum):
    BOCHA = "bocha"
    GOOGLE = "google"
    DUCKDUCKGO = "duckduckgo"


DEFAULT_BLACKLIST = [
    "baidu.com",
    "zhihu.com",
    "tieba.baidu.com",
    "zhidao.baidu.com",
    "bilibili.com",
    "csdn.net",
]


@dataclass
class SearchConfig:
    source: SearchSource = SearchSource.DUCKDUCKGO
    bocha_api_key: str = ""
    google_api_key: str = ""
    google_cx_id: str = ""
    proxy: Optional[str] = None
    count: int = 3
    max_search_results: int = 10
    blacklist: List[str] = field(default_factory=lambda: list(DEFAULT_BLACKLIST))
    crawl_max_chars: int = 5000
    crawl_min_chars: int = 200
    crawl_backend: int = 0
    target_language: Optional[str] = None
    timeout: int = 15
    total_timeout: int = 0
    query_started_at: float = 0.0


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    content: str = ""
    source: str = ""
    content_source: str = ""


def _is_blacklisted(url: str, blacklist: Iterable[str]) -> bool:
    return any(domain in url for domain in blacklist)


def _fetch_with_playwright(url: str, config: SearchConfig) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            locale="zh-CN",
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        page.set_default_timeout(max(1000, config.timeout * 1000))

        def block_heavy_assets(route) -> None:
            if route.request.resource_type in {"image", "media", "font"}:
                route.abort()
            else:
                route.continue_()

        page.route("**/*", block_heavy_assets)
        try:
            try:
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=max(1000, config.timeout * 1000),
                )
            except Exception as exc:
                print(f"[playwright] goto warning: {url} ({exc})")
                return ""

            page.wait_for_timeout(1000)
            try:
                page.evaluate("window.stop()")
            except Exception:
                pass

            for _ in range(2):
                try:
                    page.mouse.wheel(0, 1800)
                    page.wait_for_timeout(400)
                except Exception:
                    break

            try:
                html = page.content()
            except Exception as exc:
                print(f"[playwright] page.content warning: {url} ({exc})")
                return _extract_visible_text_from_page(page, config.crawl_max_chars)

            import trafilatura

            content = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=False,
                favor_recall=True,
            )
            text = content or ""
            if len(text) < config.crawl_min_chars:
                text = _extract_visible_text_from_page(page, config.crawl_max_chars)
            return _clean_crawled_text(text, config.crawl_max_chars)
        finally:
            context.close()
            browser.close()


def _extract_visible_text_from_page(page, max_chars: int) -> str:
    selectors = [
        "article",
        "main",
        "[role='main']",
        ".article",
        ".article-content",
        ".content",
        ".post-content",
        ".entry-content",
        "body",
    ]
    for selector in selectors:
        try:
            text = page.locator(selector).first.inner_text(timeout=1200)
        except Exception:
            continue
        text = " ".join(text.split())
        if text:
            return text[:max_chars] if max_chars and len(text) > max_chars else text
    return ""


def _clean_crawled_text(text: str, max_chars: int = 0) -> str:
    """Remove navigation/link-heavy boilerplate from crawled page text."""

    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    raw_lines = []
    for chunk in text.split("\n"):
        chunk = re.sub(r"[ \t]+", " ", chunk).strip()
        if not chunk:
            continue
        raw_lines.extend(_split_suspect_link_blocks(chunk))

    kept: List[str] = []
    previous = ""
    for line in raw_lines:
        if _is_boilerplate_line(line):
            continue
        line = _strip_markdown_link_syntax(line)
        line = re.sub(r"[ \t]+", " ", line).strip(" -|·•\t")
        if not line or line == previous:
            continue
        previous = line
        if _is_boilerplate_line(line):
            continue
        kept.append(line)

    cleaned = "\n".join(kept)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if max_chars and len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip()
    return cleaned


def _split_suspect_link_blocks(line: str) -> List[str]:
    if len(line) < 500:
        return [line]
    marker_count = line.count("http") + line.count("](http") + line.count(" * [")
    if marker_count < 6:
        return [line]
    parts = re.split(r"\s+\*\s+|\s{2,}|(?<=\))\s+(?=\*)", line)
    return [part.strip() for part in parts if part.strip()]


def _strip_markdown_link_syntax(line: str) -> str:
    line = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", line)
    line = re.sub(r"\[([^\]]{1,80})\]\((https?://[^)]+)\)", r"\1", line)
    return line


def _is_boilerplate_line(line: str) -> bool:
    compact = re.sub(r"\s+", "", line).lower()
    if len(compact) <= 1:
        return True

    url_count = len(re.findall(r"https?://", line))
    markdown_link_count = len(re.findall(r"\[[^\]]+\]\(https?://", line))
    if url_count >= 2 or markdown_link_count >= 2:
        return True

    linkish_tokens = len(re.findall(r"https?://|www\.|\.com|\.cn|\.html|/zh/|/en/", line, flags=re.I))
    if linkish_tokens >= 4 and len(line) < 1200:
        return True
    if "/zh/" in line and "help.aliyun.com" in line and len(line) < 1500:
        return True

    nav_terms = [
        "首页",
        "文档",
        "产品",
        "解决方案",
        "定价",
        "支持",
        "帮助中心",
        "控制台",
        "登录",
        "注册",
        "备案",
        "联系我们",
        "新手指南",
        "从这里开始",
        "相关产品",
        "推荐产品",
        "更多产品",
        "上一页",
        "下一页",
        "目录",
        "云产品",
        "大数据计算",
        "数据库",
        "计算与分析",
        "文档停止维护",
    ]
    nav_hits = sum(1 for term in nav_terms if term in line or term in compact)
    bullet_count = line.count("* ") + line.count(" - ") + line.count("·")
    if nav_hits >= 3 and (bullet_count >= 1 or linkish_tokens >= 2 or len(line) < 1200):
        return True
    if nav_hits >= 5:
        return True

    product_catalog_terms = [
        "云原生",
        "数据库",
        "大数据",
        "计算服务",
        "迁移",
        "网关",
        "安全指南",
        "卓越架构",
        "采用框架",
        "maxcompute",
    ]
    catalog_hits = sum(1 for term in product_catalog_terms if term.lower() in compact)
    if catalog_hits >= 4:
        return True

    if line.startswith(("当前位置", "您当前的位置", "面包屑", "breadcrumb")):
        return True
    if re.fullmatch(r"[\W_]*(首页|文档|产品|控制台|登录|注册|帮助|目录)[\W_]*", compact):
        return True
    if len(line) <= 30 and nav_hits >= 1 and not re.search(r"[。；，,.]", line):
        return True

    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", line))
    if len(line) > 180 and cjk_chars < 12 and linkish_tokens >= 2:
        return True
    return False


def _fetch_with_crawl4ai(url: str, config: SearchConfig) -> str:
    async def run() -> str:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

        browser_config = BrowserConfig(
            browser_type="chromium",
            headless=True,
            ignore_https_errors=True,
            text_mode=True,
            light_mode=True,
            java_script_enabled=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
        )
        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            wait_until="domcontentloaded",
            page_timeout=max(1000, config.timeout * 1000),
            delay_before_return_html=0.5,
            scan_full_page=True,
            max_scroll_steps=2,
            remove_overlay_elements=True,
            remove_forms=True,
            exclude_all_images=True,
            locale="zh-CN",
            verbose=False,
        )
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config)

        markdown = getattr(result, "markdown", "") or ""
        if hasattr(markdown, "raw_markdown"):
            text = markdown.raw_markdown or markdown.fit_markdown or ""
        else:
            text = str(markdown)
        if not text:
            text = getattr(result, "cleaned_html", "") or getattr(result, "html", "") or ""
        return _clean_crawled_text(str(text), config.crawl_max_chars)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run())

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run())
    finally:
        loop.close()


def _crawl_or_snippet(result: SearchResult, config: SearchConfig) -> SearchResult:
    if config.crawl_max_chars <= 0:
        result.content = result.snippet
        result.content_source = "搜索摘要"
        return result

    if config.crawl_backend == 1:
        try:
            text = _fetch_with_playwright(result.url, config)
            source_name = "Playwright网页正文"
        except Exception as exc:
            print(f"[playwright] crawl failed: {result.url} ({exc})")
            text = ""
            source_name = "网页正文"
        if len(text) < config.crawl_min_chars and not _deadline_exceeded(config):
            try:
                print(f"[crawler] Playwright未获取到足够正文，改用传统爬虫: {result.url}")
                text = fetch_page_text(
                    result.url,
                    proxy=config.proxy,
                    timeout=_remaining_timeout(config),
                    max_chars=config.crawl_max_chars,
                    target_language=config.target_language,
                )
                text = _clean_crawled_text(text, config.crawl_max_chars)
                source_name = "网页正文"
            except Exception as exc:
                print(f"[crawler] fallback failed: {result.url} ({exc})")
    elif config.crawl_backend == 2:
        try:
            text = _fetch_with_crawl4ai(result.url, config)
            source_name = "Crawl4AI正文"
        except Exception as exc:
            print(f"[crawl4ai] crawl failed: {result.url} ({exc})")
            text = ""
            source_name = "网页正文"
        if len(text) < config.crawl_min_chars and not _deadline_exceeded(config):
            try:
                print(f"[crawler] Crawl4AI未获取到足够正文，改用传统爬虫: {result.url}")
                text = fetch_page_text(
                    result.url,
                    proxy=config.proxy,
                    timeout=_remaining_timeout(config),
                    max_chars=config.crawl_max_chars,
                    target_language=config.target_language,
                )
                text = _clean_crawled_text(text, config.crawl_max_chars)
                source_name = "网页正文"
            except Exception as exc:
                print(f"[crawler] fallback failed: {result.url} ({exc})")
    else:
        text = fetch_page_text(
            result.url,
            proxy=config.proxy,
            timeout=_remaining_timeout(config),
            max_chars=config.crawl_max_chars,
            target_language=config.target_language,
        )
        text = _clean_crawled_text(text, config.crawl_max_chars)
        source_name = "网页正文"

    if len(text) >= config.crawl_min_chars:
        result.content = text
        result.content_source = source_name
    else:
        result.content = result.snippet
        result.content_source = "搜索摘要"
    return result


def _query_started_at(config: SearchConfig) -> float:
    return float(getattr(config, "query_started_at", 0.0) or 0.0)


def _query_total_timeout(config: SearchConfig) -> int:
    return max(0, int(getattr(config, "total_timeout", 0) or 0))


def _deadline_exceeded(config: SearchConfig) -> bool:
    total_timeout = _query_total_timeout(config)
    started_at = _query_started_at(config)
    return bool(total_timeout and started_at and time.monotonic() - started_at >= total_timeout)


def _remaining_timeout(config: SearchConfig) -> int:
    base_timeout = max(1, int(getattr(config, "timeout", 15) or 15))
    total_timeout = _query_total_timeout(config)
    started_at = _query_started_at(config)
    if not total_timeout or not started_at:
        return base_timeout
    remaining = total_timeout - (time.monotonic() - started_at)
    return max(1, min(base_timeout, int(remaining)))


def _with_remaining_timeout(config: SearchConfig) -> SearchConfig:
    return replace(config, timeout=_remaining_timeout(config))


def _crawl_results_with_deadline(
    query: str,
    results: List[SearchResult],
    config: SearchConfig,
) -> List[SearchResult]:
    crawled: List[SearchResult] = []
    for item in results:
        if not item.url:
            continue
        if _deadline_exceeded(config):
            print(
                f"[search-timeout] query exceeded {_query_total_timeout(config)}s, "
                f"stop current search: {query}"
            )
            break
        crawled.append(_crawl_or_snippet(item, _with_remaining_timeout(config)))
    return crawled


def search_bocha(query: str, config: SearchConfig) -> List[SearchResult]:
    """Search with Bocha Web Search API."""
    if not config.bocha_api_key:
        raise ValueError("bocha_api_key is required for Bocha search")

    if not _query_started_at(config):
        config = replace(config, query_started_at=time.monotonic())

    response = requests.post(
        "https://api.bocha.cn/v1/web-search",
        headers={
            "Authorization": f"Bearer {config.bocha_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "query": query,
            "count": config.count,
            "summary": True,
            "freshness": "noLimit",
        },
        timeout=_remaining_timeout(config),
    )
    response.raise_for_status()

    data = response.json()
    items = data.get("data", {}).get("webPages", {}).get("value", [])
    results = []
    for item in items:
        snippet_parts = []
        site_name = item.get("siteName") or item.get("site_name")
        published = item.get("datePublished") or item.get("dateLastCrawled")
        if site_name:
            snippet_parts.append(f"siteName: {site_name}")
        if published:
            snippet_parts.append(f"date: {published}")
        summary = item.get("summary", "") or item.get("snippet", "")
        if summary:
            snippet_parts.append(summary)
        results.append(
            SearchResult(
                title=item.get("name", ""),
                url=item.get("url", ""),
                snippet="\n".join(snippet_parts),
                source=SearchSource.BOCHA.value,
            )
        )
    return _crawl_results_with_deadline(query, results, config)


def search_google(query: str, config: SearchConfig) -> List[SearchResult]:
    """Search with Google Custom Search JSON API."""
    if not config.google_api_key or not config.google_cx_id:
        raise ValueError("google_api_key and google_cx_id are required for Google search")

    if not _query_started_at(config):
        config = replace(config, query_started_at=time.monotonic())

    response = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={
            "q": query,
            "key": config.google_api_key,
            "cx": config.google_cx_id,
            "num": config.count,
        },
        timeout=_remaining_timeout(config),
    )
    response.raise_for_status()

    results = [
        SearchResult(
            title=item.get("title", ""),
            url=item.get("link", ""),
            snippet=item.get("snippet", ""),
            source=SearchSource.GOOGLE.value,
        )
        for item in response.json().get("items", [])
    ]
    return _crawl_results_with_deadline(query, results, config)


def search_duckduckgo(query: str, config: SearchConfig) -> List[SearchResult]:
    """Search with DuckDuckGo and filter blacklisted domains."""
    if not _query_started_at(config):
        config = replace(config, query_started_at=time.monotonic())

    with DDGS(proxy=config.proxy, timeout=_remaining_timeout(config)) as ddgs:
        raw_results = list(
            ddgs.text(
                keywords=query,
                region="wt-wt",
                max_results=config.max_search_results,
                backend="html",
            )
        )

    results: List[SearchResult] = []
    for item in raw_results:
        url = item.get("href", "")
        if not url or _is_blacklisted(url, config.blacklist):
            continue

        results.append(
            SearchResult(
                title=item.get("title", ""),
                url=url,
                snippet=item.get("body", ""),
                source=SearchSource.DUCKDUCKGO.value,
            )
        )
        if len(results) >= config.count:
            break

    return _crawl_results_with_deadline(query, results, config)


def search(query: str, config: SearchConfig) -> List[SearchResult]:
    """Dispatch a query to the configured search provider."""
    if config.source == SearchSource.BOCHA:
        return search_bocha(query, config)
    if config.source == SearchSource.GOOGLE:
        return search_google(query, config)
    if config.source == SearchSource.DUCKDUCKGO:
        return search_duckduckgo(query, config)
    raise ValueError(f"Unsupported search source: {config.source}")


def format_results(query: str, results: List[SearchResult]) -> str:
    """Format search results for feeding back into an LLM."""
    if not results:
        return f"No search results found for: {query}"

    sections = [f"Search results for '{query}':"]
    for index, item in enumerate(results, 1):
        content = item.content or item.snippet
        sections.append(
            "\n".join(
                [
                    f"--- Source {index}: {item.title} ---",
                    f"URL: {item.url}",
                    f"Content: {content}",
                ]
            )
        )
    return "\n\n".join(sections)


def unified_search(query: str, config: SearchConfig) -> str:
    """Search and return a ready-to-use text report for the LLM loop."""
    return format_results(query, search(query, config))

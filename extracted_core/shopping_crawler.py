"""Dedicated shopping-site crawlers for JD, Taobao, and Tmall."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional
from urllib.parse import quote_plus, urlparse

import requests

from .crawler import DEFAULT_HEADERS, fetch_page_text


JD_PLATFORM = "JD"
TAOBAO_PLATFORM = "Taobao/Tmall"

JD_DOMAINS = ("jd.com", "item.jd.com", "jd.hk", "item.jd.hk")
TAOBAO_DOMAINS = ("taobao.com", "item.taobao.com", "tmall.com", "detail.tmall.com")


@dataclass
class ShoppingSearchHit:
    platform: str
    title: str
    url: str
    snippet: str = ""
    page_text: str = ""


def _domain_matches(url: str, domains: Iterable[str]) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _is_product_url(url: str, platform: str) -> bool:
    if platform == JD_PLATFORM:
        return _domain_matches(url, JD_DOMAINS) and (
            "item.jd.com" in url or re.search(r"jd\.com/\d+\.html", url)
        )
    if platform == TAOBAO_PLATFORM:
        return _domain_matches(url, TAOBAO_DOMAINS) and (
            "item.taobao.com" in url or "detail.tmall.com" in url
        )
    return False


def _normalize_url(url: str) -> str:
    url = url.replace("\\/", "/").replace("&amp;", "&")
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


def _fetch_html(url: str, proxy: Optional[str], timeout: int) -> str:
    proxies = {"http": proxy, "https": proxy} if proxy else None
    headers = dict(DEFAULT_HEADERS)
    headers.update(
        {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.baidu.com/",
        }
    )
    try:
        response = requests.get(
            url,
            headers=headers,
            proxies=proxies,
            timeout=timeout,
            verify=not bool(proxy),
        )
        if response.status_code != 200:
            return ""
        response.encoding = response.apparent_encoding
        return response.text
    except Exception:
        return ""


def _extract_title_near_url(html: str, url: str) -> str:
    if not html:
        return ""
    index = html.find(url)
    if index < 0:
        parsed = urlparse(url)
        tail = parsed.path.split("/")[-1]
        index = html.find(tail) if tail else -1
    if index < 0:
        return ""
    window = html[max(0, index - 800) : index + 800]
    title_patterns = [
        r'title=["\']([^"\']{2,160})["\']',
        r'alt=["\']([^"\']{2,160})["\']',
        r'"raw_title"\s*:\s*"([^"]{2,160})"',
        r'"title"\s*:\s*"([^"]{2,160})"',
    ]
    for pattern in title_patterns:
        match = re.search(pattern, window, flags=re.IGNORECASE)
        if match:
            return " ".join(match.group(1).split())
    return ""


def _extract_product_urls(html: str, platform: str) -> List[str]:
    urls = set()
    patterns = []
    if platform == JD_PLATFORM:
        patterns = [
            r"https?://item\.jd\.com/\d+\.html",
            r"//item\.jd\.com/\d+\.html",
            r"https?://item\.jd\.hk/\d+\.html",
            r"//item\.jd\.hk/\d+\.html",
        ]
    elif platform == TAOBAO_PLATFORM:
        patterns = [
            r"https?://item\.taobao\.com/item\.htm\?[^\"'<>\\\s]+",
            r"//item\.taobao\.com/item\.htm\?[^\"'<>\\\s]+",
            r"https?://detail\.tmall\.com/item\.htm\?[^\"'<>\\\s]+",
            r"//detail\.tmall\.com/item\.htm\?[^\"'<>\\\s]+",
        ]

    for pattern in patterns:
        for match in re.finditer(pattern, html):
            url = _normalize_url(match.group(0))
            if _is_product_url(url, platform):
                urls.add(url)
    return list(urls)


def search_jd_products(
    product_name: str,
    *,
    proxy: Optional[str] = None,
    timeout: int = 15,
    max_items: int = 3,
) -> List[ShoppingSearchHit]:
    search_urls = [
        f"https://search.jd.com/Search?keyword={quote_plus(product_name)}&enc=utf-8",
        f"https://search.jd.com/Search?keyword={quote_plus(product_name + ' \u4eac\u4e1c\u81ea\u8425')}&enc=utf-8",
    ]
    return _search_shopping_pages(
        platform=JD_PLATFORM,
        product_name=product_name,
        search_urls=search_urls,
        proxy=proxy,
        timeout=timeout,
        max_items=max_items,
    )


def search_taobao_tmall_products(
    product_name: str,
    *,
    proxy: Optional[str] = None,
    timeout: int = 15,
    max_items: int = 3,
) -> List[ShoppingSearchHit]:
    search_urls = [
        f"https://s.taobao.com/search?q={quote_plus(product_name)}",
        f"https://list.tmall.com/search_product.htm?q={quote_plus(product_name)}",
    ]
    return _search_shopping_pages(
        platform=TAOBAO_PLATFORM,
        product_name=product_name,
        search_urls=search_urls,
        proxy=proxy,
        timeout=timeout,
        max_items=max_items,
    )


def _search_shopping_pages(
    *,
    platform: str,
    product_name: str,
    search_urls: List[str],
    proxy: Optional[str],
    timeout: int,
    max_items: int,
) -> List[ShoppingSearchHit]:
    hits: List[ShoppingSearchHit] = []
    seen_urls = set()

    for search_url in search_urls:
        if len(hits) >= max_items:
            break
        html = _fetch_html(search_url, proxy, timeout)
        for url in _extract_product_urls(html, platform):
            if len(hits) >= max_items:
                break
            if url in seen_urls:
                continue
            seen_urls.add(url)
            title = _extract_title_near_url(html, url) or product_name
            page_text = fetch_page_text(
                url,
                proxy=proxy,
                timeout=timeout,
                max_chars=8000,
                target_language="zh",
            )
            hits.append(
                ShoppingSearchHit(
                    platform=platform,
                    title=title,
                    url=url,
                    snippet=f"Found from shopping search page: {search_url}",
                    page_text=page_text,
                )
            )
    return hits


def search_shopping_products(
    product_name: str,
    *,
    proxy: Optional[str] = None,
    timeout: int = 15,
    max_items_per_platform: int = 3,
) -> List[ShoppingSearchHit]:
    hits = []
    hits.extend(
        search_jd_products(
            product_name,
            proxy=proxy,
            timeout=timeout,
            max_items=max_items_per_platform,
        )
    )
    hits.extend(
        search_taobao_tmall_products(
            product_name,
            proxy=proxy,
            timeout=timeout,
            max_items=max_items_per_platform,
        )
    )
    return hits

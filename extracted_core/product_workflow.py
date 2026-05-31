"""Product parameter workflow for JD/Taobao/Tmall plus an LLM summary."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

import requests

from .crawler import DEFAULT_HEADERS, fetch_page_text
from .llm_client import chat_content
from .search import SearchConfig, search


JD_PLATFORM = "JD"
TAOBAO_PLATFORM = "Taobao/Tmall"
UNKNOWN_PLATFORM = "Unknown"

JD_DOMAINS = ("jd.com", "item.jd.com", "jd.hk", "item.jd.hk")
TAOBAO_DOMAINS = ("taobao.com", "item.taobao.com", "tmall.com", "detail.tmall.com")

PARAM_ALIASES = {
    "brand": ["brand", "\u54c1\u724c"],
    "model": ["model", "\u578b\u53f7"],
    "product_name": ["name", "\u5546\u54c1\u540d\u79f0", "\u4ea7\u54c1\u540d\u79f0"],
    "sku": ["sku", "\u5546\u54c1\u7f16\u53f7", "\u8d27\u53f7"],
    "shop": ["seller", "shop", "\u5e97\u94fa", "\u5356\u5bb6"],
    "price": ["price", "\u4ef7\u683c", "\u552e\u4ef7", "\u5230\u624b\u4ef7"],
    "color": ["color", "\u989c\u8272", "\u989c\u8272\u5206\u7c7b"],
    "version": ["version", "\u7248\u672c", "\u7248\u672c\u7c7b\u578b"],
    "capacity": ["capacity", "\u5bb9\u91cf", "\u5b58\u50a8\u5bb9\u91cf", "\u5185\u5b58"],
    "spec": ["spec", "specification", "\u89c4\u683c", "\u914d\u7f6e"],
}


@dataclass
class ProductWorkflowConfig:
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    search_config: SearchConfig
    max_items_per_platform: int = 3
    max_review_items: int = 6
    crawl_timeout: int = 15
    crawl_max_chars: int = 8000
    temperature: float = 0.2
    max_tokens: int = 3000
    verbose: bool = True
    use_llm_query_rewrite: bool = True
    progress_printer: Optional[Callable[[str], None]] = print


@dataclass
class ProductCandidate:
    platform: str
    title: str
    url: str
    snippet: str = ""
    page_text: str = ""
    extracted_params: Dict[str, str] = field(default_factory=dict)
    blocked_or_empty: bool = False


@dataclass
class ReviewEvidence:
    source_type: str
    title: str
    url: str
    snippet: str = ""
    page_text: str = ""
    blocked_or_empty: bool = False


@dataclass
class ProductWorkflowResult:
    product_name: str
    candidates: List[ProductCandidate]
    reviews: List[ReviewEvidence]
    summary: str
    raw_prompt: str


def _log(config: ProductWorkflowConfig, message: str) -> None:
    if config.verbose and config.progress_printer:
        config.progress_printer(message)


def _domain_matches(url: str, domains: tuple[str, ...]) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _platform_from_url(url: str) -> str:
    if _domain_matches(url, JD_DOMAINS):
        return JD_PLATFORM
    if _domain_matches(url, TAOBAO_DOMAINS):
        return TAOBAO_PLATFORM
    return UNKNOWN_PLATFORM


def _is_product_platform_url(url: str, platform: str) -> bool:
    if platform == JD_PLATFORM:
        return _domain_matches(url, JD_DOMAINS)
    if platform == TAOBAO_PLATFORM:
        return _domain_matches(url, TAOBAO_DOMAINS)
    return False


def _parse_json_object(content: str) -> Dict[str, object]:
    cleaned = content.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned)


def _normalize_query_list(value: object, max_items: int) -> List[str]:
    if not isinstance(value, list):
        return []
    queries = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            continue
        query = " ".join(item.split())
        if not query or query in seen:
            continue
        seen.add(query)
        queries.append(query)
        if len(queries) >= max_items:
            break
    return queries


def _fallback_query_plan(product_name: str) -> Dict[str, List[str]]:
    return {
        "jd_queries": [
            f"{product_name} item.jd.com",
            f"{product_name} \u4eac\u4e1c \u53c2\u6570 \u89c4\u683c",
        ],
        "taobao_tmall_queries": [
            f"{product_name} detail.tmall.com item.taobao.com",
            f"{product_name} \u5929\u732b \u6dd8\u5b9d \u53c2\u6570 \u89c4\u683c",
        ],
        "review_queries": [
            f"{product_name} \u8bc4\u6d4b",
            f"{product_name} \u4f53\u9a8c \u4f18\u70b9 \u7f3a\u70b9",
            f"{product_name} \u503c\u4e0d\u503c\u5f97\u4e70 \u907f\u5751",
            f"{product_name} \u4ec0\u4e48\u503c\u5f97\u4e70 \u77e5\u4e4e \u8bc4\u6d4b",
        ],
    }


def plan_search_queries(product_name: str, config: ProductWorkflowConfig) -> Dict[str, List[str]]:
    """Ask the LLM to rewrite Bocha search queries for product and review search."""
    fallback = _fallback_query_plan(product_name)
    if not config.use_llm_query_rewrite:
        _log(config, "[query-plan] LLM query rewrite disabled, using fallback queries")
        return fallback

    _log(config, f"[query-plan] Asking LLM to rewrite search queries for: {product_name}")
    prompt = f"""
You are planning search queries for Bocha Web Search.
The user product name is: {product_name}

Generate concise search queries that work well in a Chinese web-search API.
Avoid overusing advanced operators. Use natural-language queries first, and use
site/domain hints only when helpful.
Ecommerce pages, forums, reviews, blogs, and communities are all evidence
sources. Ecommerce is not the main source; it is only one source for parameters,
price, SKU, and seller information.
Product parameters do not have to come only from official or ecommerce pages.
Review articles, hands-on evaluations, teardown posts, benchmark posts, forums,
blogs, and community discussions can also be parameter references. Generate
queries that intentionally look for these third-party sources.
If the input is closer to an internet product, AI/Vibe tool, SaaS, or service
than a physical ecommerce item, still generate useful third-party queries for
docs, pricing, changelog, reviews, tutorials, GitHub/issues, comparisons,
limitations, workflows, and user feedback.

Return strict JSON only:
{{
  "jd_queries": [
    "queries likely to find JD product pages or JD product parameter pages"
  ],
  "taobao_tmall_queries": [
    "queries likely to find Taobao/Tmall product pages or official flagship pages"
  ],
  "review_queries": [
    "queries likely to find reviews, hands-on tests, teardown posts, blogs, community posts, pros/cons, buying advice, parameter details"
  ]
}}

Constraints:
- 2 jd_queries.
- 2 taobao_tmall_queries.
- 4 review_queries.
- Include the original product name in every query.
- Prefer Chinese queries for Chinese ecommerce products.
- At least 2 review_queries should explicitly target 测评, 实测, 拆解, 参数,
  规格, 体验, 缺点, or 用户反馈.
- Do not include explanations.
""".strip()

    try:
        content = chat_content(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": "You create high-recall web-search queries and return strict JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1200,
        )
        data = _parse_json_object(content or "{}")
        plan = {
            "jd_queries": _normalize_query_list(data.get("jd_queries"), 2),
            "taobao_tmall_queries": _normalize_query_list(data.get("taobao_tmall_queries"), 2),
            "review_queries": _normalize_query_list(data.get("review_queries"), 4),
        }
        for key, fallback_queries in fallback.items():
            if not plan[key]:
                plan[key] = fallback_queries
        _log(config, "[query-plan] LLM query rewrite succeeded")
        for key, queries in plan.items():
            _log(config, f"[query-plan] {key}: {queries}")
        return plan
    except Exception as exc:
        _log(config, f"[query-plan] LLM query rewrite failed, using fallback queries: {exc}")
        return fallback


def _extract_ld_json_params(html: str) -> Dict[str, str]:
    params: Dict[str, str] = {}
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        raw = match.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            for key in ("name", "brand", "model", "sku", "description"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    params[key] = value.strip()
            offers = data.get("offers")
            if isinstance(offers, dict):
                price = offers.get("price")
                if price:
                    params["price"] = str(price)
    return params


def _strip_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(value.split())


def _extract_meta_params(html: str) -> Dict[str, str]:
    params: Dict[str, str] = {}
    if not html:
        return params

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if title_match:
        params["html_title"] = _strip_html(title_match.group(1))[:200]

    for match in re.finditer(r"<meta\s+([^>]+)>", html, flags=re.IGNORECASE | re.DOTALL):
        attrs = match.group(1)
        name_match = re.search(
            r'(?:name|property)=["\']([^"\']+)["\']',
            attrs,
            flags=re.IGNORECASE,
        )
        content_match = re.search(
            r'content=["\']([^"\']+)["\']',
            attrs,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not name_match or not content_match:
            continue

        name = name_match.group(1).lower()
        content = _strip_html(content_match.group(1))[:500]
        if not content:
            continue
        if name in ("keywords", "description", "og:title", "og:description"):
            params[f"meta_{name.replace(':', '_')}"] = content

    return params


def _extract_script_text_params(html: str) -> Dict[str, str]:
    params: Dict[str, str] = {}
    if not html:
        return params

    compact_html = " ".join(html.split())
    patterns = {
        "sku": r'(?:skuId|skuid|wareId|itemId|item_id)["\']?\s*[:=]\s*["\']?([A-Za-z0-9_-]{4,80})',
        "price": r'(?:price|pPrice|jdPrice|salePrice)["\']?\s*[:=]\s*["\']?([0-9]+(?:\.[0-9]+)?)',
        "brand": r'(?:brand|brandName)["\']?\s*[:=]\s*["\']([^"\']{1,80})["\']',
        "shop": r'(?:shopName|sellerName|venderName)["\']?\s*[:=]\s*["\']([^"\']{1,120})["\']',
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, compact_html, flags=re.IGNORECASE)
        if match:
            params[key] = _strip_html(match.group(1))

    return params


def _extract_inline_params(text: str) -> Dict[str, str]:
    """Best-effort parameter extraction from visible text or search snippets."""
    params: Dict[str, str] = {}
    if not text:
        return params

    compact_text = " ".join(text.split())
    for canonical_key, aliases in PARAM_ALIASES.items():
        alias_group = "|".join(re.escape(alias) for alias in aliases)
        pattern = rf"(?:{alias_group})\s*[:\uFF1A]\s*([^\s|,\uFF0C;\uFF1B]{{1,100}})"
        match = re.search(pattern, compact_text, flags=re.IGNORECASE)
        if match:
            params[canonical_key] = match.group(1).strip()

    price_match = re.search(
        r"(?:[\u00A5\uFFE5]\s*|RMB\s*)([0-9]+(?:\.[0-9]+)?)",
        compact_text,
        flags=re.IGNORECASE,
    )
    if price_match and "price" not in params:
        params["price"] = price_match.group(1)

    return params


def _fetch_raw_html(url: str, proxy: Optional[str], timeout: int) -> str:
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        response = requests.get(
            url,
            headers=DEFAULT_HEADERS,
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


def _enrich_candidate(candidate: ProductCandidate, config: ProductWorkflowConfig) -> ProductCandidate:
    _log(config, f"[crawl] Fetching page: {candidate.platform} | {candidate.title}")
    _log(config, f"[crawl] URL: {candidate.url}")

    html = _fetch_raw_html(
        candidate.url,
        proxy=config.search_config.proxy,
        timeout=config.crawl_timeout,
    )
    text = candidate.page_text or fetch_page_text(
        candidate.url,
        proxy=config.search_config.proxy,
        timeout=config.crawl_timeout,
        max_chars=config.crawl_max_chars,
        target_language=config.search_config.target_language,
    )

    candidate.page_text = text
    candidate.extracted_params.update(_extract_ld_json_params(html))
    candidate.extracted_params.update(_extract_meta_params(html))
    candidate.extracted_params.update(_extract_script_text_params(html))
    candidate.extracted_params.update(_extract_inline_params(text or candidate.snippet))
    candidate.blocked_or_empty = not text and not candidate.extracted_params

    text_status = "ok" if candidate.page_text else "empty"
    param_keys = ", ".join(sorted(candidate.extracted_params.keys())) or "none"
    _log(config, f"[extract] Page text: {text_status}; extracted params: {param_keys}")
    return candidate


def _enrich_review(review: ReviewEvidence, config: ProductWorkflowConfig) -> ReviewEvidence:
    _log(config, f"[review-crawl] Fetching review evidence: {review.source_type} | {review.title}")
    _log(config, f"[review-crawl] URL: {review.url}")
    text = review.page_text or fetch_page_text(
        review.url,
        proxy=config.search_config.proxy,
        timeout=config.crawl_timeout,
        max_chars=config.crawl_max_chars,
        target_language=config.search_config.target_language,
    )
    review.page_text = text
    review.blocked_or_empty = not text
    text_status = "ok" if text else "empty, using snippet only"
    _log(config, f"[review-extract] Page text: {text_status}")
    return review


def collect_product_candidates(
    product_name: str,
    config: ProductWorkflowConfig,
    query_plan: Optional[Dict[str, List[str]]] = None,
) -> List[ProductCandidate]:
    """Find JD/Taobao/Tmall ecommerce evidence through Bocha search."""
    _log(config, f"[ecommerce-start] Collecting ecommerce evidence for: {product_name}")
    _log(config, "[ecommerce-search] Using Bocha web-search for ecommerce pages")

    plan = query_plan or _fallback_query_plan(product_name)
    queries = [(JD_PLATFORM, query) for query in plan["jd_queries"]]
    queries.extend((TAOBAO_PLATFORM, query) for query in plan["taobao_tmall_queries"])

    original_count = config.search_config.count
    original_max_results = config.search_config.max_search_results
    candidates: List[ProductCandidate] = []
    platform_counts = {JD_PLATFORM: 0, TAOBAO_PLATFORM: 0}
    seen_urls = set()

    try:
        config.search_config.count = max(original_count, config.max_items_per_platform * 5, 10)
        config.search_config.max_search_results = max(original_max_results, 20)

        for preferred_platform, query in queries:
            if platform_counts[preferred_platform] >= config.max_items_per_platform:
                continue

            _log(config, f"[ecommerce-search] Bocha query for {preferred_platform}: {query}")
            results = search(query, config.search_config)
            _log(config, f"[ecommerce-search] Raw results: {len(results)}")

            for result in results:
                if platform_counts[preferred_platform] >= config.max_items_per_platform:
                    break
                if not result.url or result.url in seen_urls:
                    continue

                actual_platform = _platform_from_url(result.url)
                if actual_platform == UNKNOWN_PLATFORM:
                    _log(config, f"[ecommerce-skip] Not a shopping domain: {result.url}")
                    continue
                if actual_platform != preferred_platform:
                    _log(
                        config,
                        f"[ecommerce-skip] Expected {preferred_platform} but got "
                        f"{actual_platform}: {result.url}",
                    )
                    continue
                if not _is_product_platform_url(result.url, actual_platform):
                    _log(config, f"[ecommerce-skip] Not a supported product URL: {result.url}")
                    continue

                seen_urls.add(result.url)
                platform_counts[actual_platform] = platform_counts.get(actual_platform, 0) + 1
                _log(config, f"[ecommerce-evidence] {actual_platform}: {result.title}")
                _log(config, f"[ecommerce-evidence] {result.url}")
                candidates.append(
                    ProductCandidate(
                        platform=actual_platform,
                        title=result.title,
                        url=result.url,
                        snippet=result.snippet or result.content,
                        page_text=result.content,
                    )
                )
    finally:
        config.search_config.count = original_count
        config.search_config.max_search_results = original_max_results

    _log(config, f"[ecommerce-search] Total ecommerce evidence kept: {len(candidates)}")
    _log(
        config,
        "[ecommerce-search] Evidence counts by platform: "
        f"JD={platform_counts.get(JD_PLATFORM, 0)}, "
        f"Taobao/Tmall={platform_counts.get(TAOBAO_PLATFORM, 0)}",
    )
    enriched = [_enrich_candidate(candidate, config) for candidate in candidates]
    _log(config, "[ecommerce-collect] Ecommerce evidence collection finished")
    return enriched


def collect_review_evidence(
    product_name: str,
    config: ProductWorkflowConfig,
    query_plan: Optional[Dict[str, List[str]]] = None,
) -> List[ReviewEvidence]:
    """Search review/blog/community evidence through Bocha."""
    _log(config, f"[review-start] Collecting review evidence for: {product_name}")

    plan = query_plan or _fallback_query_plan(product_name)
    queries = [(f"review_{index + 1}", query) for index, query in enumerate(plan["review_queries"])]

    original_count = config.search_config.count
    original_max_results = config.search_config.max_search_results
    reviews: List[ReviewEvidence] = []

    try:
        per_query_count = max(2, min(config.max_review_items, original_count))
        config.search_config.count = per_query_count
        config.search_config.max_search_results = max(10, original_max_results)
        seen_urls = set()

        for source_type, query in queries:
            if len(reviews) >= config.max_review_items:
                break
            _log(config, f"[review-search] Bocha query for {source_type}: {query}")
            results = search(query, config.search_config)
            _log(config, f"[review-search] Raw results: {len(results)}")

            for result in results:
                if len(reviews) >= config.max_review_items:
                    break
                if not result.url or result.url in seen_urls:
                    continue
                seen_urls.add(result.url)
                review = ReviewEvidence(
                    source_type=source_type,
                    title=result.title,
                    url=result.url,
                    snippet=result.snippet or result.content,
                    page_text=result.content,
                )
                _log(config, f"[review] {source_type}: {result.title}")
                _log(config, f"[review] {result.url}")
                reviews.append(review)
    finally:
        config.search_config.count = original_count
        config.search_config.max_search_results = original_max_results

    _log(config, f"[review-search] Total review evidence kept: {len(reviews)}")
    enriched = [_enrich_review(review, config) for review in reviews]
    _log(config, "[review-collect] Review evidence collection finished")
    return enriched


def build_product_summary_prompt(
    product_name: str,
    candidates: List[ProductCandidate],
    reviews: Optional[List[ReviewEvidence]] = None,
) -> str:
    product_payload = []
    for item in candidates:
        product_payload.append(
            {
                "platform": item.platform,
                "title": item.title,
                "url": item.url,
                "snippet": item.snippet[:1000],
                "extracted_params": item.extracted_params,
                "page_text": item.page_text[:2500],
                "blocked_or_empty": item.blocked_or_empty,
            }
        )
    review_payload = []
    for item in reviews or []:
        review_payload.append(
            {
                "source_type": item.source_type,
                "title": item.title,
                "url": item.url,
                "snippet": item.snippet[:1000],
                "page_text": item.page_text[:2500],
                "blocked_or_empty": item.blocked_or_empty,
            }
        )

    return f"""
You are a product evidence synthesis assistant. The user product name is:
{product_name}

The JSON below contains two evidence groups:
1. Ecommerce evidence from JD, Taobao, and Tmall.
2. Forum/review/blog/community evidence from multiple internet searches.

Treat these evidence groups as peer sources. Ecommerce pages are useful for
parameters, price, SKU, and seller information, but they are not automatically
more important than reviews, forums, blogs, or community posts.
Do not require parameters to come from official pages. Parameters from credible
review articles, hands-on evaluations, teardown posts, benchmark posts, blogs,
forums, and community discussions are acceptable references when the source is
clearly cited. Mark them as non-official if relevant.
If the topic is not a physical ecommerce product, adapt the summary to the
available evidence: capabilities, pricing, plans, limits, integrations, docs,
workflow fit, reliability, privacy, support, ecosystem, and user feedback may be
more important than SKU-style fields.

Some pages may be empty because of login walls, JavaScript rendering, or
anti-crawling. If a field is missing, say it is not available. Do not invent
missing values.

Please answer in Chinese and include:
1. A balanced evidence summary across ecommerce, reviews, forums, blogs, and
   communities.
2. Key parameters found anywhere: brand, model, capacity/spec, color or version,
   price, shop, SKU, and other available specs. Mark the source for each key
   parameter when possible, including whether it came from ecommerce, review,
   teardown, forum/community, blog, or other evidence.
3. Cross-source consensus: main advantages, disadvantages, common complaints,
   and use-case fit.
4. Conflicts or uncertainty between sources, including whether ecommerce pages
   and third-party sources appear to discuss the same model/SKU.
5. Short pre-purchase verification advice.
6. URLs for every cited evidence item.

Ecommerce evidence JSON:
{json.dumps(product_payload, ensure_ascii=False, indent=2)}

Forum/review/blog/community evidence JSON:
{json.dumps(review_payload, ensure_ascii=False, indent=2)}
""".strip()


def summarize_product_candidates(
    product_name: str,
    candidates: List[ProductCandidate],
    reviews: List[ReviewEvidence],
    config: ProductWorkflowConfig,
) -> str:
    prompt = build_product_summary_prompt(product_name, candidates, reviews)
    if not candidates and not reviews:
        _log(config, "[llm] Skip LLM summary because no evidence was found")
        return (
            "\u672a\u627e\u5230\u4eac\u4e1c\u6216\u6dd8\u5b9d/\u5929\u732b"
            "\u5019\u9009\u5546\u54c1\uff0c\u4e5f\u672a\u627e\u5230\u6d4b\u8bc4"
            "\u8bc1\u636e\u3002\u5efa\u8bae\u6362\u4e00\u4e2a\u66f4\u5b8c\u6574"
            "\u7684\u5546\u54c1\u540d\u79f0\uff0c\u6216"
            "\u68c0\u67e5\u641c\u7d22\u4ee3\u7406/API \u914d\u7f6e\u3002"
        )

    _log(
        config,
        f"[llm] Sending {len(candidates)} ecommerce evidence items and "
        f"{len(reviews)} forum/review/blog/community evidence items to model: {config.llm_model}",
    )
    summary = chat_content(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You summarize product evidence in Chinese. Treat ecommerce, "
                    "reviews, forums, blogs, and communities as peer evidence sources. "
                    "Use only the provided crawled material and never fabricate missing specs."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    _log(config, "[llm] Summary generated")
    return summary


def run_product_workflow(
    product_name: str,
    config: ProductWorkflowConfig,
) -> ProductWorkflowResult:
    """Run search, crawl, parameter extraction, and LLM summarization."""
    _log(config, "[workflow] Start")
    query_plan = plan_search_queries(product_name, config)
    candidates = collect_product_candidates(product_name, config, query_plan)
    reviews = collect_review_evidence(product_name, config, query_plan)
    _log(config, "[workflow] Building LLM prompt")
    prompt = build_product_summary_prompt(product_name, candidates, reviews)
    summary = summarize_product_candidates(product_name, candidates, reviews, config)
    _log(config, "[workflow] Done")
    return ProductWorkflowResult(
        product_name=product_name,
        candidates=candidates,
        reviews=reviews,
        summary=summary,
        raw_prompt=prompt,
    )

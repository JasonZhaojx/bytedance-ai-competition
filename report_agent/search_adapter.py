"""上游搜索工作流到 report_agent 的唯一适配层。

这个文件的职责边界非常明确：
1. report_agent 不负责重新设计搜索策略，也不在这里硬编码搜索 query。
2. 真正的搜索/相似产品发现仍然调用上游已有工作流。
3. 本文件只把上游原始输出改写成 `core.py` 里 `run_writing_agent`
   已经能消费的 source 列表格式。

这样上游以后继续改搜索实现时，中游只需要维护“输出格式适配”，不需要跟着
重写搜索策略，也不需要修改上游源码。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Sequence

try:
    from .llm_utils import clean_text, parse_json_payload
except ImportError:
    from report_agent.llm_utils import clean_text, parse_json_payload


@dataclass
class ReportSearchConfig:
    """调用上游工作流和 adapter LLM 所需的运行时配置。

    这里保留搜索相关字段，是为了把环境变量透传给上游
    `run_positioning_product_search()`。这些字段不是 report_agent 自己的
    搜索调参入口；report_agent 不在本文件里自己构造 query 或循环搜索。

    `llm_*` 和 `adapter_*` 字段只服务于“上游输出 -> report_agent source”
    这一步改写。
    """

    # 上游搜索配置：默认值保持和根目录 run_similar_product_reports.py 对齐。
    source: str = "bocha"
    bocha_api_key: str = ""
    google_api_key: str = ""
    google_cx_id: str = ""
    proxy: Optional[str] = None
    query_count: int = 3
    results_per_query: int = 3
    max_search_results: int = 3
    crawl_max_chars: int = 2500
    crawl_min_chars: int = 120
    crawl_backend: int = 0
    timeout: int = 20

    # Adapter LLM 配置：用于把上游的原始输出改写成 report_agent 的输入格式。
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    adapter_use_llm: bool = True
    adapter_temperature: float = 0.1
    adapter_max_tokens: int = 4000
    adapter_timeout: int = 240
    adapter_max_input_chars: int = 30000
    verbose: bool = True
    progress_printer: Optional[Callable[[str], None]] = print

    @classmethod
    def from_env(cls) -> "ReportSearchConfig":
        """从环境变量构造配置。

        注意：搜索数量、搜索源、API key 等配置只用于调用上游，不在
        report_agent 中重新解释。adapter LLM 默认复用根脚本当前 provider，
        也允许用 REPORT_ADAPTER_LLM_* 单独覆盖。
        """

        search_count = int(os.getenv("SEARCH_COUNT", "3"))
        api_key, base_url, model = provider_llm_config_from_env()
        return cls(
            source=os.getenv("SEARCH_SOURCE", "bocha"),
            bocha_api_key=os.getenv("BOCHA_API_KEY", ""),
            google_api_key=os.getenv("GOOGLE_API_KEY", ""),
            google_cx_id=os.getenv("GOOGLE_CX_ID", ""),
            proxy=os.getenv("HTTP_PROXY") or None,
            query_count=int(os.getenv("QUERY_COUNT", "3")),
            results_per_query=search_count,
            max_search_results=search_count,
            crawl_max_chars=int(os.getenv("CRAWL_MAX_CHARS", "2500")),
            crawl_min_chars=int(os.getenv("CRAWL_MIN_CHARS", "120")),
            crawl_backend=int(os.getenv("SEARCH_BACKEND", "0")),
            timeout=int(os.getenv("SEARCH_TIMEOUT", "20")),
            llm_api_key=os.getenv("REPORT_ADAPTER_LLM_API_KEY") or api_key,
            llm_base_url=os.getenv("REPORT_ADAPTER_LLM_BASE_URL") or base_url,
            llm_model=os.getenv("REPORT_ADAPTER_LLM_MODEL") or model,
            adapter_use_llm=_env_bool("REPORT_ADAPTER_USE_LLM", True),
            adapter_max_tokens=int(os.getenv("REPORT_ADAPTER_MAX_TOKENS", "4000")),
            adapter_timeout=int(os.getenv("REPORT_ADAPTER_TIMEOUT", "240")),
            adapter_max_input_chars=int(
                os.getenv("REPORT_ADAPTER_MAX_INPUT_CHARS", "30000")
            ),
        )


@dataclass
class SearchBundle:
    """传给 report_agent 的适配结果。

    `results` 是最关键字段：它是 `core.py` 的 `run_writing_agent()` 直接消费
    的 source 列表。`queries`、`product_names` 和 `errors` 用于记录上游和
    adapter 的过程信息，方便调试和落盘追踪。
    """

    queries: List[str]
    results: List[Any]
    errors: List[str] = field(default_factory=list)
    product_names: List[str] = field(default_factory=list)


@dataclass
class _CollectedUpstreamOutput:
    """内部归一化结果。

    上游输出可能是 dataclass、dict、文件路径、字符串或列表。先统一收集成
    这三个字段，再交给 LLM adapter 或 fallback 处理。
    """

    queries: List[str]
    product_names: List[str]
    items: List[Any]


def search_for_report(
    product_description: str,
    *,
    competitors: Optional[Sequence[str]] = None,
    config: Optional[ReportSearchConfig] = None,
) -> SearchBundle:
    """调用上游相似产品搜索，并把原始输出适配成 report_agent 输入。

    这是给旧调用方保留的入口。和之前不同的是：
    - 不再调用 `build_report_queries()` 之类的本地硬编码 query 逻辑。
    - 不再在 report_agent 内部逐条调用 `search()`。
    - 只调用上游 `run_positioning_product_search()`，然后做格式改写。
    """

    runtime_config = config or ReportSearchConfig.from_env()
    description = _clean_required(product_description, "product_description")

    _log(runtime_config, "[upstream] run_positioning_product_search started")
    try:
        # 懒加载上游模块：只有真实跑上游搜索时才导入，避免离线改写/测试时
        # 被 trafilatura、playwright 等上游依赖卡住。
        _, run_positioning_product_search = _load_positioning_workflow()
        upstream_result = run_positioning_product_search(
            description,
            to_positioning_product_config(runtime_config),
        )
    except Exception as exc:
        _log(runtime_config, f"[upstream] failed: {exc}")
        return SearchBundle(queries=[], results=[], errors=[str(exc)])

    _log(
        runtime_config,
        "[upstream] ready: queries={queries} search_results={results} products={products}".format(
            queries=len(getattr(upstream_result, "queries", []) or []),
            results=len(getattr(upstream_result, "search_results", []) or []),
            products=len(getattr(upstream_result, "product_names", []) or []),
        ),
    )
    # 上游返回什么，就原样作为素材交给 adapter。这里不做事实抽取和搜索策略补偿。
    return adapt_upstream_output_for_report(
        upstream_result,
        config=runtime_config,
        product_description=description,
        competitors=competitors,
    )


def adapt_upstream_output_for_report(
    upstream_output: Any,
    *,
    config: Optional[ReportSearchConfig] = None,
    product_description: str = "",
    competitors: Optional[Sequence[str]] = None,
) -> SearchBundle:
    """把任意上游输出改写成 report_agent 可消费的 sources。

    支持的输入包括：
    - `PositioningProductResult`
    - 上游单品报告/横向总结组成的 dict
    - SearchResult 风格对象
    - dataclass、文件路径、字符串或这些对象的列表

    返回的 `SearchBundle.results` 是 dict 列表，字段和上游 SearchResult 保持
    一致：title/url/snippet/content/source/content_source。
    """

    runtime_config = config or ReportSearchConfig.from_env()

    # 第一步只做“收集”，不做语义加工。这样 LLM adapter 能看到尽可能完整的
    # 上游原文，同时保留 queries/product_names 供日志和后续报告使用。
    collected = _collect_upstream_output(upstream_output)
    competitor_list = _dedupe(
        [*(competitors or []), *collected.product_names],
    )

    if not collected.items:
        return SearchBundle(
            queries=collected.queries,
            results=[],
            errors=["No upstream items available to adapt"],
            product_names=competitor_list,
        )

    _log(
        runtime_config,
        f"[adapter] rewriting upstream output: items={len(collected.items)}",
    )
    errors: List[str] = []

    # 优先使用专门的 adapter LLM：它的任务不是写报告，而是把上游材料改写成
    # report_agent evidence structurer 更容易消费的 source 形态。
    adapted = _rewrite_sources_with_llm(
        collected=collected,
        config=runtime_config,
        product_description=product_description,
        competitors=competitor_list,
        errors=errors,
    )
    if not adapted:
        # LLM 不可用、返回非法 JSON 或被用户关闭时，fallback 至少保证链路可跑。
        # fallback 不做智能总结，只把已有字段拼成 SearchResult-like dict。
        _log(runtime_config, "[adapter] using local source-shape fallback")
        adapted = _fallback_sources_from_items(collected.items)

    _log(runtime_config, f"[adapter] adapted sources={len(adapted)}")
    return SearchBundle(
        queries=collected.queries,
        results=adapted,
        errors=errors,
        product_names=competitor_list,
    )


def to_positioning_product_config(config: ReportSearchConfig) -> Any:
    """构造上游 PositioningProductConfig。

    这里的关键点是“适配调用参数”，不是改上游实现；所以通过懒加载拿到上游
    dataclass 后直接实例化。
    """

    PositioningProductConfig, _ = _load_positioning_workflow()
    return PositioningProductConfig(
        llm_api_key=config.llm_api_key,
        llm_base_url=config.llm_base_url,
        llm_model=config.llm_model,
        search_config=to_upstream_search_config(config),
        query_count=config.query_count,
        results_per_query=config.results_per_query,
        verbose=config.verbose,
        progress_printer=config.progress_printer,
    )


def to_upstream_search_config(config: ReportSearchConfig) -> Any:
    """构造上游 SearchConfig。

    字段含义完全沿用 `extracted_core.search.SearchConfig`，本层不重新定义
    搜索语义。
    """

    SearchConfig, SearchSource = _load_search_types()
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
    )


def provider_llm_config_from_env() -> tuple[str, str, str]:
    """读取和根脚本一致的 LLM provider 配置。

    Adapter LLM 默认跟随当前根流程的 LLM_PROVIDER，避免 v2 脚本和
    search_adapter 用两套 provider 规则。
    """

    provider = int(os.getenv("LLM_PROVIDER", "0"))
    if provider == 0:
        return (
            os.getenv("LLM0_API_KEY")
            or os.getenv("ARK_API_KEY")
            or "ARK_API_KEY_REDACTED",
            os.getenv("LLM0_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
            os.getenv("LLM0_MODEL", "ep-20260514111325-xjmj7"),
        )
    if provider == 1:
        keys = _split_pool(os.getenv("LLM_API_KEYS", ""))
        if os.getenv("LLM_API_KEY"):
            keys.append(os.getenv("LLM_API_KEY", ""))
        return (
            os.getenv("LLM1_API_KEY") or (keys[0] if keys else ""),
            os.getenv("LLM1_BASE_URL")
            or os.getenv(
                "LLM_BASE_URL",
                "https://api.siliconflow.cn/v1/chat/completions",
            ),
            os.getenv("LLM1_MODEL")
            or os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
        )
    if provider == 2:
        return (
            os.getenv("LLM2_API_KEY") or os.getenv("MIMO_API_KEY", ""),
            os.getenv("LLM2_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1"),
            os.getenv("LLM2_MODEL", "mimo-v2.5-pro"),
        )
    raise ValueError("LLM_PROVIDER must be 0, 1, or 2")


def _load_positioning_workflow() -> tuple[Any, Callable[..., Any]]:
    """只在真实搜索时加载上游定位工作流。

    这样做是为了让“已有上游输出 -> report_agent”这条链路可以在没有完整
    上游爬虫依赖的环境中运行，方便离线测试和只处理历史报告。
    """

    try:
        from extracted_core.positioning_product_workflow import (
            PositioningProductConfig,
            run_positioning_product_search,
        )

        return PositioningProductConfig, run_positioning_product_search
    except Exception as exc:
        raise ImportError(
            "Upstream positioning workflow is unavailable. Install extracted_core "
            "dependencies before running real upstream search."
        ) from exc


def _load_search_types() -> tuple[Any, Any]:
    """只在需要构造上游 SearchConfig 时加载搜索类型。"""

    try:
        from extracted_core.search import SearchConfig, SearchSource

        return SearchConfig, SearchSource
    except Exception as exc:
        raise ImportError(
            "Upstream search types are unavailable. Install extracted_core "
            "dependencies before running real upstream search."
        ) from exc


def _load_chat_content() -> Callable[..., str]:
    """加载共享 LLM client。

    首选正常包导入；如果 `extracted_core.__init__` 因爬虫依赖导入失败，则按
    文件路径直接加载 `llm_client.py`。这样 adapter LLM 不被搜索依赖耦合。
    """

    try:
        from extracted_core.llm_client import chat_content as upstream_chat_content

        return upstream_chat_content
    except Exception:
        llm_path = (
            Path(__file__).resolve().parents[1]
            / "extracted_core"
            / "llm_client.py"
        )
        spec = importlib.util.spec_from_file_location(
            "_report_adapter_llm_client",
            llm_path,
        )
        if not spec or not spec.loader:
            raise
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.chat_content


def _rewrite_sources_with_llm(
    *,
    collected: _CollectedUpstreamOutput,
    config: ReportSearchConfig,
    product_description: str,
    competitors: Sequence[str],
    errors: List[str],
) -> List[dict[str, Any]]:
    """用 LLM 把上游材料改写成 source 列表。

    这个函数只做“格式和表达改写”，不做报告生成，也不应该补充上游没有的
    事实。返回值还会经过 `_normalize_adapted_source()` 做字段校验。
    """

    if not _can_use_adapter_llm(config):
        errors.append("adapter LLM disabled or not configured")
        return []

    # 把上游输出打包成一个明确 payload，让模型知道哪些是需求、哪些是候选
    # 产品、哪些是原始材料。模型只从 upstream_items 中抽取/压缩事实。
    payload = {
        "product_description": product_description,
        "competitors": list(competitors),
        "upstream_queries": collected.queries,
        "upstream_product_names": collected.product_names,
        "upstream_items": [_serialize_item(item) for item in collected.items],
    }
    payload_text = _json_dumps(payload)
    if len(payload_text) > config.adapter_max_input_chars:
        # 大报告可能非常长，adapter 只需要足够的证据密度文本。截断发生在
        # prompt 输入侧，不会修改上游落盘文件。
        payload_text = payload_text[: config.adapter_max_input_chars].rstrip()

    prompt = f"""
你是 report_agent 的上游输出改写智能体。

目标:
把上游原始输出改写成 report_agent.core.run_writing_agent 可以消费的搜索来源列表。

输入是上游输出原文/结构化对象，可能包含搜索结果、单品报告、FINAL SUMMARY、参考点或最终横向总结。

输出要求:
- 只输出严格 JSON，不要 Markdown。
- 不要编造上游没有的信息，不要补 URL，不要改写引用标记。
- 尽量保留产品名、事实、限制、定价、集成、目标用户、优势短板、参考点编号和来源路径。
- 如果上游对象已经有 title/url/snippet/content/source/content_source 字段，保留其事实并按同名字段输出。
- content 要是证据密度高的正文，适合后续 evidence structurer 抽证据。
- url 没有网页链接时可使用上游文件路径；确实没有就置空字符串。

返回 JSON schema:
{{
  "sources": [
    {{
      "title": "来源标题",
      "url": "网页链接或上游文件路径",
      "snippet": "短摘要",
      "content": "保留事实和引用的正文",
      "source": "upstream",
      "content_source": "search_adapter_ai_rewrite"
    }}
  ]
}}

上游输出:
{payload_text}
""".strip()

    try:
        chat_content = _load_chat_content()
        content = chat_content(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": "你只把上游输出改写为严格 JSON sources。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=config.adapter_temperature,
            max_tokens=config.adapter_max_tokens,
            timeout=config.adapter_timeout,
        )
    except Exception as exc:
        errors.append(f"adapter LLM call failed: {exc}")
        _log(config, f"[adapter] LLM call failed: {exc}")
        return []

    data = parse_json_payload(content or "")
    raw_sources = data.get("sources") if isinstance(data, dict) else data
    if not isinstance(raw_sources, list):
        errors.append("adapter LLM returned invalid sources JSON")
        return []

    sources: List[dict[str, Any]] = []
    for raw in raw_sources:
        # 对 LLM 输出做本地 schema 清洗，避免空 source 或奇怪字段污染
        # evidence_structurer。
        source = _normalize_adapted_source(raw)
        if source:
            sources.append(source)
    if not sources:
        errors.append("adapter LLM returned no usable sources")
    return sources


def _collect_upstream_output(upstream_output: Any) -> _CollectedUpstreamOutput:
    """递归收集上游输出中的 query、产品名和材料条目。

    这里尽量宽容，是因为上游有多种形态：第一阶段搜索结果、单品报告文件、
    v2 汇总 dict、历史报告路径等。宽容收集可以降低上游变更对中游的影响。
    """

    queries: List[str] = []
    product_names: List[str] = []
    items: List[Any] = []

    def visit(value: Any) -> None:
        nonlocal queries, product_names, items
        if value is None:
            return

        # SearchResult-like 或报告条目已经是“材料”，不用再拆内部字段。
        if _looks_like_source_item(value):
            items.append(value)
            return

        if is_dataclass(value):
            # dataclass 先转成 dict，方便统一读取 queries/product_names/search_results。
            data = asdict(value)
            queries.extend(_string_list(data.get("queries")))
            product_names.extend(_string_list(data.get("product_names")))
            if "search_results" in data:
                visit(data.get("search_results"))
                return
            if _looks_like_report_item(data):
                items.append(data)
                return
            items.append(data)
            return

        if isinstance(value, dict):
            # 常见的上游容器字段先拆出来递归处理；未知 dict 则作为一个材料条目
            # 保留下来，交给 adapter LLM 判断如何使用。
            queries.extend(_string_list(value.get("queries")))
            product_names.extend(
                _string_list(value.get("product_names"))
                or _string_list(value.get("selected_products"))
                or _string_list(value.get("competitors"))
            )
            handled = False
            for key in (
                "search_results",
                "results",
                "single_product_reports",
                "reports",
                "report_inputs",
            ):
                if key in value:
                    visit(value.get(key))
                    handled = True
            if "final_comparison" in value:
                visit(value.get("final_comparison"))
                handled = True
            if _looks_like_report_item(value) or _looks_like_source_item(value):
                items.append(value)
                handled = True
            if not handled:
                items.append(value)
            return

        if isinstance(value, (list, tuple, set)):
            # 列表容器只负责展开，不在这里决定每个元素的含义。
            for item in value:
                visit(item)
            return

        if isinstance(value, Path):
            # 文件路径是 v2 接入历史报告时最常见的形态之一。
            items.append(_path_to_item(value))
            return

        text = str(value).strip()
        if text:
            maybe_path = Path(text)
            if len(text) < 500 and maybe_path.exists() and maybe_path.is_file():
                # 字符串也可能是路径；短字符串才尝试按路径解析，避免超长正文
                # 被误判成路径。
                items.append(_path_to_item(maybe_path))
            else:
                items.append({"title": "Upstream output", "content": text})

    visit(upstream_output)
    return _CollectedUpstreamOutput(
        queries=_dedupe(queries),
        product_names=_dedupe(product_names),
        items=items,
    )


def _fallback_sources_from_items(items: Iterable[Any]) -> List[dict[str, Any]]:
    """LLM adapter 不可用时的保底转换。

    fallback 的目标不是“聪明”，而是确保 report_agent 能拿到
    SearchResult-like 输入继续运行。
    """

    sources: List[dict[str, Any]] = []
    for item in items:
        source = _source_from_upstream_item(item)
        if source:
            sources.append(source)
    return sources


def _source_from_upstream_item(item: Any) -> Optional[dict[str, Any]]:
    """把单个上游材料条目保守转换成 source dict。"""

    data = _as_mapping(item)

    title = clean_text(
        data.get("title")
        or data.get("product_name")
        or data.get("name")
        or data.get("question")
        or "Upstream source",
        240,
    )
    url = clean_text(data.get("url") or data.get("path") or data.get("file_path"), 600)
    snippet = clean_text(
        data.get("snippet")
        or data.get("final_summary")
        or data.get("summary")
        or data.get("text"),
        1400,
    )

    content_parts = []
    # 对上游报告而言，reference_points 和完整 report_markdown 往往比摘要更
    # 适合作为证据来源，因此 fallback 会优先把这些字段拼进 content。
    for key in (
        "content",
        "final_summary",
        "reference_points",
        "report_markdown",
        "full_report",
        "text",
    ):
        value = data.get(key)
        if value:
            content_parts.append(str(value))
    content = clean_text("\n\n".join(content_parts) or snippet, 6000)
    if not (title or snippet or content):
        return None

    return {
        "title": title or "Upstream source",
        "url": url,
        "snippet": snippet,
        "content": content,
        "source": clean_text(data.get("source"), 80) or "upstream",
        "content_source": clean_text(data.get("content_source"), 120)
        or "search_adapter_local_fallback",
    }


def _normalize_adapted_source(raw: Any) -> Optional[dict[str, Any]]:
    """清洗 LLM adapter 输出的一条 source。"""

    if not isinstance(raw, dict):
        return None

    title = clean_text(raw.get("title"), 240)
    url = clean_text(raw.get("url"), 600)
    snippet = clean_text(raw.get("snippet"), 1400)
    content = clean_text(raw.get("content") or snippet, 6000)
    if not (title or snippet or content):
        return None

    return {
        "title": title or "Upstream source",
        "url": url,
        "snippet": snippet,
        "content": content,
        "source": clean_text(raw.get("source"), 80) or "upstream",
        "content_source": clean_text(raw.get("content_source"), 120)
        or "search_adapter_ai_rewrite",
    }


def _as_mapping(item: Any) -> dict[str, Any]:
    """把 dict/dataclass/属性对象统一成 dict，供后续字段读取。"""

    if isinstance(item, dict):
        return dict(item)
    if is_dataclass(item):
        return asdict(item)
    return {
        "title": getattr(item, "title", ""),
        "url": getattr(item, "url", ""),
        "snippet": getattr(item, "snippet", ""),
        "content": getattr(item, "content", ""),
        "source": getattr(item, "source", ""),
        "content_source": getattr(item, "content_source", ""),
        "product_name": getattr(item, "product_name", ""),
        "final_summary": getattr(item, "final_summary", ""),
        "reference_points": getattr(item, "reference_points", ""),
        "path": str(getattr(item, "path", "")),
    }


def _serialize_item(item: Any) -> Any:
    """序列化上游材料，去掉空字段，减少 prompt 噪声。"""

    data = _as_mapping(item)
    return {
        key: value
        for key, value in data.items()
        if value not in (None, "", [], {})
    }


def _path_to_item(path: Path) -> dict[str, str]:
    """把报告文件路径读取成 source-like 材料。"""

    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "title": path.stem,
        "url": str(path),
        "snippet": text[:1000],
        "content": text,
        "source": "upstream_file",
        "content_source": "upstream_file",
    }


def _looks_like_source_item(value: Any) -> bool:
    """判断对象是否已经像一个 source/search result。"""

    if isinstance(value, dict):
        keys = set(value)
        return bool({"title", "url", "snippet", "content"} & keys) and not bool(
            {"search_results", "single_product_reports", "reports"} & keys
        )
    return any(
        hasattr(value, key)
        for key in ("title", "url", "snippet", "content", "final_summary")
    )


def _looks_like_report_item(value: dict[str, Any]) -> bool:
    """判断 dict 是否是上游单品报告/汇总报告条目。"""

    return bool(
        {"product_name", "final_summary", "reference_points", "report_markdown"}
        & set(value)
    )


def _can_use_adapter_llm(config: ReportSearchConfig) -> bool:
    """adapter LLM 是否具备调用条件。"""

    return bool(
        config.adapter_use_llm
        and config.llm_api_key
        and config.llm_base_url
        and config.llm_model
    )


def _clean_required(value: object, field_name: str) -> str:
    text = clean_text(value)
    if not text:
        raise ValueError(f"{field_name} cannot be empty")
    return text


def _dedupe(values: Iterable[Any]) -> List[str]:
    """按原顺序去重，并统一清理空白。"""

    results: List[str] = []
    seen: set[str] = set()
    for value in values:
        item = clean_text(value)
        if item and item not in seen:
            seen.add(item)
            results.append(item)
    return results


def _string_list(value: Any) -> List[str]:
    """把字符串或序列统一转换为字符串列表。"""

    if not value:
        return []
    if isinstance(value, str):
        return _split_pool(value)
    if isinstance(value, (list, tuple, set)):
        return [clean_text(item) for item in value if clean_text(item)]
    return []


def _split_pool(value: str) -> List[str]:
    return [
        item.strip()
        for item in re.split(r"[,，、;\n]+", value or "")
        if item.strip()
    ]


def _env_bool(name: str, default: bool) -> bool:
    """读取布尔环境变量，支持常见关闭写法。"""

    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "否", "关闭"}


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _log(config: ReportSearchConfig, message: str) -> None:
    if config.verbose and config.progress_printer:
        config.progress_printer(message)
        sys.stdout.flush()

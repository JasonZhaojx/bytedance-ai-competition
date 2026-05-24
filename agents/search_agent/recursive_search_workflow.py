"""Heuristic recursive Bocha search workflow guided by an LLM."""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ..workflow.llm_client import chat_content, stream_chat_content
from .search import SearchConfig, SearchResult, search
class RecursiveSearchConfig:
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    search_config: SearchConfig
    max_rounds: int = 4
    initial_query_count: int = 1
    next_query_count: int = 3
    results_per_query: int = 5
    max_evidence_items: int = 30
    evidence_text_chars: int = 3200
    node_summary_chars: int = 1200
    temperature: float = 0.2
    planning_temperature: float = 0.65
    max_tokens: int = 2500
    max_parallel_nodes: int = 4
    llm_timeout: int = 120
    final_llm_timeout: int = 900
    verbose: bool = True
    progress_printer: Optional[Callable[[str], None]] = print
    final_stream_printer: Optional[Callable[[str], None]] = None
    skip_final_summary: bool = False
    filter_irrelevant_evidence: bool = True
    comparison_keyword_library: str = ""
    search_func: Optional[Callable[[str, SearchConfig], List[SearchResult]]] = None


FULL_TEXT_CHARS = 0


@dataclass
class EvidenceItem:
    query: str
    round_index: int
    title: str
    url: str
    snippet: str = ""
    content: str = ""
    content_source: str = ""


@dataclass
class RecursiveSearchResult:
    question: str
    evidence: List[EvidenceItem]
    final_answer: str
    rounds: List[Dict[str, object]] = field(default_factory=list)


@dataclass
class SearchNode:
    query: str
    depth: int
    node_id: str
    parent_id: Optional[str] = None
    evidence: List[EvidenceItem] = field(default_factory=list)
    summary: str = ""
    children: List["SearchNode"] = field(default_factory=list)


@dataclass
class TreeSearchResult:
    question: str
    root: SearchNode
    final_answer: str
    evidence: List[EvidenceItem]
    tree_summary: str = ""


def _log(config: RecursiveSearchConfig, message: str) -> None:
    if config.verbose and config.progress_printer:
        config.progress_printer(message)


def _max_possible_tree_nodes(max_rounds: int, child_count: int) -> int:
    if max_rounds <= 0:
        return 0
    if child_count <= 0:
        return 1
    if child_count == 1:
        return max_rounds
    return sum(child_count**depth for depth in range(max_rounds))


def _progress_bar(done: int, total: int, width: int = 24) -> tuple[str, float]:
    if total <= 0:
        ratio = 0.0
    else:
        ratio = min(1.0, max(0.0, done / total))
    filled = round(ratio * width)
    return f"[{'#' * filled}{'-' * (width - filled)}]", ratio


def _parse_json_object(content: str) -> Dict[str, object]:
    cleaned = content.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned)


def _normalize_queries(value: object, max_items: int) -> List[str]:
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


def _comparison_keyword_queue(library: str) -> List[str]:
    keywords = []
    seen = set()
    for line in library.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("说明"):
            continue
        if ":" in line or "：" in line:
            _, line = re.split(r"[:：]", line, maxsplit=1)
        for part in re.split(r"[,，、;/；|]+", line):
            keyword = " ".join(part.strip().split())
            if not keyword or keyword in seen:
                continue
            seen.add(keyword)
            keywords.append(keyword)
    return keywords


def _format_evidence(evidence: List[EvidenceItem], max_chars: int) -> str:
    blocks = []
    for index, item in enumerate(evidence, 1):
        text = item.content or item.snippet
        if max_chars and max_chars > 0:
            text = text[:max_chars]
        blocks.append(
            "\n".join(
                [
                    f"[{index}] 轮次={item.round_index} 搜索词={item.query}",
                    f"正文来源: {item.content_source or '未知'}",
                    f"标题: {item.title}",
                    f"链接: {item.url}",
                    f"正文: {text}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _format_reference_evidence(evidence: List[EvidenceItem], max_chars: int) -> str:
    """Format only reference points and text for final synthesis."""
    blocks = []
    for index, item in enumerate(evidence, 1):
        text = item.content or item.snippet
        if max_chars and max_chars > 0:
            text = text[:max_chars]
        blocks.append(
            "\n".join(
                [
                    f"[参考点{index}]",
                    f"正文来源: {item.content_source or '未知'}",
                    f"标题: {item.title}",
                    f"链接: {item.url}",
                    f"正文: {text}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _format_search_results_for_filter(results: List[SearchResult], max_chars: int = 900) -> str:
    blocks = []
    for index, item in enumerate(results, 1):
        text = item.content or item.snippet
        if max_chars and len(text) > max_chars:
            text = text[:max_chars]
        blocks.append(
            "\n".join(
                [
                    f"[{index}]",
                    f"标题: {item.title}",
                    f"链接: {item.url}",
                    f"正文: {text}",
                ]
            )
        )
    return "\n\n".join(blocks)


def filter_relevant_search_results(
    question: str,
    query: str,
    results: List[SearchResult],
    config: RecursiveSearchConfig,
) -> List[SearchResult]:
    if not config.filter_irrelevant_evidence or not results:
        return results

    prompt = f"""
你是搜索结果相关性过滤器。

调研主题:
{question}

本次搜索词:
{query}

搜索结果:
{_format_search_results_for_filter(results)}

任务:
判断每条搜索结果是否应该作为本次调研的参考点保留。

保留标准:
- 结果内容必须能帮助理解调研主题本身、同类产品、竞品、替代品、功能定位、价格、用户反馈、限制、评测或使用场景。
- 只要对主题有明确帮助，即使不是官网也可以保留。

移除标准:
- 只是在字面上碰巧包含关键词，但主题不相关。
- 广告、导航页、无实质内容、明显跑题、完全不同产品或不同概念。
- 内容太空泛，无法支持任何调研结论。

只返回严格 JSON:
{{
  "keep_indexes": [1, 3],
  "remove_indexes": [2],
  "reason": "简要说明过滤原因"
}}
""".strip()

    try:
        content = chat_content(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
            messages=[
                {"role": "system", "content": "你负责过滤搜索结果，只返回严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=800,
            timeout=config.llm_timeout,
        )
        data = _parse_json_object(content or "{}")
    except Exception as exc:
        _log(config, f"[filter] 相关性过滤失败，保留原结果: {exc}")
        return results

    keep_indexes = data.get("keep_indexes")
    if not isinstance(keep_indexes, list):
        return results

    keep_numbers = {
        int(value)
        for value in keep_indexes
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit())
    }
    filtered = [
        item
        for index, item in enumerate(results, 1)
        if index in keep_numbers
    ]
    removed_count = len(results) - len(filtered)
    reason = str(data.get("reason", "") or "")
    _log(config, f"[filter] query={query} 保留 {len(filtered)}/{len(results)} 条，移除 {removed_count} 条。{reason}")
    return filtered


def _flatten_tree(root: SearchNode) -> List[SearchNode]:
    nodes = [root]
    for child in root.children:
        nodes.extend(_flatten_tree(child))
    return nodes


def _tree_outline(root: SearchNode, summary_chars: int = FULL_TEXT_CHARS) -> str:
    lines = []

    def walk(node: SearchNode, indent: int) -> None:
        prefix = "  " * indent
        lines.append(
            f"{prefix}- node={node.node_id} depth={node.depth} query={node.query} "
            f"evidence={len(node.evidence)}"
        )
        if node.summary:
            summary = node.summary[:summary_chars] if summary_chars and summary_chars > 0 else node.summary
            lines.append(f"{prefix}  summary={summary}")
        for child in node.children:
            walk(child, indent + 1)

    walk(root, 0)
    return "\n".join(lines)


def render_tree_summary(root: SearchNode, summary_chars: int = FULL_TEXT_CHARS) -> str:
    """Render the search tree with each node's local summary."""
    lines = []

    def walk(node: SearchNode, indent: int) -> None:
        prefix = "  " * indent
        connector = "- " if indent == 0 else "+- "
        lines.append(f"{prefix}{connector}[{node.node_id}] 搜索词: {node.query}")
        lines.append(f"{prefix}   深度: {node.depth}; 参考点数量: {len(node.evidence)}")
        summary = node.summary.strip() if node.summary else "暂无节点总结。"
        if summary_chars and summary_chars > 0 and len(summary) > summary_chars:
            summary = summary[:summary_chars]
        lines.append(f"{prefix}   summary: {summary}")
        for child in node.children:
            walk(child, indent + 1)

    walk(root, 0)
    return "\n".join(lines)


def _dedupe_results(
    results: List[SearchResult],
    seen_urls: set[str],
    query: str,
    round_index: int,
) -> List[EvidenceItem]:
    items = []
    for result in results:
        if not result.url or result.url in seen_urls:
            continue
        seen_urls.add(result.url)
        items.append(
            EvidenceItem(
                query=query,
                round_index=round_index,
                title=result.title,
                url=result.url,
                snippet=result.snippet,
                content=result.content,
                content_source=result.content_source,
            )
        )
    return items


def plan_next_queries(
    question: str,
    evidence: List[EvidenceItem],
    config: RecursiveSearchConfig,
    round_index: int,
) -> Dict[str, object]:
    """Ask the LLM whether to continue and which queries to search next."""
    evidence_text = _format_evidence(evidence, config.evidence_text_chars)
    prompt = f"""
你正在控制一个递归网页搜索工作流。

原始问题或调研对象:
{question}

目前已经收集到的资料:
{evidence_text}

请判断是否还需要继续搜索。如果需要，请生成少量聚焦的博查网页搜索词，用来补全缺失事实、换一种说法检索、扩大来源类型、查找真实使用场景、社区体验和相互矛盾的信息。
调研对象可能是实体产品、互联网产品、AI/Vibe Coding 工具、SaaS、服务、开源项目、创作者工具流、公司、政策或技术概念。
不要只搜索官网；文档、更新日志、帮助中心、应用商店页面、电商页面、评测、实测、榜单、拆解、教程、GitHub issue、论坛、博客、社交/社区帖子和用户反馈都可以作为有效资料。
避免重复已经搜过的宽泛关键词。

只返回严格 JSON:
{{
  "analysis": "简要说明目前已知什么、还不确定什么、为什么",
  "need_more_search": true,
  "next_queries": ["搜索词1", "搜索词2"],
  "final_answer": "只有 need_more_search 为 false 时才填写"
}}

约束:
- next_queries 包含 1 到 {config.next_query_count} 个搜索词。
- 如果调研对象偏中文语境，优先生成准确的中文搜索词。
- 搜索角度要匹配对象：实体产品可关注 参数/规格/测评/实测/拆解/体验/缺点/用户反馈；互联网产品或 AI/Vibe 工具可关注 文档/API/价格/更新日志/GitHub/issue/benchmark/教程/替代品/限制/workflow/用户反馈。
- 如果资料已经足够，或继续搜索大概率只是重复，请停止搜索。
""".strip()

    _log(config, f"[llm-plan] Round {round_index}: asking model for next queries")
    content = chat_content(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
        messages=[
            {
                "role": "system",
                "content": "你负责规划递归网页搜索，并且只返回严格 JSON。",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        timeout=config.llm_timeout,
    )
    data = _parse_json_object(content or "{}")
    data["next_queries"] = _normalize_queries(data.get("next_queries"), config.next_query_count)
    return data


def final_summarize(
    question: str,
    evidence: List[EvidenceItem],
    config: RecursiveSearchConfig,
) -> str:
    evidence_text = _format_evidence(evidence, config.evidence_text_chars)
    prompt = f"""
请只根据下面的资料，用中文回答用户的问题或调研对象。
如果资料不完整或互相矛盾，请明确说明。关键结论需要在正文中标注来源 URL。

问题或调研对象:
{question}

资料:
{evidence_text}
""".strip()
    _log(config, "[llm-final] Generating final answer")
    return chat_content(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
        messages=[
            {
                "role": "system",
                "content": "你根据给定资料写中文调研总结，并在关键事实处保留 URL。",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        timeout=config.llm_timeout,
    )


def summarize_node(
    question: str,
    node: SearchNode,
    config: RecursiveSearchConfig,
) -> str:
    if not node.evidence:
        return "这个搜索词没有找到可用资料。"

    evidence_text = _format_evidence(node.evidence, config.evidence_text_chars)
    prompt = f"""
原始问题或调研对象:
{question}

当前搜索节点:
- node_id: {node.node_id}
- 深度: {node.depth}
- 搜索词: {node.query}

这个节点找到的资料:
{evidence_text}

请只总结这个节点的资料，用中文输出，并保留有用细节。
请按调研对象选择合适的来源标准：官网和文档很有价值，但不是唯一来源；评测、榜单、教程、GitHub issue、论坛、博客、社区帖子、应用商店页面、电商页面和用户反馈也可以作为有效证据。
如果是实体产品，请保留参数和规格；如果是互联网产品或 AI/Vibe 工具，请保留能力、价格、限制、集成方式、工作流、版本、可靠性和用户抱怨。
如果关键结论来自非官方来源，请说明来源类型，并指出不确定性。

请包含:
1. 这个节点发现的关键事实。
2. 重要数字、规格、功能、价格、限制、主张及其来源 URL。
3. 不确定、冲突或证据较弱的地方。
4. 这个分支提示的后续搜索线索。

不要过度压缩；保留足够细节，方便后续做整棵搜索树的综合总结。
""".strip()

    _log(config, f"[tree-summary] node={node.node_id} summarizing evidence")
    return chat_content(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
        messages=[
            {
                "role": "system",
                "content": "你用中文总结递归搜索树中的一个分支。",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        timeout=config.llm_timeout,
    )


def plan_child_queries(
    question: str,
    node: SearchNode,
    config: RecursiveSearchConfig,
    injected_keywords: Optional[List[str]] = None,
) -> List[str]:
    if node.depth >= config.max_rounds - 1:
        return []

    evidence_text = _format_evidence(node.evidence, config.evidence_text_chars)
    injected_keywords = injected_keywords or []
    keyword_hint = "、".join(injected_keywords) if injected_keywords else "无，本轮自由搜索"
    prompt = f"""
你正在扩展递归网页搜索树中的一个节点。

原始问题或调研对象:
{question}

本轮注入的已知产品参数关键词:
{keyword_hint}

当前节点:
- 搜索词: {node.query}
- 深度: {node.depth}
- 节点总结: {node.summary}

这个节点的资料:
{evidence_text}

只有当这个分支仍然存在值得探索的缺失信息时，才生成子搜索词。
请启发式、发散但聚焦：扩展到真正不同的角度，而不是重复显而易见的关键词。
如果“本轮注入的已知产品参数关键词”不是“无”，请优先围绕这些关键词生成本轮子搜索词；尽量让一个关键词对应一个子搜索词，让不同竞品最终可以在相同维度上对比。
如果本轮注入为“无”，请按当前节点证据自由生成最有价值的后续搜索词。

可用的子搜索方向包括:
- 官方页面、权威来源、文档、帮助中心、更新日志、发布说明
- 评测、教程、实测体验、benchmark、测试、横向对比
- 论坛、Reddit、GitHub issue/discussion、社区帖子、用户抱怨
- 限制、失败案例、负面评价、可靠性、支持体验
- 价格、套餐、可用性、版本、地区差异、集成方式
- 别名、中英文名、型号、昵称、旧名/新名
- 实体产品: 参数、规格、测评、实测、拆解、维修、售后
- 互联网产品或 AI/Vibe 工具: 文档、API、价格、工作流、示例、模板、插件、IDE/编辑器支持、部署、隐私、限制
- 本轮注入关键词对应的维度，例如定价、套餐、部署方式、目标用户、核心功能、限制、集成、隐私、安全、企业版、免费额度等

子搜索词应比当前搜索词更具体，不要只是重复当前搜索词。

只返回严格 JSON:
{{
  "need_children": true,
  "child_queries": ["搜索词1", "搜索词2"],
  "reason": "简要原因"
}}

约束:
- child_queries 包含 0 到 {config.next_query_count} 个搜索词。
- 如果相关，优先生成聚焦的中文搜索词。
- 如果这个分支价值已经较低或重复，请设置 need_children=false。
""".strip()

    _log(config, f"[tree-plan] node={node.node_id} planning children")
    content = chat_content(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
        messages=[
            {
                "role": "system",
                "content": "你负责扩展递归搜索树节点，并且只返回严格 JSON。",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=config.planning_temperature,
        max_tokens=1000,
        timeout=config.llm_timeout,
    )
    data = _parse_json_object(content or "{}")
    reason = data.get("reason", "")
    _log(config, f"[tree-plan] node={node.node_id} reason={reason}")
    if not data.get("need_children", True):
        return []
    return _normalize_queries(data.get("child_queries"), config.next_query_count)


def tree_final_summarize(
    question: str,
    root: SearchNode,
    evidence: List[EvidenceItem],
    config: RecursiveSearchConfig,
) -> str:
    def build_prompt(evidence_chars: int) -> str:
        evidence_text = _format_reference_evidence(evidence, evidence_chars)
        tree_summary = render_tree_summary(root, config.node_summary_chars)
        comparison_keywords = config.comparison_keyword_library.strip() or "无"
        return f"""
请根据下面的参考点和正文内容，用中文生成一份产品调研总结。
不要使用参考点之外的信息；如果证据不足或互相矛盾，请直接说明。
总结中的关键事实后面要标注参考点编号，例如：[参考点1]。
如果“已知产品参数关键词库”不为空，请优先按这些共同参数点组织总结；缺失的参数点也要说明“未找到明确证据”。

调研对象:
{question}

已知产品参数关键词库:
{comparison_keywords}

搜索树摘要:
{tree_summary}

参考点与正文:
{evidence_text}
""".strip()

    _log(config, "[tree-final] Generating final answer from reference evidence")
    messages = [
        {
            "role": "system",
            "content": "你只根据给定参考点正文做中文产品调研总结，并保留参考点编号。",
        },
        {"role": "user", "content": build_prompt(config.evidence_text_chars)},
    ]
    try:
        if config.final_stream_printer:
            chunks = []
            for chunk in stream_chat_content(
                api_key=config.llm_api_key,
                base_url=config.llm_base_url,
                model=config.llm_model,
                messages=messages,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout=config.final_llm_timeout,
            ):
                chunks.append(chunk)
                config.final_stream_printer(chunk)
            return "".join(chunks)

        return chat_content(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
            messages=messages,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.final_llm_timeout,
            retries=1,
        )
    except Exception as exc:
        _log(config, f"[tree-final] Full-context summary failed: {exc}")
        return (
            "最终模型总结失败。"
            "参考点证据已经在上方输出。"
        )


def run_tree_search(
    question: str,
    config: RecursiveSearchConfig,
) -> TreeSearchResult:
    """Run a true tree-shaped recursive Bocha search."""
    _log(config, f"[tree] Start tree search: {question}")

    original_count = config.search_config.count
    original_max_results = config.search_config.max_search_results
    seen_urls: set[str] = set()
    scheduled_queries: set[str] = set()
    searched_queries: set[str] = set()
    all_evidence: List[EvidenceItem] = []
    keyword_queue = _comparison_keyword_queue(config.comparison_keyword_library)
    keyword_cursor = 0
    node_counter = 0
    discovered_nodes = 0
    completed_nodes = 0
    planned_child_nodes = 0
    theoretical_nodes = _max_possible_tree_nodes(config.max_rounds, config.next_query_count)
    root = SearchNode(query=question, depth=0, node_id="n0")
    tree_summary = ""
    state_lock = threading.Lock()

    def claim_comparison_keywords(count: int) -> List[str]:
        nonlocal keyword_cursor
        with state_lock:
            if keyword_cursor >= len(keyword_queue):
                return []
            end = min(len(keyword_queue), keyword_cursor + max(1, count))
            keywords = keyword_queue[keyword_cursor:end]
            keyword_cursor = end
            return keywords

    def log_progress(stage: str = "") -> None:
        with state_lock:
            done = completed_nodes
            total = max(discovered_nodes + planned_child_nodes, done, 1)
        bar, ratio = _progress_bar(done, total)
        suffix = f" {stage}" if stage else ""
        _log(
            config,
            f"[tree-progress] {bar} {ratio * 100:5.1f}% "
            f"已完成 {done}/{total} 节点；理论上限 {theoretical_nodes}{suffix}",
        )

    def next_node_id() -> str:
        nonlocal discovered_nodes, node_counter
        with state_lock:
            node_counter += 1
            discovered_nodes += 1
            return f"n{node_counter}"

    def claim_query(node: SearchNode) -> bool:
        with state_lock:
            if len(all_evidence) >= config.max_evidence_items:
                return False
            if node.query in searched_queries:
                return False
            scheduled_queries.add(node.query)
            searched_queries.add(node.query)
            return True

    def add_evidence(node: SearchNode, results: List[SearchResult]) -> None:
        items: List[EvidenceItem] = []
        with state_lock:
            if len(all_evidence) >= config.max_evidence_items:
                node.evidence = []
                return
            remaining = config.max_evidence_items - len(all_evidence)
            for result in results:
                if remaining <= 0:
                    break
                if not result.url or result.url in seen_urls:
                    continue
                seen_urls.add(result.url)
                items.append(
                    EvidenceItem(
                        query=node.query,
                        round_index=node.depth + 1,
                        title=result.title,
                        url=result.url,
                        snippet=result.snippet,
                        content=result.content,
                        content_source=result.content_source,
                    )
                )
                remaining -= 1
            node.evidence = items
            all_evidence.extend(items)

    def reserve_child_queries(queries: List[str]) -> List[str]:
        reserved = []
        with state_lock:
            for query in queries:
                if len(all_evidence) >= config.max_evidence_items:
                    break
                if query in scheduled_queries:
                    continue
                scheduled_queries.add(query)
                reserved.append(query)
        return reserved

    def process_node(node: SearchNode) -> List[str]:
        nonlocal completed_nodes, planned_child_nodes
        child_queries: List[str] = []
        if not claim_query(node):
            _log(config, f"[tree-skip] Already searched or limit reached: {node.query}")
            with state_lock:
                completed_nodes += 1
            log_progress(f"跳过 {node.node_id}")
            return []

        log_progress(f"开始 {node.node_id}")
        try:
            _log(config, f"[tree-search] node={node.node_id} depth={node.depth} query={node.query}")
            search_runner = config.search_func or search
            results = search_runner(node.query, config.search_config)
            _log(config, f"[tree-search] node={node.node_id} results={len(results)}")
            results = filter_relevant_search_results(question, node.query, results, config)
            _log(config, f"[tree-search] node={node.node_id} relevant_results={len(results)}")
            add_evidence(node, results)

            node.summary = summarize_node(question, node, config)
            _log(config, f"[tree-summary] node={node.node_id}\n{node.summary}")

            with state_lock:
                reached_evidence_limit = len(all_evidence) >= config.max_evidence_items
            if node.depth < config.max_rounds - 1 and not reached_evidence_limit:
                try:
                    injected_keywords = claim_comparison_keywords(config.next_query_count)
                    if injected_keywords:
                        _log(
                            config,
                            f"[keyword-inject] node={node.node_id} 使用关键词 "
                            f"{keyword_cursor - len(injected_keywords) + 1}-{keyword_cursor}/"
                            f"{len(keyword_queue)}: {'、'.join(injected_keywords)}",
                        )
                    else:
                        _log(config, f"[keyword-inject] node={node.node_id} 关键词库已用完，自由搜索")
                    child_queries = plan_child_queries(question, node, config, injected_keywords)
                except Exception as exc:
                    _log(config, f"[tree-plan] node={node.node_id} failed: {exc}")
        except Exception as exc:
            _log(config, f"[tree-node] node={node.node_id} failed: {exc}")

        with state_lock:
            planned_child_nodes += len(child_queries)
            completed_nodes += 1
        log_progress(f"完成 {node.node_id}，生成 {len(child_queries)} 个子节点")
        return child_queries

    def attach_children(parent: SearchNode, queries: List[str]) -> List[SearchNode]:
        nonlocal planned_child_nodes
        children = []
        for query in reserve_child_queries(queries):
            child = SearchNode(
                query=query,
                depth=parent.depth + 1,
                node_id=next_node_id(),
                parent_id=parent.node_id,
            )
            parent.children.append(child)
            children.append(child)
            _log(config, f"[tree-child] {parent.node_id} -> {child.node_id}: {query}")
        if children:
            with state_lock:
                planned_child_nodes = max(0, planned_child_nodes - len(children))
            log_progress(f"{parent.node_id} 已挂载 {len(children)} 个子节点")
        return children

    def process_level(nodes: List[SearchNode]) -> List[SearchNode]:
        if not nodes:
            return []
        workers = max(1, min(config.max_parallel_nodes, len(nodes)))
        _log(config, f"[tree-level] depth={nodes[0].depth} nodes={len(nodes)} workers={workers}")
        next_level: List[SearchNode] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_node = {executor.submit(process_node, node): node for node in nodes}
            for future in as_completed(future_to_node):
                node = future_to_node[future]
                try:
                    child_queries = future.result()
                except Exception as exc:
                    _log(config, f"[tree-node] node={node.node_id} failed: {exc}")
                    child_queries = []
                next_level.extend(attach_children(node, child_queries))
        return next_level

    def expand_tree(root_node: SearchNode) -> None:
        current_level = [root_node]
        while current_level:
            current_level = process_level(current_level)
            with state_lock:
                if len(all_evidence) >= config.max_evidence_items:
                    _log(config, "[tree] Reached max evidence items")
                    break

    def expand_node(node: SearchNode) -> None:
        """Compatibility wrapper for the former depth-first implementation."""
        if node.query in searched_queries:
            return
        expand_tree(node)

    try:
        config.search_config.count = config.results_per_query
        config.search_config.max_search_results = max(
            config.search_config.max_search_results,
            config.results_per_query,
        )

        root = SearchNode(query=question, depth=0, node_id=next_node_id())
        log_progress("初始化根节点")
        expand_tree(root)
        log_progress("搜索树展开完成")
        if config.skip_final_summary:
            final_answer = ""
        else:
            final_answer = tree_final_summarize(question, root, all_evidence, config)
        tree_summary = render_tree_summary(root, config.node_summary_chars)
    finally:
        config.search_config.count = original_count
        config.search_config.max_search_results = original_max_results

    _log(config, "[tree] Done")
    return TreeSearchResult(
        question=question,
        root=root,
        final_answer=final_answer,
        evidence=all_evidence,
        tree_summary=tree_summary,
    )


def run_recursive_search(
    question: str,
    config: RecursiveSearchConfig,
) -> RecursiveSearchResult:
    """Run recursive Bocha search until enough evidence is collected."""
    _log(config, f"[workflow] Start recursive search: {question}")

    evidence: List[EvidenceItem] = []
    rounds: List[Dict[str, object]] = []
    seen_urls: set[str] = set()
    searched_queries: set[str] = set()
    pending_queries = [question][: config.initial_query_count]
    final_answer = ""

    original_count = config.search_config.count
    original_max_results = config.search_config.max_search_results

    try:
        config.search_config.count = config.results_per_query
        config.search_config.max_search_results = max(
            config.search_config.max_search_results,
            config.results_per_query,
        )

        for round_index in range(1, config.max_rounds + 1):
            if not pending_queries:
                _log(config, f"[round {round_index}] No pending queries, stopping")
                break

            _log(config, f"[round {round_index}] Queries: {pending_queries}")
            round_queries = pending_queries
            pending_queries = []

            round_new_items = []
            for query in round_queries:
                if query in searched_queries:
                    _log(config, f"[search-skip] Already searched: {query}")
                    continue
                searched_queries.add(query)

                _log(config, f"[search] Round {round_index}: {query}")
                search_runner = config.search_func or search
                results = search_runner(query, config.search_config)
                _log(config, f"[search] Results: {len(results)}")
                items = _dedupe_results(results, seen_urls, query, round_index)
                round_new_items.extend(items)
                evidence.extend(items)
                if len(evidence) >= config.max_evidence_items:
                    evidence = evidence[: config.max_evidence_items]
                    _log(config, "[evidence] Reached max evidence items")
                    break

            _log(config, f"[round {round_index}] New evidence items: {len(round_new_items)}")

            if round_index >= config.max_rounds or len(evidence) >= config.max_evidence_items:
                break

            try:
                decision = plan_next_queries(question, evidence, config, round_index)
            except Exception as exc:
                _log(config, f"[llm-plan] Failed to plan next queries, stopping recursion: {exc}")
                break

            rounds.append(
                {
                    "round": round_index,
                    "searched_queries": round_queries,
                    "new_evidence_count": len(round_new_items),
                    "decision": decision,
                }
            )
            _log(config, f"[llm-plan] Analysis: {decision.get('analysis', '')}")

            if not decision.get("need_more_search", True):
                final_answer = str(decision.get("final_answer", "") or "")
                _log(config, "[llm-plan] Model says evidence is sufficient")
                break

            next_queries = [
                query for query in decision.get("next_queries", []) if query not in searched_queries
            ]
            _log(config, f"[llm-plan] Next queries: {next_queries}")
            pending_queries = next_queries

        if not final_answer:
            final_answer = final_summarize(question, evidence, config)

    finally:
        config.search_config.count = original_count
        config.search_config.max_search_results = original_max_results

    _log(config, "[workflow] Done")
    return RecursiveSearchResult(
        question=question,
        evidence=evidence,
        final_answer=final_answer,
        rounds=rounds,
    )

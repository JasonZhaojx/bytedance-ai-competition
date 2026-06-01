"""证据结构化 Agent。

本节点只做“材料整理”，把上游 SearchResult/dict/object 统一成 SourceRecord，
再抽取 EvidenceCard。它不写报告，也不做最终事实检测；核心约束是所有 claim
必须能被 raw_excerpt 支撑。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional, Sequence, Tuple

try:
    from .batch_runner import run_parallel_batches
    from .chunking import chunk_by_json_size
    from .llm_utils import call_json_llm, clamp_confidence, clean_text
    from .models import EvidenceCard, SourceRecord, WritingAgentConfig
except ImportError:
    from report_agent.batch_runner import run_parallel_batches
    from report_agent.chunking import chunk_by_json_size
    from report_agent.llm_utils import call_json_llm, clamp_confidence, clean_text
    from report_agent.models import EvidenceCard, SourceRecord, WritingAgentConfig


DIMENSIONS = [
    "user_and_scenario",
    "task_completion",
    "agent_capability",
    "trust_and_control",
    "experience",
    "integration",
    "pricing_and_gtm",
    "moat",
    "user_feedback",
]


_DIMENSION_KEYWORDS = {
    "user_and_scenario": ["用户", "场景", "persona", "use case", "workflow", "团队"],
    "task_completion": ["任务", "执行", "规划", "自动化", "完成", "workflow"],
    "agent_capability": [
        "agent",
        "tool",
        "memory",
        "rag",
        "planning",
        "multi-agent",
        "模型",
    ],
    "trust_and_control": [
        "权限",
        "审计",
        "日志",
        "安全",
        "guardrail",
        "approval",
        "回滚",
    ],
    "experience": ["体验", "上手", "模板", "界面", "创建", "配置", "onboarding"],
    "integration": ["api", "mcp", "集成", "插件", "连接", "数据源", "slack", "github"],
    "pricing_and_gtm": ["价格", "定价", "订阅", "套餐", "enterprise", "收费", "销售"],
    "moat": ["生态", "壁垒", "分发", "数据", "平台", "marketplace", "community"],
    "user_feedback": ["评价", "吐槽", "反馈", "complaint", "review", "缺点", "问题"],
}


_IMPORTANCE = {
    "user_and_scenario": "帮助判断目标用户、使用频率和优先切入场景。",
    "task_completion": "影响产品是否能形成完整任务闭环。",
    "agent_capability": "影响 Agent 核心能力和技术差异化判断。",
    "trust_and_control": "影响企业客户是否敢授权 Agent 执行任务。",
    "experience": "影响首次使用、配置成本和激活转化。",
    "integration": "影响进入客户现有业务系统和数据流的能力。",
    "pricing_and_gtm": "影响商业化路径、目标客户和采购门槛。",
    "moat": "影响长期竞争壁垒和防御能力。",
    "user_feedback": "暴露未满足需求和产品机会点。",
}


def structure_evidence(
    search_results: Iterable[Any],
    config: WritingAgentConfig,
    *,
    analysis_goal: str,
    target_domain: str,
    competitors: Optional[Sequence[str]] = None,
) -> Tuple[List[SourceRecord], List[EvidenceCard]]:
    """标准化搜索结果并抽取证据卡。

    LLM 可用时优先让模型按 schema 抽取；模型不可用、关闭或返回格式不合法时，
    使用本地 fallback。这样测试环境和无网环境也能跑完整链路。
    """

    sources = normalize_search_results(search_results, config)
    if not sources:
        return [], []

    mode = getattr(config, "evidence_structurer_mode", 1)
    fallback_cards = _fallback_evidence_cards(
        sources, config, list(competitors or [])
    )
    if mode == 0:
        return sources, fallback_cards

    if mode == 1:
        cards = _cards_from_section_llm(
            sources=sources,
            config=config,
            analysis_goal=analysis_goal,
            target_domain=target_domain,
            competitors=list(competitors or []),
        )
    else:
        cards = _cards_from_llm(
            sources=sources,
            config=config,
            analysis_goal=analysis_goal,
            target_domain=target_domain,
            competitors=list(competitors or []),
        )

    if cards:
        return sources, _merge_evidence_cards(
            cards, fallback_cards, _evidence_limit(config)
        )
    return sources, fallback_cards


def _cards_from_section_llm(
    *,
    sources: List[SourceRecord],
    config: WritingAgentConfig,
    analysis_goal: str,
    target_domain: str,
    competitors: List[str],
) -> List[EvidenceCard]:
    """Use local heading extraction first, then let LLM normalize fields."""

    section_payload = []
    limit = _evidence_limit(config)
    for source in sources:
        text = source.content or source.snippet or source.title
        sections = _section_excerpts(text)
        if not sections:
            excerpt = _best_excerpt(text)
            if excerpt:
                sections = [(source.title, excerpt)]
        for heading, body in sections:
            excerpt = _best_excerpt(f"{heading}: {body}")
            if not excerpt:
                continue
            section_payload.append(
                {
                    "source_id": source.source_id,
                    "title": source.title,
                    "url": source.url,
                    "heading": heading,
                    "suggested_dimension": _dimension_from_heading(heading, body),
                    "excerpt": excerpt,
                }
            )
            if limit is not None and len(section_payload) >= limit * 2:
                break
        if limit is not None and len(section_payload) >= limit * 2:
            break

    if not section_payload:
        return []

    chunks = chunk_by_json_size(section_payload)
    if len(chunks) > 1:
        batch_results = run_parallel_batches(
            label="evidence sections",
            batches=chunks,
            config=config,
            worker=lambda batch: _cards_from_section_payload_llm(
                section_payload=batch,
                sources=sources,
                config=config,
                analysis_goal=analysis_goal,
                target_domain=target_domain,
                competitors=competitors,
            ),
        )
        return _renumber_evidence_cards(
            [card for batch in batch_results for card in batch],
            _evidence_limit(config),
        )

    return _cards_from_section_payload_llm(
        section_payload=section_payload,
        sources=sources,
        config=config,
        analysis_goal=analysis_goal,
        target_domain=target_domain,
        competitors=competitors,
    )


def _cards_from_section_payload_llm(
    *,
    section_payload: List[dict[str, Any]],
    sources: List[SourceRecord],
    config: WritingAgentConfig,
    analysis_goal: str,
    target_domain: str,
    competitors: List[str],
) -> List[EvidenceCard]:
    """Normalize one section-payload batch through the LLM."""

    limit = _evidence_limit(config)
    limit_text = f"最多 {limit} 张" if limit is not None else "尽可能完整抽取"
    data = call_json_llm(
        config=config,
        system_prompt="你是证据字段归一化助手，只输出 JSON，不写报告。",
        user_prompt=f"""
任务目标:
{analysis_goal}

分析领域:
{target_domain}

候选竞品:
{json.dumps(competitors, ensure_ascii=False)}

可选 dimension:
{json.dumps(DIMENSIONS, ensure_ascii=False)}

规则切片得到的原文片段:
{json.dumps(section_payload, ensure_ascii=False, indent=2)}

请把这些片段归一化为{limit_text} EvidenceCard。要求:
- 先判断 evidence_type：competitor_fact、user_context、implementation_detail、irrelevant。
- competitor_fact 才能作为竞品能力、定价、安全、集成、部署等事实；user_context 只能作为需求侧背景，competitor 必须为 null。
- implementation_detail 指 shell 命令、Dockerfile/build 脚本、安装日志、原始配置/代码片段；除非能明确概括成产品级能力，否则丢弃。
- irrelevant 必须丢弃。
- 你只做“结构翻译/字段归一化”，不要补充片段之外的新事实。
- competitor 尽量归属到候选竞品；如果是我方产品参数、问卷背景、行业共性信息，可以为 null。
- dimension 必须从可选 dimension 中选择；可参考 suggested_dimension，但可以纠正明显错误。
- claim 必须由 excerpt 直接支撑，写成简洁中文判断。
- raw_excerpt 必须完整保留或截取自 excerpt，不要改写成新文本。
- 如果片段只是目录、导航、链接堆砌或与任务无关，直接丢弃。
- 如果来源包含“我方产品参数关键词库”，只能把它作为对比维度线索，不能当作竞品事实。
- 如果来源包含“问卷分析补充背景”，只能作为需求侧/用户侧背景，不能当作某个竞品官方事实。
- 返回严格 JSON:
{{
  "evidence_cards": [
    {{
      "source_id": "src_001",
      "evidence_type": "competitor_fact|user_context|implementation_detail|irrelevant",
      "competitor": "竞品名或 null",
      "dimension": "user_and_scenario",
      "claim": "证据支持的判断",
      "raw_excerpt": "来自 excerpt 的原文片段",
      "confidence": 0.0,
      "freshness": "recent|older|unknown",
      "importance_for_pm": "对产品经理的价值"
    }}
  ]
}}
""".strip(),
    )
    if not isinstance(data, dict):
        return []

    source_by_id = {source.source_id: source for source in sources}
    allowed_sources = set(source_by_id)
    allowed_excerpts: dict[str, list[str]] = {}
    for item in section_payload:
        allowed_excerpts.setdefault(item["source_id"], []).append(item["excerpt"])
    cards: List[EvidenceCard] = []
    limit = _evidence_limit(config)
    for raw in data.get("evidence_cards", []):
        if not isinstance(raw, dict):
            continue
        source_id = str(raw.get("source_id") or "").strip()
        if source_id not in allowed_sources:
            continue
        claim = clean_text(raw.get("claim"), 260)
        excerpt = clean_text(raw.get("raw_excerpt"), 420)
        if not claim or not excerpt:
            continue
        original_excerpts = allowed_excerpts.get(source_id, [])
        if original_excerpts and not any(excerpt in item for item in original_excerpts):
            excerpt = _best_supported_excerpt(excerpt, original_excerpts)
        if not excerpt:
            continue
        dimension = str(raw.get("dimension") or "").strip()
        if dimension not in DIMENSIONS:
            dimension = classify_dimension(f"{claim} {excerpt}")
        evidence_type = _evidence_type(raw, source_by_id[source_id], claim, excerpt)
        if evidence_type in {"irrelevant", "implementation_detail"}:
            continue
        competitor = _normalize_competitor(
            raw.get("competitor"),
            source_by_id[source_id],
            competitors,
            allow_competitor=evidence_type == "competitor_fact",
        )
        cards.append(
            EvidenceCard(
                evidence_id=f"ev_{len(cards) + 1:03d}",
                source_id=source_id,
                competitor=competitor,
                dimension=dimension,
                claim=claim,
                raw_excerpt=excerpt,
                confidence=clamp_confidence(raw.get("confidence"), 0.76),
                freshness=clean_text(raw.get("freshness"), 40) or "unknown",
                importance_for_pm=clean_text(raw.get("importance_for_pm"), 220)
                or importance_for_dimension(dimension),
            )
        )
        if limit is not None and len(cards) >= limit:
            break
    return cards


def _best_supported_excerpt(candidate: str, originals: Sequence[str]) -> str:
    """Pull a model-normalized excerpt back to the nearest original section."""

    candidate = clean_text(candidate, 420)
    if not candidate:
        return ""
    for original in originals:
        if candidate in original:
            return candidate

    compact_candidate = re.sub(r"\s+", "", candidate)
    for original in originals:
        compact_original = re.sub(r"\s+", "", original)
        if compact_candidate and compact_candidate in compact_original:
            return clean_text(original, 420)

    candidate_terms = [
        term
        for term in re.split(r"[，。；、,.;:\s]+", candidate)
        if len(term) >= 2
    ]
    best_original = ""
    best_score = 0
    for original in originals:
        score = sum(1 for term in candidate_terms if term in original)
        if score > best_score:
            best_score = score
            best_original = original
    if best_original and best_score:
        return clean_text(best_original, 420)
    return clean_text(originals[0] if originals else "", 420)


def normalize_search_results(
    search_results: Iterable[Any],
    config: WritingAgentConfig,
) -> List[SourceRecord]:
    """把上游各种结果对象归一化成 SourceRecord。

    这里做去重、正文截断和 source_id 分配。source_id 是后续 evidence、claim
    和报告引用的根，因此必须在进入链路最开始就稳定生成。
    """

    records: List[SourceRecord] = []
    seen_urls: set[str] = set()
    retrieved_at = datetime.now(timezone.utc).isoformat()

    for index, item in enumerate(search_results, 1):
        title = clean_text(_value(item, "title"), 240)
        url = clean_text(_value(item, "url"), 600)
        snippet = clean_text(_value(item, "snippet"), 1200)
        content = _clean_source_content(
            _value(item, "content") or snippet, config.max_source_chars
        )
        normalized_url = url.split("#", 1)[0].rstrip("/")
        if normalized_url and normalized_url in seen_urls:
            continue
        if normalized_url:
            seen_urls.add(normalized_url)

        record = SourceRecord(
            source_id=f"src_{len(records) + 1:03d}",
            title=title or f"Source {index}",
            url=url,
            snippet=snippet,
            content=content,
            source=clean_text(_value(item, "source"), 80),
            content_source=clean_text(_value(item, "content_source"), 120),
            publish_date=_extract_publish_date(snippet),
            retrieved_at=retrieved_at,
            credibility_score=_float_or_none(_value(item, "credibility_score")),
        )
        records.append(record)
        if config.max_prompt_sources > 0 and len(records) >= config.max_prompt_sources:
            break
    return records


def _cards_from_llm(
    *,
    sources: List[SourceRecord],
    config: WritingAgentConfig,
    analysis_goal: str,
    target_domain: str,
    competitors: List[str],
) -> List[EvidenceCard]:
    """使用 LLM 抽取 evidence cards，并做本地 schema 校验。

    即便 LLM 返回了 JSON，也要过滤未知 source_id、空 claim、空 excerpt 和
    非法 dimension，避免把不可追溯内容传给下游。
    """

    source_payload = _source_prompt_payload(sources)
    chunks = chunk_by_json_size(source_payload)
    if len(chunks) > 1:
        source_by_id = {source.source_id: source for source in sources}
        batch_results = run_parallel_batches(
            label="evidence sources",
            batches=chunks,
            config=config,
            worker=lambda batch: _cards_from_source_payload_llm(
                source_payload=batch,
                source_by_id=source_by_id,
                config=config,
                analysis_goal=analysis_goal,
                target_domain=target_domain,
                competitors=competitors,
            ),
        )
        return _renumber_evidence_cards(
            [card for batch in batch_results for card in batch],
            _evidence_limit(config),
        )

    return _cards_from_source_payload_llm(
        source_payload=source_payload,
        source_by_id={source.source_id: source for source in sources},
        config=config,
        analysis_goal=analysis_goal,
        target_domain=target_domain,
        competitors=competitors,
    )


def _source_prompt_payload(sources: List[SourceRecord]) -> List[dict[str, Any]]:
    return [
        {
            "source_id": source.source_id,
            "title": source.title,
            "url": source.url,
            "snippet": source.snippet,
            "content": source.content,
            "publish_date": source.publish_date,
        }
        for source in sources
    ]


def _cards_from_source_payload_llm(
    *,
    source_payload: List[dict[str, Any]],
    source_by_id: dict[str, SourceRecord],
    config: WritingAgentConfig,
    analysis_goal: str,
    target_domain: str,
    competitors: List[str],
) -> List[EvidenceCard]:
    """Extract EvidenceCard objects from one source-payload batch."""

    limit = _evidence_limit(config)
    limit_text = f"最多 {limit} 张" if limit is not None else "尽可能完整抽取"
    data = call_json_llm(
        config=config,
        system_prompt="你是证据结构化助手，只输出 JSON，不写报告。",
        user_prompt=f"""
任务目标:
{analysis_goal}

分析领域:
{target_domain}

候选竞品:
{json.dumps(competitors, ensure_ascii=False)}

可选 dimension:
{json.dumps(DIMENSIONS, ensure_ascii=False)}

搜索来源:
{json.dumps(source_payload, ensure_ascii=False, indent=2)}

请从来源中{limit_text}证据卡。要求:
- 先判断 evidence_type：competitor_fact、user_context、implementation_detail、irrelevant。
- competitor_fact 才能作为竞品能力、定价、安全、集成、部署等事实；user_context 只能作为需求侧背景，competitor 必须为 null。
- implementation_detail 指 shell 命令、Dockerfile/build 脚本、安装日志、原始配置/代码片段；除非能明确概括成产品级能力，否则丢弃。
- irrelevant 必须丢弃。
- 如果来源中包含“我方产品参数关键词库”或“已知产品参数关键词库”，必须理解为用户自己的产品/我方产品基准参数，不是竞品参数；只能把其中参数点作为共同对比维度线索，优先抽取竞品资料中能支撑或否定这些参数点的证据。
- 如果来源中包含“问卷分析补充背景”，要抽取用户画像、场景优先级、价格敏感度、替换意愿、采购顾虑、风险偏好等需求侧证据；这类证据 competitor 可以为 null，不能当作某个竞品官方事实。
- 每张卡只表达一个 claim。
- claim 必须能被 raw_excerpt 直接支撑。
- competitor 尽量归属到候选竞品；如果是用户需求、问卷背景或行业共性信息，可以为 null。
- 不要引入来源中没有的信息。
- 返回严格 JSON:
{{
  "evidence_cards": [
    {{
      "source_id": "src_001",
      "evidence_type": "competitor_fact|user_context|implementation_detail|irrelevant",
      "competitor": "竞品名或 null",
      "dimension": "user_and_scenario",
      "claim": "证据支持的判断",
      "raw_excerpt": "原文片段",
      "confidence": 0.0,
      "freshness": "recent|older|unknown",
      "importance_for_pm": "对产品经理的价值"
    }}
  ]
}}
""".strip(),
    )
    if not isinstance(data, dict):
        return []

    allowed_sources = set(source_by_id)
    cards: List[EvidenceCard] = []
    for raw in data.get("evidence_cards", []):
        if not isinstance(raw, dict):
            continue
        source_id = str(raw.get("source_id") or "").strip()
        if source_id not in allowed_sources:
            continue
        claim = clean_text(raw.get("claim"), 260)
        excerpt = clean_text(raw.get("raw_excerpt"), 420)
        if not claim or not excerpt:
            continue
        dimension = str(raw.get("dimension") or "").strip()
        if dimension not in DIMENSIONS:
            dimension = classify_dimension(f"{claim} {excerpt}")
        evidence_type = _evidence_type(raw, source_by_id[source_id], claim, excerpt)
        if evidence_type in {"irrelevant", "implementation_detail"}:
            continue
        competitor = _normalize_competitor(
            raw.get("competitor"),
            source_by_id[source_id],
            competitors,
            allow_competitor=evidence_type == "competitor_fact",
        )
        cards.append(
            EvidenceCard(
                evidence_id=f"ev_{len(cards) + 1:03d}",
                source_id=source_id,
                competitor=competitor,
                dimension=dimension,
                claim=claim,
                raw_excerpt=excerpt,
                confidence=clamp_confidence(raw.get("confidence"), 0.72),
                freshness=clean_text(raw.get("freshness"), 40) or "unknown",
                importance_for_pm=clean_text(raw.get("importance_for_pm"), 220)
                or importance_for_dimension(dimension),
            )
        )
        if limit is not None and len(cards) >= limit:
            break
    return cards


def _fallback_evidence_cards(
    sources: List[SourceRecord],
    config: WritingAgentConfig,
    competitors: List[str],
) -> List[EvidenceCard]:
    """离线证据抽取。

    fallback 不追求复杂推理，只保证每个来源至少能产出一条可追溯 claim，
    让后续模块和测试可以稳定验证完整流程。
    """

    cards: List[EvidenceCard] = []
    limit = _evidence_limit(config)
    for source in sources:
        text = source.content or source.snippet or source.title
        for excerpt, dimension in _evidence_excerpts_from_source(source, text):
            if not excerpt:
                continue
            claim = _claim_from_excerpt(source.title, excerpt)
            if is_low_value_evidence_text(claim, excerpt):
                continue
            cards.append(
                EvidenceCard(
                    evidence_id=f"ev_{len(cards) + 1:03d}",
                    source_id=source.source_id,
                    competitor=_normalize_competitor(
                        infer_competitor(f"{source.title} {excerpt}", competitors),
                        source,
                        competitors,
                        allow_competitor=not _is_context_source(source),
                    ),
                    dimension=dimension,
                    claim=claim,
                    raw_excerpt=excerpt,
                    confidence=_fallback_confidence(source),
                    freshness=_freshness_from_date(source.publish_date),
                    importance_for_pm=importance_for_dimension(dimension),
                )
            )
            if limit is not None and len(cards) >= limit:
                return cards
    return cards


def _clean_source_content(value: Any, max_chars: int) -> str:
    text = "" if value is None else str(value)
    text = text.replace("[tree-final] Generating final answer from reference evidence", "")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text


def _evidence_excerpts_from_source(
    source: SourceRecord, text: str
) -> List[Tuple[str, str]]:
    sections = _section_excerpts(text)
    if not sections:
        excerpt = _best_excerpt(text)
        return [(excerpt, classify_dimension(f"{source.title} {excerpt}"))] if excerpt else []

    results: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for heading, body in sections:
        dimension = _dimension_from_heading(heading, body)
        excerpt = _best_excerpt(f"{heading}: {body}")
        if not excerpt:
            continue
        key = re.sub(r"\s+", "", excerpt)[:100]
        if key in seen:
            continue
        seen.add(key)
        results.append((excerpt, dimension))
    return results


def _section_excerpts(text: str) -> List[Tuple[str, str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    sections: List[Tuple[str, str]] = []
    current_heading = ""
    current_body: List[str] = []

    def flush() -> None:
        nonlocal current_body, current_heading
        if current_heading and current_body:
            body = clean_text(" ".join(current_body), 900)
            if body:
                sections.append((current_heading, body))
        current_body = []

    for line in lines:
        heading_match = re.match(r"^(#{1,4})\s*(.+)$", line)
        list_heading_match = re.match(r"^\d+[.、]\s*\*\*([^*：:]+)\*\*[：:]\s*(.*)$", line)
        bold_heading_match = re.match(r"^\*\*([^*：:]+)\*\*[：:]\s*(.*)$", line)
        colon_heading_match = re.match(
            r"^(产品定位|目标用户|核心场景|产品形态/入口|产品形态|商业模式/定价|商业模式|集成生态|限制或风险|用户反馈|特色AI功能矩阵|企业级部署与合规能力|全版本定价体系|计费规则|内置支持大模型清单|新用户试用福利)[：:]\s*(.*)$",
            line,
        )
        if heading_match:
            flush()
            current_heading = clean_text(heading_match.group(2), 120)
            continue
        if list_heading_match:
            flush()
            current_heading = clean_text(list_heading_match.group(1), 120)
            rest = list_heading_match.group(2).strip()
            current_body = [rest] if rest else []
            continue
        if bold_heading_match:
            flush()
            current_heading = clean_text(bold_heading_match.group(1), 120)
            rest = bold_heading_match.group(2).strip()
            current_body = [rest] if rest else []
            continue
        if colon_heading_match:
            flush()
            current_heading = clean_text(colon_heading_match.group(1), 120)
            rest = colon_heading_match.group(2).strip()
            current_body = [rest] if rest else []
            continue
        if current_heading:
            current_body.append(line)

    flush()
    return _prioritize_sections(sections)


def _prioritize_sections(sections: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    priority = [
        "产品定位",
        "目标用户",
        "核心场景",
        "产品形态",
        "商业模式",
        "定价",
        "计费",
        "特色AI功能",
        "能力",
        "集成生态",
        "企业级部署",
        "合规",
        "限制",
        "风险",
        "用户反馈",
    ]

    def score(item: Tuple[str, str]) -> int:
        heading = item[0]
        for index, keyword in enumerate(priority):
            if keyword in heading:
                return index
        return len(priority)

    return sorted(sections, key=score)


def _dimension_from_heading(heading: str, body: str) -> str:
    text = f"{heading} {body}"
    if any(key in heading for key in ["目标用户", "核心场景", "产品定位"]):
        return "user_and_scenario"
    if any(key in heading for key in ["定价", "计费", "商业模式", "试用"]):
        return "pricing_and_gtm"
    if any(key in heading for key in ["产品形态", "入口", "上手", "迁移门槛"]):
        return "experience"
    if any(key in heading for key in ["特色AI功能", "能力", "模型", "代码"]):
        return "agent_capability"
    if any(key in heading for key in ["集成", "生态", "MCP", "API"]):
        return "integration"
    if any(key in heading for key in ["部署", "合规", "安全", "权限"]):
        return "trust_and_control"
    if any(key in heading for key in ["限制", "风险"]):
        return "trust_and_control"
    if "用户反馈" in heading:
        return "user_feedback"
    return classify_dimension(text)


def _merge_evidence_cards(
    primary: List[EvidenceCard], fallback: List[EvidenceCard], limit: int
) -> List[EvidenceCard]:
    return _renumber_evidence_cards(primary + fallback, limit)


def _renumber_evidence_cards(
    cards: List[EvidenceCard], limit: Optional[int]
) -> List[EvidenceCard]:
    merged: List[EvidenceCard] = []
    seen: set[tuple[str, str, str]] = set()
    for card in cards:
        key = (
            card.source_id,
            card.dimension,
            re.sub(r"\s+", "", card.raw_excerpt)[:120],
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(card)
        if limit is not None and len(merged) >= limit:
            break
    for index, card in enumerate(merged, 1):
        card.evidence_id = f"ev_{index:03d}"
    return merged


def _evidence_limit(config: WritingAgentConfig) -> Optional[int]:
    if config.max_evidence_cards and config.max_evidence_cards > 0:
        return config.max_evidence_cards
    return None


def classify_dimension(text: str) -> str:
    """用关键词把证据粗分到 PM 分析维度。"""

    lowered = text.lower()
    for dimension, keywords in _DIMENSION_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            return dimension
    return "agent_capability"


def importance_for_dimension(dimension: str) -> str:
    return _IMPORTANCE.get(dimension, "帮助产品经理把资料转化为可行动判断。")


def infer_competitor(text: str, competitors: Sequence[str]) -> Optional[str]:
    """从文本中推断竞品归属。

    优先使用外部传入的竞品名；没有命中时再使用标题前缀作为弱推断。
    """

    lowered = text.lower()
    for competitor in competitors:
        if competitor and competitor.lower() in lowered:
            return competitor

    title_part = re.split(r"[-_|｜:：]", clean_text(text, 120), maxsplit=1)[0].strip()
    if 1 < len(title_part) <= 60:
        return title_part
    return None


def _evidence_type(
    raw: dict[str, Any],
    source: SourceRecord,
    claim: str,
    excerpt: str,
) -> str:
    value = clean_text(raw.get("evidence_type"), 80).lower()
    if value in {
        "competitor_fact",
        "user_context",
        "implementation_detail",
        "irrelevant",
    }:
        evidence_type = value
    elif _is_context_source(source):
        evidence_type = "user_context"
    elif is_low_value_evidence_text(claim, excerpt):
        evidence_type = "implementation_detail"
    else:
        evidence_type = "competitor_fact"
    if evidence_type == "competitor_fact" and _is_context_source(source):
        return "user_context"
    return evidence_type


def _normalize_competitor(
    value: Any,
    source: SourceRecord,
    competitors: Sequence[str],
    *,
    allow_competitor: bool = True,
) -> Optional[str]:
    if not allow_competitor or _is_context_source(source):
        return None
    text = clean_text(value, 120)
    if text:
        for competitor in competitors:
            if competitor and text.lower() == competitor.lower():
                return competitor
        inferred = infer_competitor(text, competitors)
        if inferred:
            return inferred
    return infer_competitor(f"{source.title} {source.snippet}", competitors)


def _is_context_source(source: SourceRecord) -> bool:
    text = f"{source.title} {source.source} {source.content_source}".lower()
    markers = [
        "用户需求",
        "参数词库",
        "问卷",
        "known_params",
        "questionnaire",
        "workflow_context",
    ]
    return any(marker.lower() in text for marker in markers)


def is_low_value_evidence_text(claim: str, excerpt: str) -> bool:
    text = f"{claim}\n{excerpt}"
    lowered = text.lower()
    command_markers = [
        "curl ",
        "chmod ",
        "dockerfile",
        "docker build",
        "docker run",
        "npm install",
        "pip install",
        "apt-get",
        "yum install",
        "brew install",
        "powershell",
        "run ",
        "copy ",
        "workdir",
        "entrypoint",
        "#!/bin/",
        "$home/",
        ".opencode/bin",
        "/brainstorm",
        "/write-plan",
        "required sub-skill",
        "def ",
        "python运行",
        "ctrl + enter",
        "generate code from context",
        "flask rest api",
        "quicksort",
    ]
    tutorial_markers = [
        "安装 oh-my",
        "install and configure",
        "following the instructions",
        "raw.githubusercontent.com",
        "体验ai代码助手",
        "代码解读复制代码",
        "开发流程总览",
        "阶段一",
        "阶段二",
        "技术方案模板",
        "openspec",
        "brainstorming 流程",
        "实际应用案例",
        "案例演示",
        "实现一个",
        "输入以下注释",
        "稍等片刻",
        "自动弹出补全建议",
        "点击接受",
        "命令面板",
        "快捷键",
        "右键菜单",
    ]
    command_hits = sum(1 for marker in command_markers if marker in lowered)
    tutorial_hits = sum(1 for marker in tutorial_markers if marker in lowered)
    code_like_chars = sum(text.count(char) for char in "{}[]`$\\")
    if tutorial_hits >= 2:
        return True
    if tutorial_hits >= 1 and command_hits >= 1:
        return True
    if command_hits >= 2:
        return True
    if command_hits >= 1 and code_like_chars >= 4:
        return True
    if len(text) > 180 and code_like_chars / max(len(text), 1) > 0.06:
        return True
    return False


def _value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _float_or_none(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_publish_date(snippet: str) -> Optional[str]:
    match = re.search(r"(?:^|\n)date:\s*([^\n]+)", snippet, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _best_excerpt(text: str) -> str:
    """选取能支撑 claim 的短片段。"""

    cleaned = clean_text(text)
    if not cleaned:
        return ""
    no_truncate = os.getenv("REPORT_AGENT_NO_TRUNCATE", "1").strip().lower()
    if no_truncate not in {"0", "false", "no", "off"}:
        return cleaned
    sentences = re.split(r"(?<=[。！？.!?])\s+", cleaned)
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) >= 24:
            return sentence[:420].rstrip()
    return cleaned[:420].rstrip()


def _claim_from_excerpt(title: str, excerpt: str) -> str:
    title = clean_text(title, 80)
    excerpt = clean_text(excerpt, 160)
    if ":" in excerpt:
        heading, body = excerpt.split(":", 1)
        heading = clean_text(heading, 60)
        body = clean_text(body, 160)
        if heading and body:
            return f"{heading}: {body}"
    if title:
        return f"{title} 的资料显示：{excerpt}"
    return excerpt


def _fallback_confidence(source: SourceRecord) -> float:
    if source.content and source.content_source != "搜索摘要":
        return 0.72
    return 0.58


def _freshness_from_date(value: Optional[str]) -> str:
    if not value:
        return "unknown"
    match = re.search(r"(20\d{2})", value)
    if not match:
        return "unknown"
    year = int(match.group(1))
    current_year = datetime.now().year
    return "recent" if year >= current_year - 2 else "older"

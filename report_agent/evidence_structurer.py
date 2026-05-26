"""证据结构化 Agent。

本节点只做“材料整理”，把上游 SearchResult/dict/object 统一成 SourceRecord，
再抽取 EvidenceCard。它不写报告，也不做最终事实检测；核心约束是所有 claim
必须能被 raw_excerpt 支撑。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional, Sequence, Tuple

try:
    from .llm_utils import call_json_llm, clamp_confidence, clean_text
    from .models import EvidenceCard, SourceRecord, WritingAgentConfig
except ImportError:
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

    cards = _cards_from_llm(
        sources=sources,
        config=config,
        analysis_goal=analysis_goal,
        target_domain=target_domain,
        competitors=list(competitors or []),
    )
    if cards:
        return sources, cards
    return sources, _fallback_evidence_cards(sources, config, list(competitors or []))


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
        content = clean_text(
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
        if len(records) >= config.max_prompt_sources:
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

    source_payload = [
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

请从来源中抽取最多 {config.max_evidence_cards} 张证据卡。要求:
- 每张卡只表达一个 claim。
- claim 必须能被 raw_excerpt 直接支撑。
- 不要引入来源中没有的信息。
- 返回严格 JSON:
{{
  "evidence_cards": [
    {{
      "source_id": "src_001",
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

    allowed_sources = {source.source_id for source in sources}
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
        competitor = clean_text(raw.get("competitor"), 120) or None
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
        if len(cards) >= config.max_evidence_cards:
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
    for source in sources:
        text = source.content or source.snippet or source.title
        excerpt = _best_excerpt(text)
        if not excerpt:
            continue
        dimension = classify_dimension(f"{source.title} {excerpt}")
        cards.append(
            EvidenceCard(
                evidence_id=f"ev_{len(cards) + 1:03d}",
                source_id=source.source_id,
                competitor=infer_competitor(f"{source.title} {excerpt}", competitors),
                dimension=dimension,
                claim=_claim_from_excerpt(source.title, excerpt),
                raw_excerpt=excerpt,
                confidence=_fallback_confidence(source),
                freshness=_freshness_from_date(source.publish_date),
                importance_for_pm=importance_for_dimension(dimension),
            )
        )
        if len(cards) >= config.max_evidence_cards:
            break
    return cards


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

    cleaned = clean_text(text, 900)
    if not cleaned:
        return ""
    sentences = re.split(r"(?<=[。！？.!?])\s+", cleaned)
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) >= 24:
            return sentence[:420].rstrip()
    return cleaned[:420].rstrip()


def _claim_from_excerpt(title: str, excerpt: str) -> str:
    title = clean_text(title, 80)
    excerpt = clean_text(excerpt, 160)
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

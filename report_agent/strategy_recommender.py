"""产品策略建议 Agent。

本节点把分析结论转成可执行建议，默认使用 30/60/90 天路线图结构。建议仍然
保留 evidence_ids，方便下游检查建议是否有证据基础。
"""

from __future__ import annotations

import json
import re
from typing import Any, List

try:
    from .batch_runner import run_parallel_batches
    from .chunking import chunk_evidence_cards, evidence_prompt_payload
    from .llm_utils import call_json_llm, clean_text, valid_ids
    from .models import (
        EvidenceCard,
        PMInsight,
        ProductRecommendation,
        SWOTResult,
        WritingAgentConfig,
    )
except ImportError:
    from report_agent.batch_runner import run_parallel_batches
    from report_agent.chunking import chunk_evidence_cards, evidence_prompt_payload
    from report_agent.llm_utils import call_json_llm, clean_text, valid_ids
    from report_agent.models import (
        EvidenceCard,
        PMInsight,
        ProductRecommendation,
        SWOTResult,
        WritingAgentConfig,
    )


PRIORITIES = ["P0", "P1", "P2"]
TIMEFRAMES = ["30_days", "60_days", "90_days"]


def _default_timeframe(index: int) -> str:
    return TIMEFRAMES[index % len(TIMEFRAMES)]


def _normalize_timeframe(value: Any, index: int) -> str:
    text = str(value or "").strip()
    lowered = text.lower().replace("-", "_").replace(" ", "_")
    if lowered in TIMEFRAMES:
        return lowered
    compact = re.sub(r"[\s_\-]+", "", lowered)
    if compact in {"30days", "day30", "30d", "0to30days"}:
        return "30_days"
    if compact in {"60days", "day60", "60d", "31to60days"}:
        return "60_days"
    if compact in {"90days", "day90", "90d", "61to90days"}:
        return "90_days"
    if re.search(r"(^|[^0-9])30([^0-9]|$)", text) or any(
        marker in text for marker in ("30天", "30日", "一月", "一个月", "短期", "近期")
    ):
        return "30_days"
    if re.search(r"(^|[^0-9])60([^0-9]|$)", text) or any(
        marker in text for marker in ("60天", "60日", "两月", "两个月", "二月", "中期")
    ):
        return "60_days"
    if re.search(r"(^|[^0-9])90([^0-9]|$)", text) or any(
        marker in text for marker in ("90天", "90日", "三月", "三个月", "长期", "远期")
    ):
        return "90_days"
    return _default_timeframe(index)


def _rebalance_timeframes(
    recommendations: List[ProductRecommendation],
) -> List[ProductRecommendation]:
    if len(recommendations) < 2:
        return recommendations
    present = {rec.timeframe for rec in recommendations}
    if len(present) >= min(len(recommendations), len(TIMEFRAMES)):
        return recommendations
    for index, rec in enumerate(recommendations):
        if index >= len(TIMEFRAMES):
            break
        rec.timeframe = TIMEFRAMES[index]
    return recommendations


def generate_recommendations(
    evidence_cards: List[EvidenceCard],
    pm_insights: List[PMInsight],
    swot: SWOTResult,
    config: WritingAgentConfig,
) -> List[ProductRecommendation]:
    """基于 evidence、insight 和 SWOT 生成产品策略建议。"""

    if not evidence_cards:
        return []
    recommendations = _recommendations_from_llm(
        evidence_cards, pm_insights, swot, config
    )
    if recommendations:
        return recommendations
    return _fallback_recommendations(evidence_cards, pm_insights, swot)


def _recommendations_from_llm(
    evidence_cards: List[EvidenceCard],
    pm_insights: List[PMInsight],
    swot: SWOTResult,
    config: WritingAgentConfig,
) -> List[ProductRecommendation]:
    """使用 LLM 生成路线图建议，并校验证据绑定和枚举值。"""

    chunks = chunk_evidence_cards(evidence_cards)
    if len(chunks) > 1:
        merged: List[ProductRecommendation] = []
        batch_results = run_parallel_batches(
            label="recommendations",
            batches=chunks,
            config=config,
            worker=lambda cards: _recommendations_from_llm(
                    cards,
                    _insights_for_cards(pm_insights, cards),
                    swot,
                    config,
            ),
        )
        for recommendations in batch_results:
            merged.extend(recommendations)
        return _dedupe_recommendations(merged)

    data = call_json_llm(
        config=config,
        system_prompt="你是产品策略顾问，只输出 JSON。",
        user_prompt=f"""
Evidence Cards:
{json.dumps(evidence_prompt_payload(evidence_cards), ensure_ascii=False, indent=2)}

PM Insights:
{json.dumps([insight.to_dict() for insight in pm_insights], ensure_ascii=False, indent=2)}

SWOT:
{json.dumps(swot.to_dict(), ensure_ascii=False, indent=2)}

请生成 30/60/90 天产品策略建议。要求:
- 每条建议有 priority, timeframe, action, reason, expected_impact, risk, evidence_ids, success_metric。
- evidence_ids 必须来自输入。
- 我方产品参数词库或已知产品参数词库是路线图的共同对齐清单：它来自用户自己的产品/我方产品，不是竞品事实；建议中要体现哪些参数需要优先补证、对标、验证或形成差异化。
- 问卷分析是用户需求和商业决策校准依据：建议中要回应用户画像、场景优先级、价格敏感度、替换意愿、采购顾虑和风险偏好。
- 如果问卷与竞品资料出现张力，例如用户很关注价格但竞品定价证据缺失，要把它转化为验证任务或风险项。
- 返回严格 JSON:
{{"recommendations": []}}
""".strip(),
    )
    if not isinstance(data, dict):
        return []
    raw_items = data.get("recommendations")
    if not isinstance(raw_items, list):
        return []

    allowed = {card.evidence_id for card in evidence_cards}
    recommendations: List[ProductRecommendation] = []
    for raw_index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            continue
        evidence_ids = valid_ids(raw.get("evidence_ids"), allowed)
        if not evidence_ids:
            continue
        priority = str(raw.get("priority") or "").strip()
        if priority not in PRIORITIES:
            priority = "P1"
        timeframe = _normalize_timeframe(raw.get("timeframe"), raw_index)
        action = clean_text(raw.get("action"), 220)
        reason = clean_text(raw.get("reason"), 260)
        if not action or not reason:
            continue
        recommendations.append(
            ProductRecommendation(
                priority=priority,
                timeframe=timeframe,
                action=action,
                reason=reason,
                expected_impact=clean_text(raw.get("expected_impact"), 220)
                or "提升产品决策质量和报告可采纳率。",
                risk=clean_text(raw.get("risk"), 220)
                or "证据覆盖不足会影响判断准确性。",
                evidence_ids=evidence_ids,
                success_metric=clean_text(raw.get("success_metric"), 180)
                or "任务完成率、证据覆盖率、报告采纳率",
            )
        )
    return _rebalance_timeframes(recommendations)


def _insights_for_cards(
    pm_insights: List[PMInsight], evidence_cards: List[EvidenceCard]
) -> List[PMInsight]:
    allowed = {card.evidence_id for card in evidence_cards}
    return [
        insight
        for insight in pm_insights
        if any(evidence_id in allowed for evidence_id in insight.evidence_ids)
    ]


def _dedupe_recommendations(
    recommendations: List[ProductRecommendation],
) -> List[ProductRecommendation]:
    deduped: List[ProductRecommendation] = []
    seen: set[tuple[str, str, str]] = set()
    for rec in recommendations:
        key = (rec.priority, rec.timeframe, rec.action)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(rec)
    return _rebalance_timeframes(deduped)


def _fallback_recommendations(
    evidence_cards: List[EvidenceCard],
    pm_insights: List[PMInsight],
    swot: SWOTResult,
) -> List[ProductRecommendation]:
    """离线生成固定 30/60/90 天路线图。

    这些建议是保守默认值，重点服务于流程验证和报告结构完整；真实场景可由
    LLM 或人工 PM 根据更多证据细化。
    """

    del swot
    all_ids = [card.evidence_id for card in evidence_cards]
    first_ids = all_ids[:4] or []
    insight_title = (
        pm_insights[0].title if pm_insights else "现有证据显示应优先验证核心场景"
    )
    return [
        ProductRecommendation(
            priority="P0",
            timeframe="30_days",
            action="验证 1-2 个高频、高价值、结果可验证的 Agent 竞品分析场景",
            reason=insight_title,
            expected_impact="明确产品切入点，减少通用 Agent 定位过宽导致的价值稀释。",
            risk="场景选择过宽会导致评测集和产品价值都不清晰。",
            evidence_ids=first_ids,
            success_metric="任务完成率、报告采纳率、人工修正率",
        ),
        ProductRecommendation(
            priority="P1",
            timeframe="60_days",
            action="补齐证据溯源、人审确认、执行日志和结果回放能力",
            reason="竞品分析报告需要被下游检测和业务用户信任。",
            expected_impact="提升报告可信度，并为质检 Agent 提供可验证输入。",
            risk="只优化生成效果但缺少溯源，会降低 PM 采用意愿。",
            evidence_ids=first_ids,
            success_metric="证据覆盖率、低置信度结论占比、质检通过率",
        ),
        ProductRecommendation(
            priority="P2",
            timeframe="90_days",
            action="沉淀行业模板、对比维度库和稳定评测数据集",
            reason="长期竞争需要从一次性报告生成升级为可复用的决策工作流。",
            expected_impact="提高跨行业复用效率，形成产品方法论和数据壁垒。",
            risk="模板过早固化可能遮蔽新兴场景和用户反馈。",
            evidence_ids=first_ids,
            success_metric="模板复用率、行业覆盖数、报告复跑一致性",
        ),
    ]

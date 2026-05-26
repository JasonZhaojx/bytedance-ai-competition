"""报告包轻量自检。

这里不替代下游质检 Agent，只做结构完整性检查：章节是否齐、claim 是否能回溯
到 evidence/source、SWOT 是否绑定证据。
"""

from __future__ import annotations

try:
    from .models import ReportState
except ImportError:
    from report_agent.models import ReportState


REQUIRED_SECTIONS = [
    "核心结论",
    "竞品分类",
    "用户场景",
    "重点竞品拆解",
    "横向能力对比",
    "SWOT",
    "产品策略建议",
    "资料来源",
]


def precheck_report_package(state: ReportState) -> ReportState:
    """检查 ReportState 的基本完整性并写回风险列表。"""

    report = state.report_markdown or ""
    for section in REQUIRED_SECTIONS:
        message = f"报告缺少章节：{section}"
        if section not in report and message not in state.missing_info:
            state.missing_info.append(message)

    evidence_ids = {card.evidence_id for card in state.evidence_cards}
    source_ids = {source.source_id for source in state.sources}

    for item in state.claim_evidence_map:
        claim = item.get("claim", "")
        mapped_evidence_ids = item.get("evidence_ids", [])
        mapped_source_ids = item.get("source_ids", [])
        if not mapped_evidence_ids or not set(mapped_evidence_ids).issubset(
            evidence_ids
        ):
            _append_unique(state.low_confidence_claims, claim)
        if not mapped_source_ids or not set(mapped_source_ids).issubset(source_ids):
            _append_unique(state.low_confidence_claims, claim)
        if item.get("confidence", 1.0) < 0.6:
            _append_unique(state.low_confidence_claims, claim)

    swot_items = (
        state.swot.strengths
        + state.swot.weaknesses
        + state.swot.opportunities
        + state.swot.threats
    )
    for item in swot_items:
        if not item.evidence_ids or not set(item.evidence_ids).issubset(evidence_ids):
            _append_unique(state.low_confidence_claims, item.point)

    return state


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)

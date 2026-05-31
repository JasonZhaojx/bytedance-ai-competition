"""报告撰写 Agent。

Composer 只负责表达，把结构化分析渲染为 Markdown。它不重新搜索、不重新推理，
也不新增 evidence/insight/SWOT/recommendation 之外的事实。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List

try:
    from .llm_utils import call_json_llm, clean_text
    from .models import ReportState, SWOTItem, WritingAgentConfig
except ImportError:
    from report_agent.llm_utils import call_json_llm, clean_text
    from report_agent.models import ReportState, SWOTItem, WritingAgentConfig


def compose_report(state: ReportState, config: WritingAgentConfig) -> str:
    """生成最终 Markdown 报告。"""

    report = _report_from_llm(state, config)
    if report:
        return _clean_report(report)
    return _fallback_report_markdown(state)


def _report_from_llm(state: ReportState, config: WritingAgentConfig) -> str:
    """让 LLM 根据结构化分析润色报告。

    这里要求模型返回 JSON，是为了继续用程序校验输出；如果返回失败，直接走
    本地 Markdown fallback。
    """

    data = call_json_llm(
        config=config,
        system_prompt="你是面向产品经理写竞品分析报告的专家，只输出 JSON。",
        user_prompt=f"""
你只能基于下面结构化分析写报告，不要新增事实。

结构化分析:
{json.dumps(_structured_payload(state), ensure_ascii=False, indent=2)}

资料来源:
{json.dumps([source.to_dict() for source in state.sources], ensure_ascii=False, indent=2)}

请返回严格 JSON:
{{"report_markdown": "Markdown 正文"}}

报告必须包含这些章节:
核心结论、分析背景与目标、竞品分类、用户场景、重点竞品拆解、横向能力对比、SWOT、产品机会点与风险、产品策略建议、资料来源。
""".strip(),
    )
    if isinstance(data, dict):
        report = data.get("report_markdown")
        return "" if report is None else str(report).strip()
    return ""


def _fallback_report_markdown(state: ReportState) -> str:
    """离线 Markdown 报告。

    章节结构固定，确保 smoke test 和下游检测 Agent 能稳定找到核心部分。
    """

    lines: List[str] = [
        f"# {state.target_domain} 竞品分析报告",
        "",
        "## 核心结论",
        _executive_summary(state),
        "",
        "## 分析背景与目标",
        f"本报告服务于：{state.analysis_goal}。分析对象聚焦 {state.target_domain}，并基于上游搜索结果生成可被下游检测的结构化报告包。",
        "",
        "## 竞品分类与选择理由",
    ]

    if state.competitor_profiles:
        for profile in state.competitor_profiles:
            lines.append(
                "- {competitor}: {judgement} 证据: {evidence}".format(
                    competitor=_cell(profile.get("competitor", "未识别竞品")),
                    judgement=_cell(profile.get("strategic_judgement", "需要补充判断")),
                    evidence=", ".join(profile.get("evidence_ids", []) or ["无"]),
                )
            )
    else:
        lines.append("- 当前资料未形成明确竞品画像，需要补充搜索结果。")

    lines.extend(
        [
            "",
            "## 用户场景与任务分析",
        ]
    )
    if state.pm_insights:
        for insight in state.pm_insights:
            lines.append(
                f"- {insight.title}: {insight.description} 对 PM 的启发：{insight.pm_value} 证据: {', '.join(insight.evidence_ids)}"
            )
    else:
        lines.append("- 当前资料不足以形成明确用户场景洞察。")

    lines.extend(
        [
            "",
            "## 重点竞品拆解",
        ]
    )
    for profile in state.competitor_profiles:
        lines.append(f"### {_cell(profile.get('competitor', '未识别竞品'))}")
        lines.append(f"- 目标用户: {_cell(profile.get('target_user'))}")
        lines.append(f"- 核心场景: {_cell(profile.get('core_scenario'))}")
        lines.append(f"- 产品形态: {_cell(profile.get('product_form'))}")
        lines.append(f"- 商业模式: {_cell(profile.get('business_model'))}")
        lines.append(f"- 战略判断: {_cell(profile.get('strategic_judgement'))}")
    if not state.competitor_profiles:
        lines.append("- 暂无可拆解竞品画像。")

    lines.extend(
        [
            "",
            "## 横向能力对比",
            _markdown_tables(state.comparison_tables),
            "",
            "## SWOT 分析",
            _swot_markdown(state),
            "",
            "## 产品机会点与风险",
        ]
    )
    opportunities = [item for item in state.swot.opportunities] + [
        item for item in state.swot.weaknesses
    ]
    if opportunities:
        for item in opportunities:
            lines.append(
                f"- {item.point}: {item.pm_implication} 证据: {', '.join(item.evidence_ids)}"
            )
    else:
        lines.append("- 当前资料不足以形成明确机会点或风险。")

    lines.extend(
        [
            "",
            "## 产品策略建议",
        ]
    )
    for rec in state.recommendations:
        lines.append(
            f"- [{rec.timeframe}][{rec.priority}] {rec.action}。理由：{rec.reason}。预期影响：{rec.expected_impact}。风险：{rec.risk}。指标：{rec.success_metric}。证据: {', '.join(rec.evidence_ids)}"
        )
    if not state.recommendations:
        lines.append("- 当前资料不足以生成策略建议。")

    if state.missing_info or state.low_confidence_claims:
        lines.extend(["", "## 质检修复记录"])
        for item in state.missing_info:
            lines.append(f"- 修复约束: {item}")
        for item in state.low_confidence_claims:
            lines.append(f"- 低置信问题: {item}")

    lines.extend(
        [
            "",
            "## 资料来源",
        ]
    )
    for source in state.sources:
        lines.append(f"- [{source.source_id}] {source.title} {source.url}".rstrip())

    return "\n".join(lines).strip() + "\n"


def _executive_summary(state: ReportState) -> str:
    parts: List[str] = []
    if state.pm_insights:
        parts.append("；".join(insight.title for insight in state.pm_insights[:3]))
    if state.recommendations:
        parts.append(f"优先动作是：{state.recommendations[0].action}")
    if not parts:
        return "当前资料有限，建议先补充竞品事实和用户反馈证据。"
    return "。".join(parts) + "。"


def _markdown_tables(tables: List[Dict[str, Any]]) -> str:
    """把结构化 comparison_tables 渲染成 Markdown 表格。"""

    sections: List[str] = []
    for table in tables:
        name = table.get("table_name", "comparison_table")
        sections.append(f"### {name}")
        if name == "competitor_positioning_matrix":
            rows = table.get("rows", [])
            sections.append(
                _simple_table(
                    [
                        "competitor",
                        "target_user",
                        "core_scenario",
                        "business_model",
                        "strategic_judgement",
                    ],
                    rows,
                )
            )
        elif name == "agent_capability_scorecard":
            rows = table.get("dimensions", [])
            sections.append(_score_table(rows))
        elif name == "user_journey_comparison":
            rows = table.get("rows", [])
            sections.append(
                _simple_table(
                    [
                        "stage",
                        "user_goal",
                        "competitor_experience",
                        "opportunity",
                        "evidence_ids",
                    ],
                    rows,
                )
            )
        else:
            sections.append(
                f"```json\n{json.dumps(table, ensure_ascii=False, indent=2)}\n```"
            )
    return "\n\n".join(section for section in sections if section)


def _simple_table(columns: List[str], rows: Iterable[Dict[str, Any]]) -> str:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in rows:
        lines.append(
            "| " + " | ".join(_cell(row.get(column)) for column in columns) + " |"
        )
    return "\n".join(lines)


def _score_table(rows: Iterable[Dict[str, Any]]) -> str:
    lines = [
        "| dimension | weight | scores | reason | evidence_ids |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {dimension} | {weight} | {scores} | {reason} | {evidence_ids} |".format(
                dimension=_cell(row.get("dimension")),
                weight=_cell(row.get("weight")),
                scores=_cell(row.get("scores")),
                reason=_cell(row.get("reason")),
                evidence_ids=_cell(row.get("evidence_ids")),
            )
        )
    return "\n".join(lines)


def _swot_markdown(state: ReportState) -> str:
    sections = [
        ("Strengths", state.swot.strengths),
        ("Weaknesses", state.swot.weaknesses),
        ("Opportunities", state.swot.opportunities),
        ("Threats", state.swot.threats),
    ]
    lines: List[str] = []
    for title, items in sections:
        lines.append(f"### {title}")
        if not items:
            lines.append("- 暂无足够证据。")
            continue
        for item in items:
            lines.append(_swot_item_line(item))
    return "\n".join(lines)


def _swot_item_line(item: SWOTItem) -> str:
    return (
        f"- {item.point}: {item.why_it_matters} "
        f"PM 启发：{item.pm_implication} "
        f"置信度：{item.confidence:.2f} "
        f"证据: {', '.join(item.evidence_ids)}"
    )


def _structured_payload(state: ReportState) -> Dict[str, Any]:
    return {
        "executive_summary": {"text": _executive_summary(state)},
        "evidence_cards": [card.to_dict() for card in state.evidence_cards],
        "pm_insights": [insight.to_dict() for insight in state.pm_insights],
        "competitor_profiles": state.competitor_profiles,
        "comparison_tables": state.comparison_tables,
        "swot": state.swot.to_dict(),
        "recommendations": [rec.to_dict() for rec in state.recommendations],
        "product_recommendations": [rec.to_dict() for rec in state.recommendations],
        "writer_constraints": {
            "missing_info": state.missing_info,
            "low_confidence_claims": state.low_confidence_claims,
        },
        "generation_trace": state.generation_trace,
    }


def _cell(value: Any) -> str:
    """清理表格单元格内容，避免 Markdown 表格被竖线破坏。"""

    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = clean_text(value, 220)
    return text.replace("|", "\\|")


def _clean_report(report: str) -> str:
    report = report.replace("```markdown", "").replace("```", "").strip()
    return report + "\n" if report else ""

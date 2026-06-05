"""报告撰写 Agent。

Composer 只负责表达，把结构化分析渲染为 Markdown。它不重新搜索、不重新推理，
也不新增 evidence/insight/SWOT/recommendation 之外的事实。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List

try:
    from .llm_utils import call_json_llm, clean_text
    from .models import ReportState, SWOTItem, WritingAgentConfig
except ImportError:
    from report_agent.llm_utils import call_json_llm, clean_text
    from report_agent.models import ReportState, SWOTItem, WritingAgentConfig


def compose_report(state: ReportState, config: WritingAgentConfig) -> str:
    """生成最终 Markdown 报告。"""

    use_llm_composer = getattr(config, "use_llm_report_composer", False)
    if not use_llm_composer:
        return _fallback_report_markdown(state)

    report = _report_from_llm(state, config)
    if report:
        cleaned = _clean_report(report)
        if not _has_invalid_empty_tables(cleaned):
            return cleaned
        if config.verbose and config.progress_printer:
            config.progress_printer(
                "[writing-agent] LLM report contains empty tables, using fallback renderer"
            )
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
补充要求:
- 如果结构化分析包含我方产品参数词库或已知产品参数词库，报告必须单独体现“共同参数对齐”视角：这些参数来自用户自己的产品/我方产品，不是竞品事实；说明哪些竞品参数有证据、哪些缺证据、哪些参数决定产品选择。
- 如果结构化分析包含问卷分析，报告必须单独体现“用户/采购侧校准”视角：用户画像、场景优先级、价格敏感度、替换意愿、采购顾虑和风险偏好如何影响判断。
- 要明确区分“竞品事实证据”和“问卷/用户侧证据”：问卷结论只能用于需求侧和决策侧判断，不能写成某竞品官方功能或承诺。
- 不要输出空表格；如果某个单元格没有证据，请写“未找到明确证据”，如果整张表缺少有效数据，请写“暂无可渲染对比数据”。
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
        sections.append(f"### {_table_title(name)}")
        if name == "competitor_positioning_matrix":
            rows = table.get("rows", [])
            columns = [
                "competitor",
                "target_user",
                "core_scenario",
                "product_form",
                "main_entry",
                "business_model",
                "strategic_judgement",
                "evidence_ids",
            ]
            sections.append(
                _simple_table_or_empty(
                    _columns_for_rows(rows, columns),
                    rows,
                    header_map=_header_map(),
                )
            )
        elif name == "agent_capability_scorecard":
            rows = table.get("dimensions", [])
            sections.append(_score_table_or_empty(rows))
        elif name == "user_journey_comparison":
            rows = table.get("rows", [])
            columns = [
                "stage",
                "user_goal",
                "competitor_experience",
                "opportunity",
                "evidence_ids",
            ]
            sections.append(
                _simple_table_or_empty(
                    _columns_for_rows(rows, columns),
                    rows,
                    header_map=_header_map(),
                )
            )
        else:
            rows = _clean_table_rows(table.get("rows") or table.get("dimensions") or [])
            columns = table.get("columns")
            if not isinstance(columns, list):
                columns = _columns_for_rows(rows, [])
            else:
                columns = [str(column) for column in columns if str(column) != "pending_search_query"]
            if not columns:
                columns = ["待补充信息", "evidence_ids"]
            if not rows and columns:
                rows = [_pending_row_for_columns(columns, name)]
            sections.append(
                _simple_table_or_empty(
                    [str(column) for column in columns],
                    rows,
                    header_map=_header_map(),
                )
            )
    return "\n\n".join(section for section in sections if section)


def _table_title(name: Any) -> str:
    mapping = {
        "competitor_positioning_matrix": "竞品定位矩阵",
        "agent_capability_scorecard": "Agent 能力评分表",
        "user_journey_comparison": "用户旅程对比表",
    }
    return mapping.get(str(name), str(name))


def _header_map() -> Dict[str, str]:
    return {
        "dimension": "维度",
        "competitor": "竞品",
        "target_user": "目标用户",
        "core_scenario": "核心场景",
        "product_form": "产品形态",
        "main_entry": "主要入口",
        "business_model": "商业模式",
        "strategic_judgement": "战略判断",
        "stage": "阶段",
        "user_goal": "用户目标",
        "competitor_experience": "竞品体验",
        "opportunity": "机会点",
        "evidence_ids": "证据ID",
        "competitor_name": "竞品",
        "product": "竞品",
        "product_name": "竞品",
        "target_users": "目标用户",
        "core_positioning": "核心定位",
        "capability": "能力维度",
        "score": "评分",
        "scores": "评分",
        "reason": "依据",
        "journey_stage": "阶段",
        "source_ids": "证据ID",
    }


def _row_has_content(row: Dict[str, Any]) -> bool:
    for key, value in row.items():
        if key == "pending_search_query":
            continue
        if key == "evidence_ids":
            if value:
                return True
            continue
        if isinstance(value, dict) and value:
            return True
        if isinstance(value, list) and value:
            return True
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (int, float)) and value != 0:
            return True
    return False


def _valid_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [row for row in rows if isinstance(row, dict) and _row_has_content(row)]


def _clean_table_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        next_row = dict(row)
        next_row.pop("pending_search_query", None)
        cleaned.append(next_row)
    return cleaned


def _pending_row_for_columns(columns: Iterable[Any], table_name: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    subject = clean_text(table_name, 80) or "横向对比表"
    for raw_column in columns:
        column = str(raw_column)
        if column in {"evidence_ids", "证据ID", "证据ids", "source_ids", "pending_search_query"}:
            continue
        if column in {"竞品", "产品", "产品名称", "competitor"}:
            row[column] = "待搜索"
        else:
            row[column] = f"待搜索（方向：{subject} {column}）"
    row["evidence_ids"] = []
    return row


def _columns_for_rows(rows: Iterable[Dict[str, Any]], preferred: List[str]) -> List[str]:
    keys: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row.keys():
            if key == "pending_search_query":
                continue
            if key not in keys:
                keys.append(str(key))
    columns = [key for key in preferred if key in keys]
    columns.extend(key for key in keys if key not in columns)
    return columns or preferred


def _simple_table_or_empty(
    columns: List[str],
    rows: Iterable[Dict[str, Any]],
    *,
    header_map: Dict[str, str] | None = None,
) -> str:
    valid = _valid_rows(rows)
    if not valid:
        return "暂无可渲染对比数据。"
    return _simple_table(columns, valid, header_map=header_map or {})


def _simple_table(
    columns: List[str],
    rows: Iterable[Dict[str, Any]],
    *,
    header_map: Dict[str, str] | None = None,
) -> str:
    header_map = header_map or {}
    lines = [
        "| " + " | ".join(header_map.get(column, column) for column in columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in rows:
        lines.append(
            "| " + " | ".join(_cell(row.get(column)) for column in columns) + " |"
        )
    return "\n".join(lines)


def _score_table_or_empty(rows: Iterable[Dict[str, Any]]) -> str:
    valid = _valid_rows(rows)
    if not valid:
        return "暂无可渲染对比数据。"
    return _score_table(valid)


def _score_table(rows: Iterable[Dict[str, Any]]) -> str:
    lines = [
        "| 维度 | 权重 | 评分 | 依据 | 证据ID |",
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


def _has_invalid_empty_tables(report: str) -> bool:
    for table in _extract_markdown_tables(report):
        if _table_is_mostly_empty(table):
            return True
    return False


def _extract_markdown_tables(report: str) -> List[List[str]]:
    tables: List[List[str]] = []
    current: List[str] = []
    for raw_line in report.splitlines():
        line = raw_line.strip()
        if line.startswith("|") and line.endswith("|"):
            current.append(line)
            continue
        if current:
            if len(current) >= 3:
                tables.append(current)
            current = []
    if current and len(current) >= 3:
        tables.append(current)
    return tables


def _table_is_mostly_empty(lines: List[str]) -> bool:
    headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
    data_rows = [
        line
        for line in lines[2:]
        if not re.fullmatch(r"\|\s*[-: ]+(?:\|\s*[-: ]+)*\|", line)
    ]
    if not data_rows:
        return True

    empty_rows = 0
    useful_rows = 0
    for row in data_rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if _markdown_row_has_required_content(headers, cells):
            useful_rows += 1
        else:
            empty_rows += 1

    return useful_rows == 0 or empty_rows >= max(2, len(data_rows) // 2 + 1)


def _markdown_row_has_required_content(headers: List[str], cells: List[str]) -> bool:
    row = {
        header: cells[index] if index < len(cells) else ""
        for index, header in enumerate(headers)
    }
    if "dimension" in row and "scores" in row and "reason" in row:
        return bool(
            _meaningful_cell(row.get("dimension"))
            and (_meaningful_cell(row.get("scores")) or _meaningful_cell(row.get("reason")))
        )
    if "stage" in row and "user_goal" in row and "opportunity" in row:
        return bool(
            _meaningful_cell(row.get("stage"))
            and (
                _meaningful_cell(row.get("user_goal"))
                or _meaningful_cell(row.get("competitor_experience"))
                or _meaningful_cell(row.get("opportunity"))
            )
        )
    if "competitor" in row and "strategic_judgement" in row:
        return bool(
            _meaningful_cell(row.get("competitor"))
            and (
                _meaningful_cell(row.get("target_user"))
                or _meaningful_cell(row.get("core_scenario"))
                or _meaningful_cell(row.get("business_model"))
                or _meaningful_cell(row.get("strategic_judgement"))
            )
        )
    return any(
        _meaningful_cell(cell)
        for header, cell in row.items()
        if header != "evidence_ids"
    )


def _meaningful_cell(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return text not in {"[]", "{}", "null", "None", "未找到明确证据"}

"""Build QualityIssue items from the final report body by section."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from ..adapters.report_adapter import ReportAnalysis
from ..config import IssueSeverity, IssueType, QualityIssue


@dataclass
class BodySection:
    title: str
    content: str
    line_index: int


@dataclass
class SectionSignals:
    focus_terms: list[str]
    gap_targets: list[str]
    evidence_count: int
    claim_count: int
    metric_count: int
    has_timing: bool
    strategy_like: bool


def build_final_body_section_issues(
    analysis: ReportAnalysis,
    base_issues: Sequence[QualityIssue] | None = None,
) -> list[QualityIssue]:
    """Read the final body section by section and emit revision suggestions.

    The workflow wants quality-agent issues to be review tasks over the last
    report body, not a grab bag of low-level detector messages.
    """

    body = _extract_final_body(analysis.report_markdown)
    sections = _split_major_sections(body)
    if not sections:
        return list(base_issues or [])

    issues: list[QualityIssue] = []
    for section in sections:
        title = _clean_title(section.title)
        content = section.content.strip()
        if not title or _skip_section(title) or not _meaningful(content):
            continue

        if _has_markdown_table(content):
            table_issues = _table_issues(title, content)
            if table_issues:
                issues.extend(table_issues)
            else:
                issues.append(_text_issue(title, content, base_issues or []))
        else:
            issues.append(_text_issue(title, content, base_issues or []))

    return issues or list(base_issues or [])


def _extract_final_body(markdown: str) -> str:
    text = markdown.strip()
    marker_rules = [
        ("## 最终横向对比摘要", ("## 相关文件", "## 质量闭环摘要")),
        ("===== FINAL SUMMARY =====", ("===== QUALITY", "===== REFERENCE")),
    ]
    for marker, stop_markers in marker_rules:
        if marker not in text:
            continue
        text = text.split(marker, 1)[1].strip()
        for stop in stop_markers:
            if stop in text:
                text = text.split(stop, 1)[0].strip()
        return _trim_to_known_body_start(text)

    for stop in ("## 质量闭环摘要", "## 相关文件"):
        if stop in text:
            text = text.split(stop, 1)[0].strip()
    return _trim_to_known_body_start(text)


def _trim_to_known_body_start(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if _is_known_body_start_heading(line.strip()):
            return "\n".join(lines[index:]).strip()
    return text


def _is_known_body_start_heading(line: str) -> bool:
    if re.match(
        r"^##\s+(核心结论|分析背景与目标|竞品分类与选择理由|用户场景与任务分析|重点竞品拆解|横向能力对比|SWOT\s*分析|产品机会点与风险|产品策略建议)\s*$",
        line,
    ):
        return True
    if re.match(r"^##\s+[一二三四五六七八九十]+、", line):
        return True
    if re.match(r"^##\s+\d+[.)、]\s*", line):
        return True
    return False


def _split_major_sections(body: str) -> list[BodySection]:
    lines = body.splitlines()
    headings: list[tuple[int, int, str]] = []
    for index, raw_line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", raw_line.strip())
        if not match:
            continue
        level = len(match.group(1))
        if level <= 3:
            headings.append((index, level, match.group(2).strip()))

    if not headings:
        return [BodySection(title="最终正文", content=body, line_index=0)] if body.strip() else []

    preferred_level = 2 if any(level == 2 for _, level, _ in headings) else min(
        level for _, level, _ in headings
    )
    boundaries = [heading for heading in headings if heading[1] == preferred_level]
    sections: list[BodySection] = []

    for index, (line_index, _, title) in enumerate(boundaries):
        next_line_index = (
            boundaries[index + 1][0] if index + 1 < len(boundaries) else len(lines)
        )
        sections.append(
            BodySection(
                title=title,
                content="\n".join(lines[line_index:next_line_index]).strip(),
                line_index=line_index,
            )
        )
    return sections


def _clean_title(title: str) -> str:
    title = re.sub(r"^\s*\d+[.)、]\s*", "", title.strip())
    title = re.sub(r"^\s*[一二三四五六七八九十]+[、.]\s*", "", title)
    return title.strip(" #：:")


def _skip_section(title: str) -> bool:
    lowered = title.lower()
    skip_tokens = (
        "issue",
        "问题清单",
        "详细issue",
        "详细Issue",
        "质量闭环",
        "业务闭环指标",
        "相关文件",
        "资料来源",
        "数据来源",
        "参考资料",
        "参考点",
        "附录",
    )
    return any(token in lowered or token in title for token in skip_tokens)


def _meaningful(content: str) -> bool:
    compact = re.sub(r"\s+", "", content)
    return bool(compact) or _has_markdown_table(content)


def _text_issue(
    title: str,
    content: str,
    base_issues: Sequence[QualityIssue],
) -> QualityIssue:
    matched = _matching_base_issues(title, base_issues)
    signals = _section_signals(title, content)
    suggestion = _section_suggestion(title, content, matched, signals)
    subject = _section_issue_subject(title, signals)
    description = f"关于{subject}的修改建议"
    return QualityIssue(
        type=IssueType.INCOMPLETE_INFO,
        severity=IssueSeverity.MINOR,
        description=description,
        suggestion=f"{description}：{suggestion}",
        explanation=_section_explanation(title, signals),
        impact=_section_impact(title, signals),
        confidence=0.15,
        affected_fields=list(dict.fromkeys([title, subject, *signals.focus_terms[:3]])),
    )


def _section_suggestion(
    title: str,
    content: str,
    matched_issues: Sequence[QualityIssue],
    signals: SectionSignals,
) -> str:
    if matched_issues:
        fixes = "；".join(
            issue.suggestion
            for issue in matched_issues[:2]
            if issue.suggestion and "建议人工搜索" not in issue.suggestion
        )
        if fixes:
            scope = _format_scope(signals.focus_terms)
            return f"针对{scope}，{fixes}" if scope else fixes

    scope = _format_scope(signals.focus_terms)
    gap_scope = _format_scope(signals.gap_targets)
    if signals.gap_targets:
        return (
            f"把{gap_scope}单独列为待验证项，写清缺口字段、目标对象、需要补搜的数据口径，"
            "并把暂时不能下结论的判断边界标出来。"
        )
    if signals.claim_count >= 3 and signals.evidence_count == 0:
        return (
            f"为{scope or '本节核心判断'}补上可追溯证据锚点；没有证据的判断改成待确认，"
            "避免把推断、用户感知或策略假设直接写成事实。"
        )
    if signals.claim_count >= 6 and signals.evidence_count < max(2, signals.claim_count // 4):
        return (
            f"提高{scope or '本节'}的证据覆盖密度，至少给关键结论补齐来源编号、数据口径和置信度，"
            "并合并重复但证据相同的表述。"
        )
    if signals.strategy_like and (signals.metric_count < 2 or not signals.has_timing):
        return (
            f"把{scope or '策略动作'}拆成优先级、时间窗口、验证指标和失败回滚条件；"
            "对无法量化的动作补充可观察的验收信号。"
        )

    key = _section_key(title)
    if "核心结论" in key:
        return f"围绕{scope or '关键结论'}改成“结论-依据-动作”的三段式：每条结论保留一个明确判断、一个证据锚点和一个可执行动作，弱证据判断标注为待验证。"
    if "分析背景" in key or "目标" in key:
        return f"补清楚{scope or '分析对象'}的边界、目标用户、使用场景和决策问题；把我方参数与竞品事实分开写，避免背景段混入未经验证的结论。"
    if "分类" in key or "选择理由" in key:
        return f"围绕{scope or '候选竞品'}补充纳入/排除标准，例如目标用户、产品形态、商业化阶段、生态绑定和替代关系，并说明每个竞品为什么值得对比。"
    if "用户场景" in key or "任务分析" in key:
        return f"按{scope or '核心用户场景'}重排用户角色、任务频率、痛点强度和替换阻力；把问卷信号、行为场景和产品动作一一对应。"
    if "重点竞品" in key or "竞品拆解" in key:
        return f"对{scope or '每个竞品'}统一补齐目标用户、关键能力、价格权益、生态集成、已知短板和可迁移启发，减少不同竞品之间的维度缺口。"
    if "横向能力" in key or "横向对比" in key or "能力对比" in key:
        return f"针对{scope or '关键对比维度'}补充判定口径，区分已证实能力、公开口径和推断判断；对强弱结论给出原因，而不是只给标签。"
    if "swot" in key:
        return f"把{scope or '每条 S/W/O/T'}改成“事实依据-对我方影响-下一步动作”；合并重复项，并标出哪些机会依赖外部条件。"
    if "机会" in key or "风险" in key:
        return f"把{scope or '机会和风险'}拆成短期可验证、长期布局和需规避三类；为每项补充触发条件、影响范围和优先级。"
    if "策略" in key or "建议" in key:
        return f"为{scope or '每条策略'}补上优先级、投入成本、验证指标、时间窗口和失败回滚条件，避免停留在方向性口号。"
    if _has_gap_text(content):
        return "把资料缺口改写为待验证项，说明缺口类型、影响范围和暂不下结论的边界，并给出后续验证所需的数据口径。"
    if not _reference_hint(content) and len(content) > 120:
        return f"为{scope or '本节判断'}补充可追溯来源引用；无法证实的判断改写为待确认，避免把推测写成事实。"
    return f"复核{scope or '本节结论'}是否覆盖对象、证据、影响和下一步动作；必要时补充遗漏维度或收敛重复表述。"


def _section_signals(title: str, content: str) -> SectionSignals:
    key = _section_key(title)
    claim_lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip().startswith(("-", "*")) or re.search(r"[。；;]$", line.strip())
    ]
    evidence_count = len(re.findall(r"\bev_\d+\b|\bgap_src_\d+\b|\[参考点\d+\]", content))
    metric_count = len(re.findall(r"\d+(?:\.\d+)?\s*(?:%|TOPS|km|公里|万元|元|天|周|月|年|人|次|s|秒)", content, flags=re.I))
    has_timing = bool(re.search(r"\d+\s*(?:天|周|月|年)|\b(?:30|60|90)_days\b|P[0-2]|短期|中期|长期|时间窗口", content, flags=re.I))
    strategy_like = bool(
        ("策略" in key or "建议" in key or "机会" in key or "风险" in key)
        or re.search(r"(优先级|P[0-2]|指标|回滚|落地任务|执行计划)", title + "\n" + content, flags=re.I)
    )
    return SectionSignals(
        focus_terms=_content_focus_terms(title, content),
        gap_targets=_gap_targets(content),
        evidence_count=evidence_count,
        claim_count=max(len(claim_lines), len(re.findall(r"[。；;]", content))),
        metric_count=metric_count,
        has_timing=has_timing,
        strategy_like=strategy_like,
    )


def _section_issue_subject(title: str, signals: SectionSignals) -> str:
    focus = _format_scope(signals.gap_targets[:1] or signals.focus_terms[:1])
    if focus and focus not in title and len(title) + len(focus) <= 46:
        return f"{title}中{focus}"
    return title


def _format_scope(items: Sequence[str]) -> str:
    cleaned = [item.strip() for item in items if item.strip()]
    if not cleaned:
        return ""
    return "、".join(cleaned[:3])


def _content_focus_terms(title: str, content: str) -> list[str]:
    terms: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = re.match(r"^#{3,6}\s+(.+?)\s*$", line)
        if heading:
            _append_focus_term(terms, heading.group(1), title)
            continue
        if line.startswith(("-", "*")):
            _append_focus_term(terms, line.lstrip("-* ").strip(), title)
            continue
        if len(terms) < 2 and re.search(r"(PM\s*启发|产品定位|目标用户|商业模式|战略判断|核心短板|机会|风险)", line):
            _append_focus_term(terms, line, title)
    if terms:
        return terms[:4]
    for match in re.finditer(r"(?:竞品|产品|品牌|平台|车型|工具|方案)[：:]\s*([^，,。；;\n]{2,24})", content):
        _append_focus_term(terms, match.group(1), title)
    return terms[:4]


def _append_focus_term(terms: list[str], value: str, title: str) -> None:
    cleaned = _clean_focus_term(value)
    if not cleaned or cleaned == title or cleaned in terms:
        return
    terms.append(cleaned)


def _clean_focus_term(value: str) -> str:
    text = re.sub(r"`|\*\*|__|\[|\]", "", value.strip())
    text = re.sub(r"\s+", " ", text)
    text = re.split(r"PM\s*启发|证据[:：]|置信度[:：]|理由[:：]", text, maxsplit=1, flags=re.I)[0]
    text = re.split(r"[:：。；;，,]", text, maxsplit=1)[0]
    text = re.sub(r"^\d+[.)、]\s*", "", text)
    text = re.sub(r"^\s*[一二三四五六七八九十]+[、.]\s*", "", text)
    text = text.strip(" -—,，。；;：:")
    if len(text) > 24:
        text = text[:24].rstrip()
    text = text.strip(" -—,，。；;：:")
    if len(text) < 2:
        return ""
    if text.startswith(("本报告", "本节", "本章节")):
        return ""
    generic = {"核心结论", "分析背景与目标", "横向能力对比", "SWOT 分析", "产品策略建议"}
    return "" if text in generic else text


def _gap_targets(content: str) -> list[str]:
    table_targets = _table_search_targets("table", content)
    if table_targets:
        return table_targets[:4]
    targets: list[str] = []
    for raw_line in content.splitlines():
        if raw_line.strip().startswith("|"):
            continue
        if not re.search(r"(未找到明确证据|待搜索|待补充|缺少|不足|待确认|完全缺失|未公开|未披露|暂无)", raw_line):
            continue
        cleaned = _clean_focus_term(raw_line.lstrip("-*| ").strip())
        if cleaned and cleaned not in targets:
            targets.append(cleaned)
    return targets[:4]


def _section_key(title: str) -> str:
    return re.sub(r"\s+", "", title).lower()


def _section_explanation(title: str, signals: SectionSignals) -> str:
    scope = _format_scope(signals.gap_targets[:2] or signals.focus_terms[:2])
    key = _section_key(title)
    if "横向能力" in key or "横向对比" in key or "能力对比" in key:
        return f"Quality Agent 已按最终正文大章节阅读；该章节重点检查{scope or '对比维度'}的判定口径、证据强度和强弱结论是否一致。"
    if "swot" in key:
        return f"Quality Agent 已按最终正文大章节阅读；该章节重点检查{scope or 'SWOT 条目'}是否能支撑后续策略推导。"
    if "策略" in key or "建议" in key:
        return f"Quality Agent 已按最终正文大章节阅读；该章节重点检查{scope or '建议'}是否具体、可验证、可执行。"
    if "机会" in key or "风险" in key:
        return f"Quality Agent 已按最终正文大章节阅读；该章节重点检查{scope or '机会与风险'}是否有触发条件和影响判断。"
    return f"Quality Agent 已按最终正文大章节逐段阅读，并将{scope or '该章节'}转成可执行的修改或补充建议。"


def _section_impact(title: str, signals: SectionSignals) -> str:
    scope = _format_scope(signals.gap_targets[:2] or signals.focus_terms[:2])
    key = _section_key(title)
    if "核心结论" in key:
        return f"{scope or '核心结论'}会直接影响产品决策优先级，需要同时具备判断、依据和下一步动作。"
    if "分析背景" in key or "目标" in key:
        return "背景和目标如果边界不清，后续竞品选择、用户场景和策略建议会失去共同口径。"
    if "分类" in key or "选择理由" in key:
        return "竞品选择理由不充分会让横向对比对象失焦，影响结论的代表性。"
    if "用户场景" in key or "任务分析" in key:
        return f"{scope or '用户场景'}需要连接真实任务和产品动作，否则建议难以落到具体需求。"
    if "重点竞品" in key or "竞品拆解" in key:
        return f"{scope or '竞品拆解'}维度不统一会削弱后续横向比较和差异化判断。"
    if "横向能力" in key or "横向对比" in key or "能力对比" in key:
        return f"{scope or '横向对比'}是报告的关键决策依据，需要保证维度定义、证据强度和结论标签一致。"
    if "swot" in key:
        return f"{scope or 'SWOT'}若停留在罗列，会削弱产品机会、风险和策略之间的推导链。"
    if "机会" in key or "风险" in key:
        return f"{scope or '机会和风险'}需要转成优先级与触发条件，才能支持下一步取舍。"
    if "策略" in key or "建议" in key:
        return f"{scope or '策略建议'}如果缺少验证指标和时间窗口，会难以执行和复盘。"
    return "用于人工复核该章节是否需要补证据、补维度或收敛表述。"


def _matching_base_issues(
    title: str,
    base_issues: Sequence[QualityIssue],
) -> list[QualityIssue]:
    matched: list[QualityIssue] = []
    for issue in base_issues:
        text = f"{issue.description} {issue.suggestion} {' '.join(issue.affected_fields)}"
        if title and title in text:
            matched.append(issue)
    return matched


def _table_issues(title: str, content: str) -> list[QualityIssue]:
    targets = _table_search_targets(title, content)
    return [_table_issue(title, target) for target in targets]


def _table_issue(title: str, target: str) -> QualityIssue:
    description = f"建议人工搜索{target}"
    return QualityIssue(
        type=IssueType.INSUFFICIENT_EVIDENCE,
        severity=IssueSeverity.MINOR,
        description=description,
        suggestion=description,
        explanation="该章节包含 Markdown 表格，表格数据需要人工逐项搜索或核对来源。",
        impact="避免横向对比表格中的字段误填、漏填或来源不可追溯。",
        confidence=0.25,
        affected_fields=[title, "table_manual_search"],
    )


def _table_search_targets(title: str, content: str) -> list[str]:
    topics: list[str] = []
    for table in _markdown_table_blocks(content):
        headers = _parse_table_row(table[0]) if table else []
        for row_line in table[2:]:
            cells = _parse_table_row(row_line)
            row_label = _first_meaningful_cell(cells)
            for index, cell in enumerate(cells):
                if not _is_gap_cell(cell):
                    continue
                header = headers[index] if index < len(headers) else ""
                topic = " ".join(part for part in (row_label, header) if part).strip()
                if topic and topic not in topics:
                    topics.append(topic)
    if topics:
        return topics
    return []


def _has_markdown_table(content: str) -> bool:
    lines = [line.strip() for line in content.splitlines()]
    for index, line in enumerate(lines[:-1]):
        if not (line.startswith("|") and line.endswith("|")):
            continue
        separator = lines[index + 1]
        if re.match(r"^\|\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", separator):
            return True
    return False


def _markdown_table_blocks(content: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("|") and line.endswith("|"):
            current.append(line)
            continue
        if current:
            if len(current) >= 2:
                blocks.append(current)
            current = []
    if current and len(current) >= 2:
        blocks.append(current)
    return blocks


def _parse_table_row(line: str) -> list[str]:
    return [cell.strip().replace("\\|", "|") for cell in line.strip().strip("|").split("|")]


def _first_meaningful_cell(cells: Iterable[str]) -> str:
    for cell in cells:
        if cell and not _is_gap_cell(cell) and not re.fullmatch(r":?-{3,}:?", cell):
            return cell[:40]
    return ""


def _is_gap_cell(value: str) -> bool:
    text = value.strip()
    if not text:
        return True
    normalized = re.sub(r"\s+", "", text).strip("。；;，,：:")
    exact_gap_tokens = {
        "-",
        "--",
        "n/a",
        "N/A",
        "无",
        "暂无",
        "待搜索",
        "待补充",
        "待确认",
        "完全缺失",
        "未公开",
        "未披露",
        "未找到",
        "未找到证据",
        "未找到明确证据",
    }
    if normalized in exact_gap_tokens:
        return True
    gap_prefixes = (
        "待搜索",
        "待补充",
        "未找到明确证据",
        "完全缺失",
        "未公开",
        "未披露",
        "待确认",
        "n/a",
    )
    lowered = normalized.lower()
    if any(lowered.startswith(token.lower()) for token in gap_prefixes):
        return True
    return bool(
        re.search(
            r"(待.*验证|待.*确认|待.*补|待.*搜索|未.*公开|未.*披露|未.*找到|完全缺失|缺少|缺失|证据不足)",
            normalized,
            flags=re.I,
        )
    )


def _has_gap_text(content: str) -> bool:
    return bool(
        re.search(
            r"(未找到明确证据|待搜索|待补充|缺少|不足|待确认|完全缺失|未公开|未披露|暂无)",
            content,
        )
    )


def _reference_hint(content: str) -> str:
    references = re.findall(r"\[[^\]\n]*参考点\d+\]|ev_\d+|gap_src_\d+", content)
    return "、".join(dict.fromkeys(references[:6]))

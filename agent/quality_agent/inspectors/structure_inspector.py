"""Report structure inspection functions."""

from typing import List, Sequence

from ..adapters.report_adapter import ReportAnalysis
from ..config import IssueSeverity, IssueType, QualityIssue


def _has_any_section(markdown: str, aliases: Sequence[str]) -> bool:
    return any(alias in markdown for alias in aliases)


def check_report_structure(analysis: ReportAnalysis) -> List[QualityIssue]:
    """Check report markdown structure completeness."""
    issues: List[QualityIssue] = []
    markdown = analysis.report_markdown

    required_sections = [
        ("执行摘要", ("## 执行摘要", "## 核心结论", "===== FINAL COMPARISON SUMMARY")),
        ("竞品分析", ("## 竞品分析", "单产品深度拆解", "重点竞品拆解", "核心维度横向对比")),
        ("SWOT分析", ("## SWOT分析", "## SWOT 分析")),
        ("策略建议", ("## 策略建议", "选型建议", "产品策略建议")),
        ("结论", ("## 结论", "## 核心结论", "选型建议")),
    ]

    missing_sections = []
    for name, aliases in required_sections:
        if not _has_any_section(markdown, aliases):
            missing_sections.append(name)

    if missing_sections:
        issues.append(QualityIssue(
            type=IssueType.INCOMPLETE_INFO,
            severity=IssueSeverity.MINOR,
            description=f"报告缺少必要章节: {', '.join(missing_sections)}",
            suggestion=f"补充缺失的章节内容: {', '.join(missing_sections)}",
            explanation="完整的竞品分析报告需要包含标准章节结构",
            impact="缺少必要章节会影响报告的完整性和可读性"
        ))

    if len(markdown) < 1000:
        issues.append(QualityIssue(
            type=IssueType.INCOMPLETE_INFO,
            severity=IssueSeverity.MINOR,
            description=f"报告内容过短 ({len(markdown)} 字符)",
            suggestion="增加报告内容，提供更详细的分析",
            explanation="足够的内容长度是报告质量的基本保证",
            impact="内容过短可能导致分析不够深入"
        ))

    if "[" not in markdown or "](" not in markdown:
        issues.append(QualityIssue(
            type=IssueType.MISSING_SOURCE,
            severity=IssueSeverity.MINOR,
            description="报告缺少来源引用标记",
            suggestion="在报告中添加来源引用，如 [来源](URL)",
            explanation="来源引用是报告可信度的重要组成部分",
            impact="缺少引用会降低报告的可验证性"
        ))

    return issues

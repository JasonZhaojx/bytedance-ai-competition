"""Report structure inspection functions."""

from typing import List

from ..adapters.report_adapter import ReportAnalysis
from ..config import IssueSeverity, IssueType, QualityIssue

# 检查报告结构是否符合要求
def check_report_structure(analysis: ReportAnalysis) -> List[QualityIssue]:
    """Check report markdown structure completeness."""
    issues: List[QualityIssue] = []
    markdown = analysis.report_markdown
    
    required_sections = [
        ("## 执行摘要", "执行摘要"),
        ("## 竞品分析", "竞品分析"),
        ("## SWOT分析", "SWOT分析"),
        ("## 策略建议", "策略建议"),
        ("## 结论", "结论"),
    ]
    
    # 检查报告是否缺少必要章节
    missing_sections = []
    for pattern, name in required_sections:
        if pattern not in markdown and f"## {name}" not in markdown:
            missing_sections.append(name)
    
    # 检查报告是否缺少必要章节
    if missing_sections:
        issues.append(QualityIssue(
            type=IssueType.INCOMPLETE_INFO,
            severity=IssueSeverity.MINOR,
            description=f"报告缺少必要章节: {', '.join(missing_sections)}",
            suggestion=f"补充缺失的章节内容: {', '.join(missing_sections)}",
            explanation="完整的竞品分析报告需要包含标准章节结构",
            impact="缺少必要章节会影响报告的完整性和可读性"
        ))
    
    # 检查报告内容是否过短
    if len(markdown) < 1000:
        issues.append(QualityIssue(
            type=IssueType.INCOMPLETE_INFO,
            severity=IssueSeverity.MINOR,
            description=f"报告内容过短 ({len(markdown)} 字符)",
            suggestion="增加报告内容，提供更详细的分析",
            explanation="足够的内容长度是报告质量的基本保证",
            impact="内容过短可能导致分析不够深入"
        ))
    
    # 检查报告是否缺少来源引用
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
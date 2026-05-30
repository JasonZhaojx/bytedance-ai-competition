"""Recommendation feasibility inspection functions."""

import re
from typing import Any, Dict, List

from ..adapters.report_adapter import ReportAnalysis
from ..config import IssueSeverity, IssueType, QualityIssue


def _extract_markdown_recommendations(markdown: str) -> List[Dict[str, Any]]:
    """Extract simple numbered recommendations from markdown-only reports."""
    section_match = re.search(
        r"^##\s*(?:[一二三四五六七八九十]+[、.]\s*)?(?:策略建议|选型建议|产品策略建议).*$([\s\S]*?)(?=^##\s+|\Z)",
        markdown,
        flags=re.MULTILINE,
    )
    if not section_match:
        return []

    recommendations = []
    for line in section_match.group(1).splitlines():
        match = re.match(r"^\s*\d+[.)、]\s*(.+)", line)
        if match:
            action = match.group(1).strip()
            recommendations.append({"action": action})
    return recommendations


def _get_recommendations(analysis: ReportAnalysis) -> List[Dict[str, Any]]:
    if analysis.recommendations:
        return [rec for rec in analysis.recommendations if isinstance(rec, dict)]
    return _extract_markdown_recommendations(analysis.report_markdown)


def check_recommendation_feasibility(analysis: ReportAnalysis) -> List[QualityIssue]:
    """Check recommendation feasibility and executability."""
    issues: List[QualityIssue] = []
    recommendations = _get_recommendations(analysis)

    valid_timeframes = ["7天", "30天", "60天", "90天", "半年", "一年"]

    for idx, rec in enumerate(recommendations, 1):
        action = rec.get("action", "")
        timeframe = rec.get("timeframe", "")
        success_metric = rec.get("success_metric", "")

        if len(action) < 10:
            issues.append(QualityIssue(
                type=IssueType.INCOMPLETE_INFO,
                severity=IssueSeverity.MINOR,
                description=f"建议 {idx} 描述过于笼统",
                suggestion="提供更具体的行动描述",
                explanation="具体的建议更容易执行",
                impact="笼统的建议缺乏可操作性"
            ))

        if timeframe and timeframe not in valid_timeframes:
            issues.append(QualityIssue(
                type=IssueType.INCOMPLETE_INFO,
                severity=IssueSeverity.MINOR,
                description=f"建议 {idx} 的时间框架 '{timeframe}' 不标准",
                suggestion=f"使用标准时间框架: {', '.join(valid_timeframes)}",
                explanation="标准时间框架便于项目规划和跟踪",
                impact="不标准的时间框架可能导致执行困难"
            ))

        if analysis.recommendations and not success_metric:
            issues.append(QualityIssue(
                type=IssueType.INCOMPLETE_INFO,
                severity=IssueSeverity.MINOR,
                description=f"建议 {idx} 缺少成功指标",
                suggestion="定义可量化的成功指标",
                explanation="成功指标是衡量建议效果的关键",
                impact="缺少成功指标无法评估建议的执行效果"
            ))

    if len(recommendations) > 10:
        issues.append(QualityIssue(
            type=IssueType.INCOMPLETE_INFO,
            severity=IssueSeverity.MINOR,
            description=f"建议数量过多 ({len(recommendations)} 条)",
            suggestion="精简建议，聚焦最重要的几项",
            explanation="过多的建议会分散注意力，降低执行力",
            impact="过多建议可能导致无法有效执行"
        ))

    if len(recommendations) < 3:
        issues.append(QualityIssue(
            type=IssueType.INCOMPLETE_INFO,
            severity=IssueSeverity.MINOR,
            description=f"建议数量较少 ({len(recommendations)} 条)",
            suggestion="增加更多策略建议",
            explanation="适量的建议能提供更全面的行动指导",
            impact="建议过少可能无法充分覆盖分析结果"
        ))

    return issues

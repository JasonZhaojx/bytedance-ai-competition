"""Logical consistency inspection functions."""

from typing import List

from ..adapters.report_adapter import ReportAnalysis
from ..config import IssueSeverity, IssueType, QualityIssue

# 要确保检查逻辑一致性
def check_logical_consistency(analysis: ReportAnalysis) -> List[QualityIssue]:
    """Check logical consistency between SWOT and recommendations."""
    issues: List[QualityIssue] = []
    
    swot_points = []
    # 检查SWOT分析是否包含任何内容
    for category in ['strengths', 'weaknesses', 'opportunities', 'threats']:
        for item in analysis.swot.get(category, []):
            # 检查swot points有哪些
            if isinstance(item, dict):
                swot_points.append(item.get('point', '').lower())
            else:
                swot_points.append(str(item).lower())
    
    # 检查策略建议是否包含任何内容
    recommendation_actions = []
    for rec in analysis.recommendations:
        if isinstance(rec, dict):
            action = rec.get('action', '').lower()
            reason = rec.get('reason', '').lower()
            recommendation_actions.append((action, reason))
    
    # 检查策略建议是否与SWOT分析相关
    if swot_points and recommendation_actions:
        unreferenced_swot = []
        for point in swot_points:
            referenced = False
            for action, reason in recommendation_actions:
                if point[:30] in action or point[:30] in reason:
                    referenced = True
                    break
            if not referenced:
                unreferenced_swot.append(point[:50])
        
        if len(unreferenced_swot) > len(swot_points) * 0.5:
            issues.append(QualityIssue(
                type=IssueType.LOGICAL_INCONSISTENCY,
                severity=IssueSeverity.MINOR,
                description="策略建议与SWOT分析关联性较弱",
                suggestion="确保策略建议基于SWOT分析结果制定",
                explanation="策略建议应该是SWOT分析的自然延伸",
                impact="缺乏关联会降低报告的逻辑性和说服力"
            ))
    
    # 检查策略建议是否重复
    # 如果重复，就认为是主要问题
    action_set = set()
    for action, _ in recommendation_actions:
        action_set.add(action)
    
    if len(recommendation_actions) != len(action_set):
        issues.append(QualityIssue(
            type=IssueType.LOGICAL_INCONSISTENCY,
            severity=IssueSeverity.MINOR,
            description="存在重复或相似的策略建议",
            suggestion="合并重复的建议，保持建议的简洁性",
            explanation="重复建议会降低报告的专业性",
            impact="冗余建议可能让读者困惑"
        ))
    
    return issues
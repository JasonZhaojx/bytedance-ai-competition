"""Recommendation feasibility inspection functions."""

from typing import List

from ..adapters.report_adapter import ReportAnalysis
from ..config import IssueSeverity, IssueType, QualityIssue

# 检查策略建议是否符合要求
def check_recommendation_feasibility(analysis: ReportAnalysis) -> List[QualityIssue]:
    """Check recommendation feasibility and executability."""
    issues: List[QualityIssue] = []
    
    # 定义有效的时间框架
    valid_timeframes = ['7天', '30天', '60天', '90天', '半年', '一年']
    
    for idx, rec in enumerate(analysis.recommendations, 1):
        if not isinstance(rec, dict):
            continue
        
        # 检查建议是否符合要求
        action = rec.get('action', '')
        timeframe = rec.get('timeframe', '')
        success_metric = rec.get('success_metric', '')
        
        if len(action) < 10 or action == "":
            issues.append(QualityIssue(
                type=IssueType.INCOMPLETE_INFO,
                severity=IssueSeverity.MINOR,
                description=f"建议 {idx} 描述过于笼统",
                suggestion="提供更具体的行动描述",
                explanation="具体的建议更容易执行",
                impact="笼统的建议缺乏可操作性"
            ))
        # 检查时间框架是否符合要求
        if timeframe and timeframe not in valid_timeframes:
            issues.append(QualityIssue(
                type=IssueType.INCOMPLETE_INFO,
                severity=IssueSeverity.MINOR,
                description=f"建议 {idx} 的时间框架 '{timeframe}' 不标准",
                suggestion=f"使用标准时间框架: {', '.join(valid_timeframes)}",
                explanation="标准时间框架便于项目规划和跟踪",
                impact="不标准的时间框架可能导致执行困难"
            ))

        # 检查成功指标是否符合要求
        if not success_metric:
            issues.append(QualityIssue(
                type=IssueType.INCOMPLETE_INFO,
                severity=IssueSeverity.MINOR,
                description=f"建议 {idx} 缺少成功指标",
                suggestion="定义可量化的成功指标",
                explanation="成功指标是衡量建议效果的关键",
                impact="缺少成功指标无法评估建议的执行效果"
            ))

    # 检查策略建议是否重复
    if len(analysis.recommendations) > 10:
        issues.append(QualityIssue(
            type=IssueType.INCOMPLETE_INFO,
            severity=IssueSeverity.MINOR,
            description=f"建议数量过多 ({len(analysis.recommendations)} 条)",
            suggestion="精简建议，聚焦最重要的几项",
            explanation="过多的建议会分散注意力，降低执行力",
            impact="过多建议可能导致无法有效执行"
        ))
    
    # 检查策略建议是否与SWOT分析相关
    if len(analysis.recommendations) < 3:
        issues.append(QualityIssue(
            type=IssueType.INCOMPLETE_INFO,
            severity=IssueSeverity.MINOR,
            description=f"建议数量较少 ({len(analysis.recommendations)} 条)",
            suggestion="增加更多策略建议",
            explanation="适量的建议能提供更全面的行动指导",
            impact="建议过少可能无法充分覆盖分析结果"
        ))
    
    return issues
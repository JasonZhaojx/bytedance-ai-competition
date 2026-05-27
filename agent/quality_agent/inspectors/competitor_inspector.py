"""Competitor coverage inspection functions."""
from typing import Dict, List

from ..adapters.report_adapter import ReportAnalysis
from ..config import IssueSeverity, IssueType, QualityIssue


# 检查竞品分析覆盖完整性
def check_competitor_coverage(analysis: ReportAnalysis) -> List[QualityIssue]:
    """Check competitor analysis coverage completeness."""
    issues: List[QualityIssue] = []
    
    # 检查报告是否有竞品分析部分
    competitors = analysis.competitors
    if not competitors:
        return issues
    
    # 检查每个竞品是否有证据支持
    competitor_evidence_count: Dict[str, int] = {c: 0 for c in competitors}
    
    # 检查每个证据是否包含任何竞品
    for evidence in analysis.evidence_list:
        text = (evidence.title + " " + evidence.claim).lower()
        for competitor in competitors:
            if competitor.lower() in text:
                competitor_evidence_count[competitor] += 1
    
    # 检查是否有竞品缺乏证据支持
    underrepresented = [
        comp for comp, count in competitor_evidence_count.items()
        if count == 0
    ]
    if underrepresented:
        issues.append(QualityIssue(
            type=IssueType.INSUFFICIENT_EVIDENCE,
            severity=IssueSeverity.MAJOR if len(underrepresented) > 1 else IssueSeverity.MINOR,
            description=f"竞品 {', '.join(underrepresented)} 缺乏证据支持",
            suggestion=f"增加针对 {', '.join(underrepresented)} 的搜索和分析",
            explanation="每个竞品都需要有足够的证据支持才能进行有效对比",
            impact="缺乏证据支持的竞品分析会导致对比不完整"
        ))
    
    # 检查是否有对比表缺少竞品
    if analysis.comparison_tables:
        # 检查每个对比表是否包含所有竞品
        for table in analysis.comparison_tables:
            table_competitors = table.get("competitors", []) or table.get("rows", [])
            if isinstance(table_competitors, list) and len(table_competitors) > 0:
                table_comp_names = set()
                for row in table_competitors:
                    if isinstance(row, dict):
                        table_comp_names.add(row.get("competitor", ""))
                    elif isinstance(row, str):
                        table_comp_names.add(row)
                
                missing_in_table = [c for c in competitors if c not in table_comp_names]
                if missing_in_table:
                    issues.append(QualityIssue(
                        type=IssueType.INCOMPLETE_INFO,
                        severity=IssueSeverity.MINOR,
                        description=f"对比表缺少竞品: {', '.join(missing_in_table)}",
                        suggestion=f"在对比表中添加 {', '.join(missing_in_table)} 的信息",
                        explanation="完整的对比表应包含所有目标竞品",
                        impact="缺少竞品的对比表会影响分析的全面性"
                    ))
    
    return issues
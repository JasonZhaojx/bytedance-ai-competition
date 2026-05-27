"""Score calculation for report quality."""

from typing import List

from .adapters.report_adapter import ReportAnalysis
from .config import ConfidenceLevel, IssueSeverity, QualityIssue


def calculate_report_score(issues: List[QualityIssue], analysis: ReportAnalysis) -> float:
    """Calculate report quality score."""
    score = 1.0
    
    # Deduct based on issue severity
    for issue in issues:
        if issue.severity == IssueSeverity.CRITICAL:
            score -= 0.3 * issue.confidence
        elif issue.severity == IssueSeverity.MAJOR:
            score -= 0.15 * issue.confidence
        elif issue.severity == IssueSeverity.MINOR:
            score -= 0.05 * issue.confidence
    
    # Add based on content completeness
    content_score = 0.0
    
    # Insights completeness
    if analysis.pm_insights:
        content_score += 0.05
        if len(analysis.pm_insights) >= 3:
            content_score += 0.05
    
    # SWOT completeness
    swot_complete = all(analysis.swot.get(s, []) for s in [
        'strengths', 'weaknesses', 'opportunities', 'threats'
    ])
    if swot_complete:
        content_score += 0.05
        swot_rich = all(len(analysis.swot.get(s, [])) >= 2 for s in [
            'strengths', 'weaknesses', 'opportunities', 'threats'
        ])
        if swot_rich:
            content_score += 0.05
    
    # Recommendations completeness
    if analysis.recommendations:
        content_score += 0.05
        if 3 <= len(analysis.recommendations) <= 10:
            content_score += 0.05
    
    # Claims completeness
    if analysis.claims:
        content_score += 0.05
    
    # Report structure completeness
    if len(analysis.report_markdown) >= 1000:
        content_score += 0.05
    
    # Evidence diversity bonus
    source_types = len(set(e.source_type for e in analysis.evidence_list if e.source_type))
    if source_types >= 3:
        content_score += 0.05
    
    score += content_score
    
    return max(0.0, min(1.0, score))


def calculate_confidence_level(score: float, issues: List[QualityIssue]) -> ConfidenceLevel:
    """Calculate confidence level based on score and issues."""
    critical_issues = [i for i in issues if i.severity == IssueSeverity.CRITICAL]
    major_issues = [i for i in issues if i.severity == IssueSeverity.MAJOR]
    
    if score >= 0.85 and not critical_issues and len(major_issues) <= 1:
        return ConfidenceLevel.HIGH
    if score >= 0.6 and not critical_issues:
        if len(major_issues) > 2:
            return ConfidenceLevel.LOW
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW
"""Score calculation for report quality."""

from typing import Dict, List

from .adapters.report_adapter import ReportAnalysis
from .config import ConfidenceLevel, IssueSeverity, IssueType, QualityIssue


DIMENSION_WEIGHTS: Dict[str, float] = {
    "structure": 0.25,
    "traceability": 0.30,
    "competitor_coverage": 0.20,
    "logic_recommendation": 0.15,
    "language": 0.10,
}

ISSUE_DIMENSIONS: Dict[IssueType, str] = {
    IssueType.INCOMPLETE_INFO: "structure",
    IssueType.MISSING_SOURCE: "traceability",
    IssueType.INSUFFICIENT_EVIDENCE: "traceability",
    IssueType.WEAK_EVIDENCE_SUPPORT: "traceability",
    IssueType.LOW_QUALITY_EVIDENCE: "traceability",
    IssueType.OUTDATED_EVIDENCE: "traceability",
    IssueType.CONFLICTING_EVIDENCE: "logic_recommendation",
    IssueType.LOGICAL_INCONSISTENCY: "logic_recommendation",
}

SEVERITY_PENALTY: Dict[IssueSeverity, float] = {
    IssueSeverity.CRITICAL: 1.0,
    IssueSeverity.MAJOR: 0.55,
    IssueSeverity.MINOR: 0.20,
}


def calculate_report_score(issues: List[QualityIssue], analysis: ReportAnalysis) -> float:
    """Calculate report quality score using business-dimension weights."""
    if not analysis.report_markdown.strip():
        return 0.0

    dimension_scores = {name: 1.0 for name in DIMENSION_WEIGHTS}

    for issue in issues:
        dimension = _dimension_for_issue(issue)
        penalty = SEVERITY_PENALTY.get(issue.severity, 0.2) * max(issue.confidence, 0.1)
        dimension_scores[dimension] = max(0.0, dimension_scores[dimension] - penalty)

    _apply_positive_signals(dimension_scores, analysis)

    score = sum(
        DIMENSION_WEIGHTS[dimension] * dimension_scores[dimension]
        for dimension in DIMENSION_WEIGHTS
    )
    return max(0.0, min(1.0, score))


def _dimension_for_issue(issue: QualityIssue) -> str:
    if issue.type == IssueType.INCOMPLETE_INFO:
        description = issue.description
        if "竞品" in description or "对比表" in description:
            return "competitor_coverage"
        if "建议" in description:
            return "logic_recommendation"
        return "structure"
    return ISSUE_DIMENSIONS.get(issue.type, "language")


def _apply_positive_signals(dimension_scores: Dict[str, float], analysis: ReportAnalysis) -> None:
    if len(analysis.report_markdown) >= 1000:
        dimension_scores["structure"] = min(1.0, dimension_scores["structure"] + 0.05)

    if analysis.evidence_list and analysis.claims:
        dimension_scores["traceability"] = min(1.0, dimension_scores["traceability"] + 0.05)

    source_types = len(set(e.source_type for e in analysis.evidence_list if e.source_type))
    if source_types >= 3:
        dimension_scores["traceability"] = min(1.0, dimension_scores["traceability"] + 0.05)

    if analysis.competitors and len(analysis.competitors) >= 2:
        dimension_scores["competitor_coverage"] = min(1.0, dimension_scores["competitor_coverage"] + 0.05)

    if analysis.pm_insights or analysis.recommendations:
        dimension_scores["logic_recommendation"] = min(1.0, dimension_scores["logic_recommendation"] + 0.05)


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

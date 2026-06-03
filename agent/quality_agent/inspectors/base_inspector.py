"""Base inspection functions for report quality."""

from typing import List

from ..adapters.report_adapter import ReportAnalysis
from ..config import (
    IssueSeverity,
    IssueType,
    QualityIssue,
    is_navigation_url,
)

# 检查声明与证据的链接完整性
def check_claim_evidence_linkage(analysis: ReportAnalysis) -> List[QualityIssue]:
    """Check claim-evidence linkage completeness."""
    issues: List[QualityIssue] = []
    
    # 收集所有存在的证据的ID
    evidence_ids = {e.source_id for e in analysis.evidence_list if e.source_id}
    
    # 检查每个声明是否有证据支持
    for claim in analysis.claims:
        claim_id = claim.get("claim_id", "")
        evidence_ids_in_claim = claim.get("evidence_ids", [])
        
        # 检查声明是否有证据支持
        if not evidence_ids_in_claim:
            issues.append(QualityIssue(
                type=IssueType.WEAK_EVIDENCE_SUPPORT,
                severity=IssueSeverity.MAJOR,
                description=f"声明 {claim_id} 缺少证据支持",
                suggestion="为该声明添加相关证据来源",
                explanation="每个声明都需要有证据支持以保证可信度",
                impact="无证据支持的声明会降低报告可信度",
                confidence=claim.get("confidence", 1.0)
            ))
        else:
            # 检查声明引用的证据是否存在
            for ev_id in evidence_ids_in_claim:
                if ev_id not in evidence_ids:
                    issues.append(QualityIssue(
                        type=IssueType.MISSING_SOURCE,
                        severity=IssueSeverity.MINOR,
                        description=f"声明 {claim_id} 引用的证据 {ev_id} 不存在",
                        suggestion="验证证据ID是否正确",
                        explanation="证据引用应该指向有效的来源",
                        impact="无效的证据引用会影响可追溯性"
                    ))
    
    return issues


# 检查证据的质量
def check_evidence_quality(analysis: ReportAnalysis) -> List[QualityIssue]:
    """Check evidence quality."""
    issues: List[QualityIssue] = []
    
    # 检查每个证据的质量
    for evidence in analysis.evidence_list:
        if not evidence.url or len(evidence.url) < 10:
            issues.append(QualityIssue(
                type=IssueType.LOW_QUALITY_EVIDENCE,
                severity=IssueSeverity.MINOR,
                description=f"证据 '{evidence.title[:30]}...' URL无效或过短",
                suggestion="确保所有证据都有有效的来源URL",
                explanation="有效的URL是验证信息真实性的重要依据",
                impact="无效URL会影响信息的可验证性"
            ))
        
        # 检查证据是否为导航页面
        if is_navigation_url(evidence.url, evidence.title):
            issues.append(QualityIssue(
                type=IssueType.LOW_QUALITY_EVIDENCE,
                severity=IssueSeverity.MINOR,
                description=f"证据 '{evidence.title[:30]}...' 是导航页面",
                suggestion="替换为包含实际内容的页面链接",
                explanation="导航页面通常不包含有用的产品信息",
                impact="导航链接作为证据会降低分析质量"
            ))
        
        # 检查证据内容是否足够详细
        content_length = len(evidence.page_text) + len(evidence.snippet)
        if content_length < 100:
            issues.append(QualityIssue(
                type=IssueType.LOW_QUALITY_EVIDENCE,
                severity=IssueSeverity.MINOR,
                description=f"证据 '{evidence.title[:30]}...' 内容过短",
                suggestion="寻找包含更详细信息的来源",
                explanation="充足的内容是分析的基础",
                impact="内容不足可能导致分析不全面"
            ))
        
        # 检查证据置信度是否足够高
        if evidence.confidence < 0.6:
            issues.append(QualityIssue(
                type=IssueType.WEAK_EVIDENCE_SUPPORT,
                severity=IssueSeverity.MINOR,
                description=f"证据 '{evidence.title[:30]}...' 置信度较低 ({evidence.confidence:.2f})",
                suggestion="寻找更可靠的证据来源",
                explanation="低置信度证据会影响结论的可靠性",
                impact="过多低置信度证据会降低报告可信度"
            ))
    
    return issues
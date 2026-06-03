"""Main entry for report quality inspection."""

import os
from typing import Optional

try:
    from report_agent.models import ReportPackage
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from report_agent.models import ReportPackage

from .adapters import adapt_report_package
from .config import (
    ConfidenceLevel,
    InspectionMode,
    IssueSeverity,
    OutputFormat,
    ProductType,
    QualityConfig,
    QualityReport,
)
from .inspectors import (
    HybridInspector,
    check_claim_evidence_linkage,
    check_evidence_quality,
    check_report_structure,
    check_evidence_diversity,
    check_evidence_timeliness,
    check_competitor_coverage,
    check_logical_consistency,
    check_recommendation_feasibility,
)
from .inspectors.section_issue_inspector import build_final_body_section_issues
from .score_calculator import calculate_report_score, calculate_confidence_level


def inspect_report_package(
    package: ReportPackage,
    config: Optional[QualityConfig] = None,
    mode: Optional[InspectionMode] = None,
    llm_api_key: Optional[str] = None,
    llm_base_url: Optional[str] = None,
    llm_model: Optional[str] = None,
) -> QualityReport:
    """Inspect ReportPackage quality and return QualityReport.
    
    Supports hybrid inspection mode with LLM-assisted detection and 
    rule-based fallback/voting.
    
    Configuration priority:
    1. config parameter (highest)
    2. mode + individual parameters
    3. Environment variables
    4. Default values (lowest)
    
    Inspection dimensions:
    - Claim-evidence linkage
    - Evidence quality
    - Report structure
    - Evidence diversity
    - Evidence timeliness
    - Competitor coverage
    - Logical consistency
    - Recommendation feasibility
    - Confidence distribution
    - Semantic consistency (LLM-only)
    - Factual accuracy (LLM-only)
    - Analysis depth (LLM-only)
    - Language quality (LLM-only)
    
    Args:
        package: ReportPackage from report_agent
        config: QualityConfig - complete configuration object (recommended)
        mode: InspectionMode - inspection mode (overrides config if provided)
        llm_api_key: Optional LLM API key for LLM-assisted inspection
        llm_base_url: Optional LLM base URL
        llm_model: Optional LLM model name
        
    Returns:
        QualityReport: Quality inspection result
    """
    # Step 1: Load configuration
    active_config = config or QualityConfig.from_env()
    
    # Step 2: Apply overrides from individual parameters
    if mode is not None:
        active_config.inspection_mode = mode
    if llm_api_key is not None:
        active_config.llm_api_key = llm_api_key
        active_config.llm_enabled = True
    if llm_base_url is not None:
        active_config.llm_base_url = llm_base_url
    if llm_model is not None:
        active_config.llm_model = llm_model
    
    # Step 3: Adapt and transform
    analysis = adapt_report_package(package)
    
    # Step 4: Execute inspections based on config
    check_scope = os.getenv("REPORT_AGENT_QUALITY_CHECK_SCOPE", "acceptance").strip().lower()
    if check_scope in {"acceptance", "format", "workflow", "delivery"}:
        issues = _execute_acceptance_inspections(analysis)
    elif active_config.inspection_mode != InspectionMode.RULE_ONLY:
        # 使用混合检查器
        inspector = HybridInspector.from_config(active_config)
        issues = inspector.inspect(analysis)
    else:
        # 仅使用规则检查
        issues = _execute_rule_inspections(analysis)

    issues = build_final_body_section_issues(analysis, issues)
    
    # Step 3: Calculate score and confidence
    score = calculate_report_score(issues, analysis)
    confidence_level = calculate_confidence_level(score, issues)
    
    # Step 4: Generate suggestions
    suggestions = [issue.suggestion for issue in issues]
    
    # Step 5: Determine if human review is needed
    needs_human_review = (
        confidence_level == ConfidenceLevel.LOW or
        any(i.severity.name == 'CRITICAL' for i in issues) or
        score < 0.5
    )
    
    # Step 6: Collect low confidence reasons
    low_confidence_reasons = []
    if confidence_level == ConfidenceLevel.LOW:
        if score < 0.6:
            low_confidence_reasons.append("质检分数低于阈值")
        if any(i.severity.name == 'CRITICAL' for i in issues):
            low_confidence_reasons.append("存在严重问题")
        if len([i for i in issues if i.severity.name == 'MAJOR']) > 2:
            low_confidence_reasons.append("存在多个主要问题")
    
    # Calculate average evidence quality
    evidence_quality_avg = 1.0
    if analysis.evidence_list:
        evidence_quality_avg = sum(e.confidence for e in analysis.evidence_list) / len(analysis.evidence_list)
    
    report = QualityReport(
        passed=score >= 0.6,
        score=score,
        issues=issues,
        suggestions=suggestions,
        required_resources=[],
        confidence_level=confidence_level,
        needs_human_review=needs_human_review,
        low_confidence_reasons=low_confidence_reasons,
        evidence_quality_avg=evidence_quality_avg,
        domain_type=ProductType.SOFTWARE,
        inspection_time_sec=0.0,
        inspection_rounds=1
    )

    if active_config.output.save_results:
        formats = ("json",)
        if active_config.output.format == OutputFormat.MARKDOWN:
            formats = ("md",)
        elif active_config.output.format == OutputFormat.TEXT:
            formats = ("md",)
        elif active_config.output.format == OutputFormat.JSON:
            formats = ("json", "md")

        from .exporter import export_quality_report

        export_quality_report(
            report,
            task_id=package.task_id,
            source_report=package.task_id,
            output_dir=active_config.output.output_dir,
            formats=formats,
        )

    return report


def _execute_rule_inspections(analysis) -> list:
    """Execute all rule-based inspections."""
    issues = []
    
    # Basic checks
    issues.extend(check_claim_evidence_linkage(analysis))
    issues.extend(check_evidence_quality(analysis))
    
    # Structure checks
    issues.extend(check_report_structure(analysis))
    
    # Evidence checks
    issues.extend(check_evidence_diversity(analysis))
    issues.extend(check_evidence_timeliness(analysis))
    
    # Competitor checks
    issues.extend(check_competitor_coverage(analysis))
    
    # Logical checks
    issues.extend(check_logical_consistency(analysis))
    
    # Recommendation checks
    issues.extend(check_recommendation_feasibility(analysis))
    
    return issues


def _execute_acceptance_inspections(analysis) -> list:
    """Check only delivery format and workflow completeness.

    This mode intentionally avoids fact/evidence adjudication. Upstream search
    and analysis own factual correctness; the quality gate only verifies that
    the final report is structurally usable.
    """
    issues = []
    issues.extend(check_report_structure(analysis))
    issues.extend(
        issue
        for issue in check_competitor_coverage(analysis)
        if issue.severity == IssueSeverity.MINOR
    )
    issues.extend(check_recommendation_feasibility(analysis))
    return issues


def inspect(package: ReportPackage) -> QualityReport:
    """Simplified interface for report quality inspection."""
    return inspect_report_package(package)


def inspect_with_llm(
    package: ReportPackage,
    mode: InspectionMode = InspectionMode.HYBRID_VOTING,
    config: Optional[QualityConfig] = None,
    **kwargs
) -> QualityReport:
    """Inspect with LLM-assisted hybrid mode.
    
    Args:
        package: ReportPackage from report_agent
        mode: InspectionMode - inspection mode (overrides config if provided)
        config: QualityConfig - complete configuration object
        **kwargs: Additional LLM configuration (llm_api_key, llm_base_url, llm_model)
        
    Returns:
        QualityReport: Quality inspection result
    """
    return inspect_report_package(package, config=config, mode=mode, **kwargs)

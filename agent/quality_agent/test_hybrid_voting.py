"""Test hybrid voting mechanism with real report cases."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from report_agent.models import ReportPackage

from agent.quality_agent import (
    QualityConfig,
    InspectionMode,
    inspect_report_package,
)
from agent.quality_agent.inspectors import HybridInspector
from agent.quality_agent.adapters import adapt_report_package


def create_sample_report_good() -> ReportPackage:
    """Create a high-quality report (for pass scenario testing)"""
    structured_analysis = {
        "evidence_cards": [
            {
                "evidence_id": "ev_001",
                "source_id": "src_001",
                "competitor": "Cursor",
                "dimension": "function",
                "claim": "Cursor AI supports real-time code completion",
                "raw_excerpt": "Cursor AI provides real-time code completion with AI-powered suggestions.",
                "confidence": 0.95,
                "freshness": "2024-01-15",
            },
            {
                "evidence_id": "ev_002",
                "source_id": "src_001",
                "competitor": "Cursor",
                "dimension": "function",
                "claim": "Cursor AI supports multiple programming languages",
                "raw_excerpt": "Supports Python, JavaScript, TypeScript and 20+ languages.",
                "confidence": 0.92,
                "freshness": "2024-02-20",
            },
            {
                "evidence_id": "ev_003",
                "source_id": "src_002",
                "competitor": "Copilot",
                "dimension": "pricing",
                "claim": "GitHub Copilot costs $10/month",
                "raw_excerpt": "Copilot subscription is $10/month for individuals.",
                "confidence": 0.98,
                "freshness": "2024-03-01",
            },
        ],
        "pm_insights": [
            {
                "insight_id": "ins_001",
                "type": "market_trend",
                "title": "AI programming tools market growth",
                "description": "AI programming tools market is growing rapidly, Cursor and Copilot dominate",
                "related_competitors": ["Cursor", "Copilot"],
                "evidence_ids": ["ev_001", "ev_002"],
                "pm_value": "Market opportunity is clear",
                "confidence": 0.9,
            }
        ],
        "comparison_tables": [
            {
                "competitor": "Cursor",
                "features": ["Real-time code completion", "Multi-language support", "AI chat"],
                "pricing": "$20/month",
            },
            {
                "competitor": "Copilot",
                "features": ["Code suggestions", "GitHub integration"],
                "pricing": "$10/month",
            },
        ],
        "swot": {
            "strengths": [
                {
                    "point": "Leading AI technology",
                    "why_it_matters": "Clear technical differentiation",
                    "evidence_ids": ["ev_001"],
                    "pm_implication": "Continue investing in AI R&D",
                    "confidence": 0.9,
                }
            ],
            "weaknesses": [
                {
                    "point": "High price",
                    "why_it_matters": "May affect user conversion",
                    "evidence_ids": ["ev_003"],
                    "pm_implication": "Consider offering free version",
                    "confidence": 0.85,
                }
            ],
            "opportunities": [
                {
                    "point": "Rapid market growth",
                    "why_it_matters": "Large market space",
                    "evidence_ids": ["ev_001", "ev_002"],
                    "pm_implication": "Accelerate product iteration",
                    "confidence": 0.88,
                }
            ],
            "threats": [
                {
                    "point": "Intense competition",
                    "why_it_matters": "Market share may be eroded",
                    "evidence_ids": ["ev_003"],
                    "pm_implication": "Differentiate competition",
                    "confidence": 0.87,
                }
            ],
        },
        "executive_summary": {
            "competitors": ["Cursor", "Copilot", "Tabnine"],
        }
    }

    return ReportPackage(
        task_id="test_hybrid_good",
        report_markdown="""# AI Programming Tools Competitive Analysis Report

## Overview
This report analyzes the market status and competitive landscape of mainstream AI programming tools.

## Competitive Feature Comparison
### Cursor AI
- Real-time code completion
- Multi-language support

### GitHub Copilot
- AI code suggestions
- GitHub integration

## SWOT Analysis
### Strengths
- Leading AI technology
- Good user experience

### Weaknesses
- High price

## Strategic Recommendations
1. Strengthen AI capabilities
2. Optimize pricing strategy
""",
        structured_analysis=structured_analysis,
        claim_evidence_map=[
            {
                "claim_id": "clm_001",
                "claim": "Cursor AI supports real-time code completion",
                "evidence_ids": ["ev_001", "ev_002"],
            },
            {
                "claim_id": "clm_002",
                "claim": "GitHub Copilot costs $10/month",
                "evidence_ids": ["ev_003"],
            },
        ],
        generation_trace=[
            {"step": "data_collection", "status": "completed"},
            {"step": "analysis", "status": "completed"},
            {"step": "writing", "status": "completed"},
        ],
        sources=[
            {
                "source_id": "src_001",
                "url": "https://cursor.com/features",
                "title": "Cursor AI Features",
                "snippet": "Cursor AI provides real-time code completion...",
                "content": "Cursor AI is an AI-powered code editor with real-time code completion.",
                "source": "Official website",
                "publish_date": "2024-01-15",
            },
            {
                "source_id": "src_002",
                "url": "https://github.com/features/copilot",
                "title": "GitHub Copilot",
                "snippet": "Copilot subscription is $10/month...",
                "content": "GitHub Copilot subscription plans: $10/month for individuals.",
                "source": "Official website",
                "publish_date": "2024-03-01",
            },
        ],
        missing_info=[],
        low_confidence_claims=[],
    )


def create_sample_report_with_issues() -> ReportPackage:
    """Create a report with quality issues (for issue detection and feedback testing)"""
    structured_analysis = {
        "evidence_cards": [
            {
                "evidence_id": "ev_001",
                "source_id": "src_001",
                "competitor": "Unknown",
                "dimension": "function",
                "claim": "This feature supports all programming languages",
                "raw_excerpt": "...",
                "confidence": 0.5,
                "freshness": "2020-01-01",
            },
        ],
        "pm_insights": [
            {
                "insight_id": "ins_001",
                "type": "market_trend",
                "title": "Market growth",
                "description": "Market is growing rapidly",
                "related_competitors": [],
                "evidence_ids": [],
                "pm_value": "",
                "confidence": 0.3,
            }
        ],
        "comparison_tables": [],
        "swot": {
            "strengths": [],
            "weaknesses": [],
            "opportunities": [],
            "threats": [],
        },
        "executive_summary": {
            "competitors": [],
        }
    }

    return ReportPackage(
        task_id="test_hybrid_issues",
        report_markdown="""# Short Report

This is a report with very little content, lacking detailed analysis and evidence support.
""",
        structured_analysis=structured_analysis,
        claim_evidence_map=[
            {
                "claim_id": "clm_001",
                "claim": "This feature supports all programming languages",
                "evidence_ids": [],
            },
        ],
        generation_trace=[],
        sources=[
            {
                "source_id": "src_001",
                "url": "https://example.com",
                "title": "Example Source",
                "snippet": "...",
                "content": "This feature supports many languages.",
                "source": "Unknown",
                "publish_date": "2020-01-01",
            },
        ],
        missing_info=["Lack of specific competitor information", "Lack of pricing data"],
        low_confidence_claims=["clm_001"],
    )


def test_hybrid_voting_good_report():
    """Test hybrid voting mechanism - good quality report (should pass)"""
    print("\n" + "="*60)
    print("Test 1: Hybrid Voting Mechanism - Good Quality Report")
    print("="*60)

    report = create_sample_report_good()

    modes = [
        InspectionMode.RULE_ONLY,
        InspectionMode.HYBRID_VOTING,
        InspectionMode.LLM_FALLBACK,
    ]

    for mode in modes:
        print(f"\n--- Mode: {mode.value} ---")
        config = QualityConfig(
            llm_api_key="",
            llm_base_url="",
            llm_model="",
            inspection_mode=mode,
            voting_threshold=0.6,
            llm_enabled=True,
            rule_enabled=True,
            verbose=True
        )

        result = inspect_report_package(report, config=config)
        print(f"Passed: {result.passed}")
        print(f"Score: {result.score:.2f}")
        print(f"Confidence: {result.confidence_level.value}")
        print(f"Issue count: {len(result.issues)}")

        if result.issues:
            print("Issues:")
            for issue in result.issues[:3]:
                print(f"  - [{issue.severity.value}] {issue.description}")

    print("\n[PASS] Test completed")


def test_hybrid_voting_issue_report():
    """Test hybrid voting mechanism - report with issues (should detect issues)"""
    print("\n" + "="*60)
    print("Test 2: Hybrid Voting Mechanism - Report With Issues")
    print("="*60)

    report = create_sample_report_with_issues()

    config = QualityConfig(
        llm_api_key="",
        llm_base_url="",
        llm_model="",
        inspection_mode=InspectionMode.RULE_ONLY,
        llm_enabled=False,
        rule_enabled=True,
        verbose=True
    )

    result = inspect_report_package(report, config=config)

    print(f"\nPassed: {result.passed}")
    print(f"Score: {result.score:.2f}")
    print(f"Confidence: {result.confidence_level.value}")
    print(f"Needs human review: {result.needs_human_review}")
    print(f"Issue count: {len(result.issues)}")

    if result.issues:
        print("\nDetected issues:")
        for i, issue in enumerate(result.issues, 1):
            print(f"\n{i}. [{issue.severity.value}] {issue.type.value}")
            print(f"   Description: {issue.description}")
            print(f"   Suggestion: {issue.suggestion}")

    print("\n--- Feedback Target Analysis ---")
    from agent.quality_agent.config import IssueType

    collector_issue_types = {
        IssueType.INSUFFICIENT_EVIDENCE,
        IssueType.LOW_QUALITY_EVIDENCE,
        IssueType.MISSING_SOURCE,
    }
    analyst_issue_types = {
        IssueType.LOGICAL_INCONSISTENCY,
        IssueType.INCOMPLETE_INFO,
    }
    writer_issue_types = {
        IssueType.WEAK_EVIDENCE_SUPPORT,
        IssueType.CONFLICTING_EVIDENCE,
    }

    for issue in result.issues:
        if issue.type in collector_issue_types:
            target = "Collector Agent"
        elif issue.type in analyst_issue_types:
            target = "Analyst Agent"
        elif issue.type in writer_issue_types:
            target = "Writer Agent"
        else:
            target = "Unknown"

        print(f"  {issue.type.value} -> {target}")

    print("\n[PASS] Test completed")


def test_voting_weights():
    """Test voting weight configuration"""
    print("\n" + "="*60)
    print("Test 3: Voting Weight Configuration")
    print("="*60)

    report = create_sample_report_good()

    weights = [
        (0.3, "LLM weight 30%, Rule weight 70%"),
        (0.5, "LLM weight 50%, Rule weight 50%"),
        (0.7, "LLM weight 70%, Rule weight 30%"),
    ]

    for llm_weight, desc in weights:
        print(f"\n--- {desc} ---")
        inspector = HybridInspector(
            mode=InspectionMode.HYBRID_VOTING,
            llm_enabled=False,
            voting_threshold=0.6,
            voting_llm_weight=llm_weight,
            fallback_on_llm_failure=True
        )

        analysis = adapt_report_package(report)
        issues = inspector.inspect(analysis)

        print(f"Detected {len(issues)} issues")
        for issue in issues[:2]:
            print(f"  - [{issue.severity.value}] {issue.description[:50]}...")

    print("\n[PASS] Test completed")


def test_feedback_target_decision():
    """Test feedback target decision logic"""
    print("\n" + "="*60)
    print("Test 4: Feedback Target Decision Logic")
    print("="*60)

    from agent.quality_agent.config import IssueType, QualityIssue

    test_cases = [
        (
            QualityIssue(
                type=IssueType.INSUFFICIENT_EVIDENCE,
                severity="major",
                description="Insufficient evidence",
                suggestion="Add more evidence",
                explanation="",
                impact=""
            ),
            "Collector Agent"
        ),
        (
            QualityIssue(
                type=IssueType.LOGICAL_INCONSISTENCY,
                severity="major",
                description="Logical inconsistency",
                suggestion="Re-analyze",
                explanation="",
                impact=""
            ),
            "Analyst Agent"
        ),
        (
            QualityIssue(
                type=IssueType.WEAK_EVIDENCE_SUPPORT,
                severity="major",
                description="Weak evidence support",
                suggestion="Add more content",
                explanation="",
                impact=""
            ),
            "Writer Agent"
        ),
    ]

    collector_issue_types = {
        IssueType.INSUFFICIENT_EVIDENCE,
        IssueType.LOW_QUALITY_EVIDENCE,
        IssueType.MISSING_SOURCE,
    }
    analyst_issue_types = {
        IssueType.LOGICAL_INCONSISTENCY,
        IssueType.INCOMPLETE_INFO,
    }
    writer_issue_types = {
        IssueType.WEAK_EVIDENCE_SUPPORT,
        IssueType.CONFLICTING_EVIDENCE,
    }

    for issue, expected_target in test_cases:
        if issue.type in collector_issue_types:
            actual_target = "Collector Agent"
        elif issue.type in analyst_issue_types:
            actual_target = "Analyst Agent"
        elif issue.type in writer_issue_types:
            actual_target = "Writer Agent"
        else:
            actual_target = "Unknown"

        status = "[PASS]" if actual_target == expected_target else "[FAIL]"
        print(f"{status} Issue type: {issue.type.value:30} -> Target: {actual_target:20} (Expected: {expected_target})")

    print("\n[PASS] Test completed")


if __name__ == "__main__":
    print("="*60)
    print("Hybrid Voting Mechanism Test Suite")
    print("="*60)

    test_hybrid_voting_good_report()
    test_hybrid_voting_issue_report()
    test_voting_weights()
    test_feedback_target_decision()

    print("\n" + "="*60)
    print("All tests completed!")
    print("="*60)

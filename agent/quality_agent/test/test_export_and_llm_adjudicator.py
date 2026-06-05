"""Tests for quality report export and LLM semantic adjudication."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agent.quality_agent import (
    ConfidenceLevel,
    IssueSeverity,
    IssueType,
    ProductType,
    QualityIssue,
    QualityReport,
    export_quality_report,
    quality_report_to_dict,
    quality_report_to_markdown,
)
from agent.quality_agent.adapters.report_adapter import ReportAnalysis, ReportEvidence
from agent.quality_agent.inspectors.llm_inspector import LLMInspector


def _sample_quality_report() -> QualityReport:
    return QualityReport(
        passed=False,
        score=0.58,
        issues=[
            QualityIssue(
                type=IssueType.WEAK_EVIDENCE_SUPPORT,
                severity=IssueSeverity.MAJOR,
                description="Recommendation is not supported by cited evidence",
                suggestion="Add evidence or narrow the recommendation",
                confidence=0.82,
                affected_fields=["recommendation_derivation", "ev_001"],
            )
        ],
        suggestions=["Add evidence or narrow the recommendation"],
        required_resources=[],
        confidence_level=ConfidenceLevel.MEDIUM,
        needs_human_review=False,
        evidence_quality_avg=0.76,
        domain_type=ProductType.SOFTWARE,
    )


def test_quality_report_export_json_and_markdown():
    report = _sample_quality_report()
    output_dir = Path("reports/quality_inspections_test")

    exported = export_quality_report(
        report,
        task_id="task_001",
        source_report="reports/input.md",
        output_dir=str(output_dir),
        formats=("json", "md"),
    )

    assert set(exported) == {"json", "md"}
    payload = json.loads(Path(exported["json"]).read_text(encoding="utf-8"))
    markdown = Path(exported["md"]).read_text(encoding="utf-8")

    assert payload["task_id"] == "task_001"
    assert payload["issue_count"] == 1
    assert payload["feedback_payload"]["retry_required"] is True
    assert "# Quality Inspection Report" in markdown
    assert "Recommendation is not supported" in markdown


def test_quality_report_serializers_include_feedback_payload():
    report = _sample_quality_report()

    payload = quality_report_to_dict(report, task_id="task_002")
    markdown = quality_report_to_markdown(report, task_id="task_002")

    assert payload["feedback_payload"]["task_id"] == "task_002"
    assert "Feedback By Agent" in markdown


class _FakeResponse:
    content = json.dumps({
        "issues": [
            {
                "dimension": "swot_evidence_consistency",
                "issue_type": "logical_inconsistency",
                "severity": "MAJOR",
                "description": "SWOT opportunity is not grounded in evidence",
                "suggestion": "Tie the opportunity to a cited market signal",
                "evidence_ids": ["ev_001"],
                "confidence": 0.88,
            }
        ]
    })


class _FakeClient:
    def invoke(self, prompt):
        assert "swot_evidence_consistency" in prompt
        assert "recommendation_derivation" in prompt
        return _FakeResponse()


def test_llm_quality_dimension_adjudicator_maps_response_to_issue():
    analysis = ReportAnalysis(
        task_id="task_003",
        product_name="AI IDE",
        evidence_list=[
            ReportEvidence(
                title="Market signal",
                url="https://example.com",
                snippet="Market demand is increasing.",
                confidence=0.9,
                source_id="ev_001",
            )
        ],
        claims=[{"claim": "Demand is increasing", "evidence_ids": ["ev_001"]}],
        pm_insights=[],
        swot={"opportunities": [{"point": "Enterprise migration demand"}]},
        recommendations=[{"action": "Prioritize enterprise migration tools"}],
        report_markdown="# Report\n## SWOT\nOpportunity without enough detail",
        competitors=["CodeBuddy", "Qoder"],
        comparison_tables=[],
    )
    inspector = LLMInspector(enabled=True)
    inspector._client = _FakeClient()

    issues = inspector.adjudicate_quality_dimensions(analysis)

    assert len(issues) == 1
    assert issues[0].type == IssueType.LOGICAL_INCONSISTENCY
    assert issues[0].severity == IssueSeverity.MAJOR
    assert "swot_evidence_consistency" in issues[0].affected_fields
    assert "ev_001" in issues[0].affected_fields

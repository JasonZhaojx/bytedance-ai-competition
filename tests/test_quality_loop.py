from __future__ import annotations

from dataclasses import dataclass

from agent.quality_agent.config import (
    ConfidenceLevel,
    InspectionMode,
    IssueSeverity,
    IssueType,
    QualityConfig,
    QualityIssue,
    QualityReport,
)
from report_agent.models import WritingAgentConfig
from workflows.quality_loop import choose_retry_target, run_quality_loop
from workflows.quality_loop_schema import RetryTarget, WorkflowStatus


@dataclass
class FakeSearchBundle:
    queries: list[str]
    results: list[dict]
    errors: list[str]


def _quality_report(*, passed: bool, issues: list[QualityIssue] | None = None) -> QualityReport:
    return QualityReport(
        passed=passed,
        score=1.0 if passed else 0.4,
        issues=issues or [],
        suggestions=[issue.suggestion for issue in issues or []],
        required_resources=[],
        confidence_level=ConfidenceLevel.HIGH,
    )


def test_choose_retry_target_prioritizes_upstream_agents() -> None:
    payload = {
        "retry_required": True,
        "grouped_by_agent": {
            "writer_agent": [{"issue_type": "incomplete_info"}],
            "collector_agent": [{"issue_type": "missing_source"}],
        },
    }

    assert choose_retry_target(payload) == RetryTarget.COLLECTOR


def test_quality_loop_retries_writer_then_passes(monkeypatch) -> None:
    import workflows.quality_loop as quality_loop

    monkeypatch.setattr(
        quality_loop,
        "search_for_report",
        lambda *args, **kwargs: FakeSearchBundle(
            queries=["demo query"],
            results=[
                {
                    "title": "Demo competitor launch",
                    "url": "https://example.com/demo",
                    "snippet": "Demo competitor focuses on onboarding and pricing.",
                    "content": (
                        "Demo competitor focuses on onboarding and pricing. "
                        "It has clear product evidence for comparison."
                    ),
                    "source": "fake",
                }
            ],
            errors=[],
        ),
    )

    first_issue = QualityIssue(
        type=IssueType.INCOMPLETE_INFO,
        severity=IssueSeverity.MAJOR,
        description="报告结构需要补充",
        suggestion="请 writer_agent 补充缺失章节",
    )
    reports = [
        _quality_report(passed=False, issues=[first_issue]),
        _quality_report(passed=True),
    ]

    monkeypatch.setattr(
        quality_loop,
        "inspect_report_package",
        lambda *args, **kwargs: reports.pop(0),
    )

    result = run_quality_loop(
        "demo product",
        competitors=["Demo"],
        task_id="test_quality_loop",
        max_iterations=3,
        writing_config=WritingAgentConfig(use_llm=False, verbose=False),
        quality_config=QualityConfig(inspection_mode=InspectionMode.RULE_ONLY),
    )

    assert result.passed is True
    assert result.state.status == WorkflowStatus.APPROVED
    assert result.state.iteration_count == 2
    assert result.state.history[0]["retry_target"] == RetryTarget.WRITER.value
    assert result.report_package is not None
    assert result.report_package.missing_info
    assert any(
        item.get("step") == "writer_feedback_constraints"
        for item in result.report_package.generation_trace
    )


def test_collector_retry_uses_feedback_search_queries(monkeypatch) -> None:
    import workflows.quality_loop as quality_loop

    extra_query_calls: list[list[str]] = []

    def fake_search_for_report(*args, **kwargs):
        extra_query_calls.append(list(kwargs.get("extra_queries") or []))
        return FakeSearchBundle(
            queries=["base query", *extra_query_calls[-1]],
            results=[
                {
                    "title": "Demo official evidence",
                    "url": "https://example.com/demo-official",
                    "snippet": "Official evidence for Demo.",
                    "content": "Official evidence for Demo pricing and source quality.",
                    "source": "fake",
                }
            ],
            errors=[],
        )

    monkeypatch.setattr(quality_loop, "search_for_report", fake_search_for_report)

    first_issue = QualityIssue(
        type=IssueType.MISSING_SOURCE,
        severity=IssueSeverity.MAJOR,
        description="缺少官方来源",
        suggestion="补充官方来源和可追溯证据",
        affected_fields=["sources", "claim_evidence_map"],
    )
    reports = [
        _quality_report(passed=False, issues=[first_issue]),
        _quality_report(passed=True),
    ]
    monkeypatch.setattr(
        quality_loop,
        "inspect_report_package",
        lambda *args, **kwargs: reports.pop(0),
    )

    result = run_quality_loop(
        "demo product",
        competitors=["Demo"],
        task_id="test_collector_retry",
        max_iterations=3,
        writing_config=WritingAgentConfig(use_llm=False, verbose=False),
        quality_config=QualityConfig(inspection_mode=InspectionMode.RULE_ONLY),
    )

    assert result.passed is True
    assert result.state.history[0]["retry_target"] == RetryTarget.COLLECTOR.value
    assert extra_query_calls[0] == []
    assert extra_query_calls[1]
    assert any("官方" in query for query in extra_query_calls[1])

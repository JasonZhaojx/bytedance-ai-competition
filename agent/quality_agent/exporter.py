"""Export quality inspection reports for humans and workflow systems."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable

from .config import QualityIssue, QualityReport
from .feedback import build_feedback_payload


def _serialize(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if is_dataclass(value):
        return {
            key: _serialize(item)
            for key, item in asdict(value).items()
        }
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    return value


def _issue_to_dict(issue: QualityIssue) -> Dict[str, Any]:
    return {
        "type": issue.type.value,
        "severity": issue.severity.value,
        "description": issue.description,
        "suggestion": issue.suggestion,
        "explanation": issue.explanation,
        "impact": issue.impact,
        "confidence": issue.confidence,
        "affected_fields": issue.affected_fields,
    }


def quality_report_to_dict(
    report: QualityReport,
    task_id: str = "",
    source_report: str = "",
) -> Dict[str, Any]:
    """Convert a QualityReport into a stable JSON-serializable payload."""
    return {
        "task_id": task_id,
        "source_report": source_report,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "passed": report.passed,
        "score": report.score,
        "confidence_level": report.confidence_level.value,
        "needs_human_review": report.needs_human_review,
        "low_confidence_reasons": report.low_confidence_reasons,
        "evidence_quality_avg": report.evidence_quality_avg,
        "domain_type": report.domain_type.value,
        "inspection_time_sec": report.inspection_time_sec,
        "inspection_rounds": report.inspection_rounds,
        "llm_score": report.llm_score,
        "rule_score": report.rule_score,
        "final_decision": report.final_decision,
        "issue_count": len(report.issues),
        "issues": [_issue_to_dict(issue) for issue in report.issues],
        "suggestions": report.suggestions,
        "required_resources": report.required_resources,
        "feedback_payload": build_feedback_payload(report, task_id),
    }


def quality_report_to_markdown(
    report: QualityReport,
    task_id: str = "",
    source_report: str = "",
) -> str:
    """Render a concise human-readable inspection report."""
    payload = build_feedback_payload(report, task_id)
    lines = [
        "# Quality Inspection Report",
        "",
        f"- Task ID: {task_id or '-'}",
        f"- Source report: {source_report or '-'}",
        f"- Passed: {report.passed}",
        f"- Score: {report.score:.2f}",
        f"- Confidence: {report.confidence_level.value}",
        f"- Needs human review: {report.needs_human_review}",
        f"- Evidence quality avg: {report.evidence_quality_avg:.2f}",
        "",
    ]

    if report.low_confidence_reasons:
        lines.extend(["## Low Confidence Reasons", ""])
        lines.extend(f"- {reason}" for reason in report.low_confidence_reasons)
        lines.append("")

    lines.extend(["## Issues", ""])
    if report.issues:
        lines.append("| Severity | Type | Description | Suggestion | Confidence |")
        lines.append("| --- | --- | --- | --- | --- |")
        for issue in report.issues:
            lines.append(
                "| "
                + " | ".join([
                    issue.severity.value,
                    issue.type.value,
                    issue.description.replace("|", "\\|"),
                    issue.suggestion.replace("|", "\\|"),
                    f"{issue.confidence:.2f}",
                ])
                + " |"
            )
    else:
        lines.append("No issues found.")
    lines.append("")

    lines.extend(["## Suggestions", ""])
    if report.suggestions:
        lines.extend(f"- {suggestion}" for suggestion in report.suggestions)
    else:
        lines.append("- No action required.")
    lines.append("")

    lines.extend(["## Feedback By Agent", ""])
    grouped = payload.get("grouped_by_agent", {})
    if grouped:
        for agent, messages in grouped.items():
            lines.append(f"### {agent}")
            for message in messages:
                lines.append(
                    f"- [{message['priority']}] {message['description']} -> "
                    f"{message['suggested_fix']}"
                )
            lines.append("")
    else:
        lines.append("No retry feedback generated.")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def export_quality_report(
    report: QualityReport,
    task_id: str = "",
    source_report: str = "",
    output_dir: str = "reports/quality_inspections",
    formats: Iterable[str] = ("json", "md"),
) -> Dict[str, str]:
    """Write quality inspection outputs and return paths by format."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_task_id = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in task_id)
    stem = f"{timestamp}_{safe_task_id or 'quality_report'}"
    exported: Dict[str, str] = {}

    normalized_formats = {fmt.lower() for fmt in formats}
    if "markdown" in normalized_formats:
        normalized_formats.add("md")

    if "json" in normalized_formats:
        json_path = output_path / f"{stem}.json"
        json_path.write_text(
            json.dumps(
                _serialize(quality_report_to_dict(report, task_id, source_report)),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        exported["json"] = str(json_path)

    if "md" in normalized_formats:
        markdown_path = output_path / f"{stem}.md"
        markdown_path.write_text(
            quality_report_to_markdown(report, task_id, source_report),
            encoding="utf-8",
        )
        exported["md"] = str(markdown_path)

    return exported

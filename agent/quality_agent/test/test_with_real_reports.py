"""Smoke test quality_agent with markdown reports from reports/."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from report_agent.models import ReportPackage
from agent.quality_agent import (
    InspectionMode,
    LLMConfig,
    QualityConfig,
    inspect_report_package,
)


def test_latest_markdown_report_can_be_inspected():
    reports_dir = Path(__file__).resolve().parents[3] / "reports"
    report_files = sorted(reports_dir.glob("*.md"))
    assert report_files, "reports/ should contain at least one markdown report"

    report_file = report_files[-1]
    package = ReportPackage(
        task_id=report_file.stem,
        report_markdown=report_file.read_text(encoding="utf-8"),
        structured_analysis={},
        claim_evidence_map=[],
        generation_trace=[],
        sources=[],
    )
    config = QualityConfig(
        inspection_mode=InspectionMode.RULE_ONLY,
        llm=LLMConfig(enabled=False),
    )

    result = inspect_report_package(package, config=config)

    assert 0 <= result.score <= 1
    assert result.confidence_level.value in {"high", "medium", "low"}

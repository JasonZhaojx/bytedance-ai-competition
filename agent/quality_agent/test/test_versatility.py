"""Smoke tests for product-type versatility."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from report_agent.models import ReportPackage
from agent.quality_agent import (
    InspectionMode,
    LLMConfig,
    OutputConfig,
    ProductType,
    QualityConfig,
    inspect_report_package,
)


def make_config() -> QualityConfig:
    return QualityConfig(
        inspection_mode=InspectionMode.RULE_ONLY,
        llm=LLMConfig(enabled=False),
        min_score_threshold=0.5,
        min_evidence_count=1,
        output=OutputConfig(verbose=False),
    )


def make_package(task_id: str, markdown: str) -> ReportPackage:
    return ReportPackage(
        task_id=task_id,
        report_markdown=markdown,
        structured_analysis={},
        claim_evidence_map=[],
        generation_trace=[],
        sources=[],
    )


def test_ai_tool_report_inspection_smoke():
    package = make_package(
        "codebuddy",
        "# CodeBuddy AI IDE report\n\n"
        "## 核心结论\nAI coding IDE assistant with code completion.\n\n"
        "## 竞品分析\nCodeBuddy supports VS Code and agent workflow.\n\n"
        "## SWOT分析\nStrengths, Weaknesses, Opportunities, Threats.\n\n"
        "## 策略建议\n1. Improve plugin migration.\n\n"
        "## 结论\nUseful for AI coding teams.\n\n"
        "[source](https://example.com)",
    )
    report = inspect_report_package(package, make_config())
    assert report.domain_type == ProductType.SOFTWARE


def test_empty_markdown_stays_low_confidence():
    report = inspect_report_package(make_package("empty", ""), make_config())
    assert not report.passed

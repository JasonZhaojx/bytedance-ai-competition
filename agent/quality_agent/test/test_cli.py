"""Tests for quality_agent report-file CLI helpers."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agent.quality_agent.cli import _load_report_package


class _FakePath:
    def __init__(self, name: str, text: str):
        self.name = name
        self.suffix = Path(name).suffix
        self.stem = Path(name).stem
        self._text = text

    def read_text(self, encoding: str = "utf-8") -> str:
        return self._text

    def __str__(self) -> str:
        return self.name


def test_load_markdown_report_package():
    path = _FakePath("report.md", "# Report\n\n## 选购建议\n- Buy the suitable option.")

    package = _load_report_package(path)

    assert package.task_id == "report"
    assert "选购建议" in package.report_markdown
    assert package.structured_analysis == {}


def test_load_structured_report_agent_markdown():
    payload = {
        "task_id": "task_123",
        "report_markdown": "# Structured Report",
        "structured_analysis": {"recommendations": []},
        "claim_evidence_map": [],
        "generation_trace": [],
        "sources": [],
    }
    path = _FakePath(
        "report_agent.md",
            "# Human preview\n\n===== STRUCTURED ANALYSIS JSON =====\n"
            + json.dumps(payload, ensure_ascii=False),
    )

    package = _load_report_package(path)

    assert package.task_id == "task_123"
    assert package.report_markdown == "# Structured Report"
    assert package.structured_analysis == {"recommendations": []}

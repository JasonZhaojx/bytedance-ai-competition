"""Artifact persistence helpers for workflow observability."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Sequence

from agent.quality_agent.config import QualityReport
from report_agent.models import ReportPackage


def write_round_artifacts(
    *,
    output_dir: Path,
    task_id: str,
    round_index: int,
    queries: Sequence[str],
    search_results: Sequence[Any],
    search_errors: Sequence[str],
    report_package: ReportPackage | None,
    quality_report: QualityReport | None,
    feedback_payload: Dict[str, Any],
    feedback_search_queries: Sequence[str] = (),
    writer_constraints: Sequence[Dict[str, Any]] = (),
) -> Dict[str, str]:
    """Write one workflow round of inputs, outputs, quality, and feedback."""

    round_dir = output_dir / _safe_filename(task_id) / f"round_{round_index:02d}"
    round_dir.mkdir(parents=True, exist_ok=True)

    paths: Dict[str, str] = {}
    paths["search_results"] = _write_json(
        round_dir / "search_results.json",
        {
            "queries": list(queries),
            "search_errors": list(search_errors),
            "search_results": [_to_plain(item) for item in search_results],
        },
    )

    if report_package is not None:
        paths["report_markdown"] = _write_text(
            round_dir / "report.md",
            report_package.report_markdown,
        )
        paths["report_package"] = _write_text(
            round_dir / "report_package.json",
            report_package.to_json(),
        )

    if quality_report is not None:
        paths["quality_report"] = _write_json(
            round_dir / "quality_report.json",
            _to_plain(quality_report),
        )

    paths["feedback_payload"] = _write_json(
        round_dir / "feedback_payload.json",
        feedback_payload,
    )
    if feedback_search_queries:
        paths["feedback_search_queries"] = _write_json(
            round_dir / "feedback_search_queries.json",
            list(feedback_search_queries),
        )
    if writer_constraints:
        paths["writer_constraints"] = _write_json(
            round_dir / "writer_constraints.json",
            list(writer_constraints),
        )
    return paths


def write_final_artifact(
    *,
    output_dir: Path,
    task_id: str,
    payload: Dict[str, Any],
) -> str:
    final_dir = output_dir / _safe_filename(task_id)
    final_dir.mkdir(parents=True, exist_ok=True)
    return _write_json(final_dir / "final_result.json", payload)


def _write_json(path: Path, payload: Any) -> str:
    path.write_text(
        json.dumps(_to_plain(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(path)


def _write_text(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def _to_plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _to_plain(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain(item) for item in value]
    return value


def _safe_filename(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)
    return safe.strip("_") or "workflow_task"

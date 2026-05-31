"""Command-line entry point for inspecting report files with quality_agent."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency fallback
    load_dotenv = None

try:
    from report_agent.models import ReportPackage
except ImportError:  # pragma: no cover - direct script execution fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from report_agent.models import ReportPackage

from .config import InspectionMode, LLMConfig, OutputConfig, OutputFormat, QualityConfig
from .report_quality_agent import inspect_report_package


ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT / "reports"
STRUCTURED_MARKER = "===== STRUCTURED ANALYSIS JSON ====="


def _load_env() -> None:
    if load_dotenv:
        load_dotenv(ROOT / ".env")


def _resolve_report_path(value: str) -> Path:
    candidate = Path(value)
    if candidate.exists():
        return candidate

    report_candidate = REPORTS_DIR / value
    if report_candidate.exists():
        return report_candidate

    if not candidate.suffix:
        for suffix in (".md", ".json"):
            report_candidate = REPORTS_DIR / f"{value}{suffix}"
            if report_candidate.exists():
                return report_candidate

    raise FileNotFoundError(
        f"Report not found: {value}. Pass a path or a filename under reports/."
    )


def _package_from_structured_payload(path: Path, data: Dict[str, Any]) -> ReportPackage:
    return ReportPackage(
        task_id=str(data.get("task_id") or path.stem),
        report_markdown=str(data.get("report_markdown") or ""),
        structured_analysis=data.get("structured_analysis") or {},
        claim_evidence_map=data.get("claim_evidence_map") or [],
        generation_trace=data.get("generation_trace") or [],
        sources=data.get("sources") or [],
        missing_info=data.get("missing_info") or [],
        low_confidence_claims=data.get("low_confidence_claims") or [],
    )


def _load_report_package(path: Path) -> ReportPackage:
    text = path.read_text(encoding="utf-8")

    if path.suffix.lower() == ".json":
        data = json.loads(text)
        required_keys = {"report_markdown", "structured_analysis", "sources"}
        if required_keys.intersection(data):
            return _package_from_structured_payload(path, data)
        raise ValueError(
            f"{path} does not look like a report_agent ReportPackage JSON file."
        )

    if STRUCTURED_MARKER in text:
        json_text = text.split(STRUCTURED_MARKER, 1)[1].strip()
        return _package_from_structured_payload(path, json.loads(json_text))

    return ReportPackage(
        task_id=path.stem,
        report_markdown=text,
        structured_analysis={},
        claim_evidence_map=[],
        generation_trace=[],
        sources=[],
    )


def _build_config(args: argparse.Namespace) -> QualityConfig:
    if args.mode == "rule":
        mode = InspectionMode.RULE_ONLY
        llm_enabled = False
    elif args.mode == "llm":
        mode = InspectionMode.LLM_ONLY
        llm_enabled = True
    else:
        mode = InspectionMode.HYBRID_VOTING
        llm_enabled = True

    output_format = OutputFormat.MARKDOWN if args.output_format == "md" else OutputFormat.JSON
    return QualityConfig(
        inspection_mode=mode,
        llm=LLMConfig(
            enabled=llm_enabled,
            api_key=os.getenv("LLM_API_KEY") or os.getenv("ARK_API_KEY", ""),
            base_url=os.getenv("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
            model=os.getenv("LLM_MODEL", ""),
        ),
        output=OutputConfig(
            verbose=False,
            save_results=args.save,
            output_dir=args.output_dir,
            format=output_format,
        ),
    )


def _print_result(path: Path, result) -> None:
    print(f"report: {path}")
    print(f"score: {result.score:.4f}")
    print(f"passed: {result.passed}")
    print(f"confidence: {result.confidence_level.value}")
    print(f"needs_human_review: {result.needs_human_review}")
    print(f"issues: {len(result.issues)}")

    for index, issue in enumerate(result.issues, 1):
        print(
            f"{index}. [{issue.severity.value}] {issue.type.value}: "
            f"{issue.description} -> {issue.suggestion}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect a report_agent or markdown report with quality_agent."
    )
    parser.add_argument("report", help="Report path, or filename under reports/.")
    parser.add_argument(
        "--mode",
        choices=("rule", "hybrid", "llm"),
        default="rule",
        help="Inspection mode. Default: rule.",
    )
    parser.add_argument("--save", action="store_true", help="Export inspection result.")
    parser.add_argument(
        "--output-dir",
        default="reports/quality_inspections",
        help="Directory used when --save is set.",
    )
    parser.add_argument(
        "--output-format",
        choices=("json", "md"),
        default="json",
        help="Export format used when --save is set.",
    )

    args = parser.parse_args(argv)
    _load_env()

    try:
        path = _resolve_report_path(args.report)
        package = _load_report_package(path)
        config = _build_config(args)
        result = inspect_report_package(package, config=config)
        _print_result(path, result)
    except Exception as exc:
        print(f"quality inspection failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

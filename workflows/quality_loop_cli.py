"""CLI for running the report generation workflow with quality feedback."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:  # pragma: no cover - direct script fallback
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from agent.quality_agent.config import InspectionMode, LLMConfig, QualityConfig
from workflows.quality_loop import run_quality_loop


def _quality_config(mode: str) -> QualityConfig:
    if mode == "rule":
        return QualityConfig(
            inspection_mode=InspectionMode.RULE_ONLY,
            llm=LLMConfig(enabled=False),
        )
    if mode == "llm":
        config = QualityConfig.from_env()
        config.inspection_mode = InspectionMode.LLM_ONLY
        config.llm_enabled = True
        return config
    config = QualityConfig.from_env()
    config.inspection_mode = InspectionMode.HYBRID_VOTING
    config.llm_enabled = True
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run collector -> analyst -> writer -> quality feedback loop."
    )
    parser.add_argument("product_description", help="产品描述或分析目标")
    parser.add_argument(
        "--competitor",
        action="append",
        default=[],
        help="竞品名称，可重复传入",
    )
    parser.add_argument("--task-id", default="quality_loop_task")
    parser.add_argument("--target-domain", default="")
    parser.add_argument("--analysis-goal", default="")
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument(
        "--quality-mode",
        choices=("rule", "hybrid", "llm"),
        default="rule",
        help="质检模式，默认 rule，避免默认发起 LLM 调用",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/workflow_runs",
        help="保存每轮搜索、报告、质检、反馈产物的目录",
    )

    args = parser.parse_args(argv)
    try:
        result = run_quality_loop(
            args.product_description,
            competitors=args.competitor,
            task_id=args.task_id,
            target_domain=args.target_domain,
            analysis_goal=args.analysis_goal,
            max_iterations=args.max_iterations,
            quality_config=_quality_config(args.quality_mode),
            output_dir=args.output_dir,
            progress_printer=print,
        )
    except Exception as exc:
        print(f"quality loop failed: {exc}", file=sys.stderr)
        return 1

    report = result.quality_report
    print(f"status: {result.state.status.value}")
    print(f"rounds: {result.state.iteration_count}")
    if report:
        print(f"score: {report.score:.4f}")
        print(f"passed: {report.passed}")
        print(f"issues: {len(report.issues)}")
    if result.state.output_paths:
        print(f"final_result: {result.state.output_paths.get('final_result', '')}")
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

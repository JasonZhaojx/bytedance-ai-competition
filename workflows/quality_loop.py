"""Pure Python DAG-style workflow that closes the report quality loop."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional, Sequence

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None

from agent.quality_agent.config import QualityConfig
from agent.quality_agent.feedback import build_feedback_payload
from agent.quality_agent.report_quality_agent import inspect_report_package
from report_agent.core import run_analysis_agent, run_report_writer_agent
from report_agent.models import WritingAgentConfig
from report_agent.pipeline import build_writing_config_from_env
from report_agent.search_adapter import ReportSearchConfig, search_for_report

from .artifacts import write_final_artifact, write_round_artifacts
from .quality_loop_schema import (
    QualityLoopResult,
    QualityLoopState,
    RetryTarget,
    WorkflowStatus,
)


ROOT = Path(__file__).resolve().parents[1]


def run_quality_loop(
    product_description: str,
    *,
    competitors: Optional[Sequence[str]] = None,
    task_id: str = "quality_loop_task",
    target_domain: str = "",
    analysis_goal: str = "",
    max_iterations: int = 3,
    search_config: Optional[ReportSearchConfig] = None,
    writing_config: Optional[WritingAgentConfig] = None,
    quality_config: Optional[QualityConfig] = None,
    output_dir: Optional[str | Path] = None,
    progress_printer: Optional[Callable[[str], None]] = None,
) -> QualityLoopResult:
    """Run collector -> analyst -> writer -> quality with feedback retries."""

    _load_env()
    state = QualityLoopState(
        task_id=task_id,
        product_description=_required(product_description, "product_description"),
        competitors=[item.strip() for item in competitors or [] if item.strip()],
        target_domain=target_domain.strip() or product_description.strip(),
        analysis_goal=(
            analysis_goal.strip()
            or f"基于搜索结果，为 {product_description.strip()} 生成竞品分析报告"
        ),
        max_iterations=max(1, max_iterations),
    )
    artifacts_dir = Path(output_dir) if output_dir else None

    active_writing_config = writing_config or build_writing_config_from_env()
    if progress_printer:
        active_writing_config = replace(
            active_writing_config,
            progress_printer=progress_printer,
        )

    while state.iteration_count < state.max_iterations:
        state.iteration_count += 1
        _log(progress_printer, f"[quality-loop] round {state.iteration_count} started")

        if _should_run_collector(state):
            _run_collector(state, search_config, progress_printer)
        if _should_run_analyst(state):
            _run_analyst(state, active_writing_config)
        if _should_run_writer(state):
            _run_writer(state, active_writing_config)

        _run_quality(state, quality_config)
        state.retry_target = choose_retry_target(state.feedback_payload)
        _record_round(state)

        if artifacts_dir:
            state.output_paths.update(
                write_round_artifacts(
                    output_dir=artifacts_dir,
                    task_id=state.task_id,
                    round_index=state.iteration_count,
                    queries=state.queries,
                    search_results=state.search_results,
                    search_errors=state.search_errors,
                    report_package=state.report_package,
                    quality_report=state.quality_report,
                    feedback_payload=state.feedback_payload,
                    feedback_search_queries=state.feedback_search_queries,
                    writer_constraints=state.writer_constraints,
                )
            )

        if state.quality_report and state.quality_report.passed:
            state.status = WorkflowStatus.APPROVED
            state.retry_target = RetryTarget.NONE
            _log(progress_printer, "[quality-loop] quality passed")
            break

        if state.iteration_count >= state.max_iterations:
            state.status = WorkflowStatus.REJECTED
            _log(progress_printer, "[quality-loop] max iterations reached")
            break

        _log(
            progress_printer,
            f"[quality-loop] retry target: {state.retry_target.value}",
        )

    if artifacts_dir:
        state.output_paths["final_result"] = write_final_artifact(
            output_dir=artifacts_dir,
            task_id=state.task_id,
            payload={
                "task_id": state.task_id,
                "status": state.status.value,
                "passed": bool(state.quality_report and state.quality_report.passed),
                "rounds": state.iteration_count,
                "retry_target": state.retry_target.value,
                "score": state.quality_report.score if state.quality_report else None,
                "issues": len(state.quality_report.issues) if state.quality_report else None,
                "history": state.history,
                "output_paths": state.output_paths,
            },
        )
    return QualityLoopResult(state=state)


def choose_retry_target(feedback_payload: dict) -> RetryTarget:
    """Choose the earliest upstream retry target required by quality feedback."""

    if not feedback_payload.get("retry_required"):
        return RetryTarget.NONE
    grouped = feedback_payload.get("grouped_by_agent") or {}
    if grouped.get(RetryTarget.COLLECTOR.value):
        return RetryTarget.COLLECTOR
    if grouped.get(RetryTarget.ANALYST.value):
        return RetryTarget.ANALYST
    if grouped.get(RetryTarget.WRITER.value):
        return RetryTarget.WRITER
    return RetryTarget.WRITER


def build_feedback_search_queries(
    state: QualityLoopState,
    *,
    limit: int = 6,
) -> list[str]:
    """Convert collector feedback into targeted follow-up search queries."""

    grouped = state.feedback_payload.get("grouped_by_agent") or {}
    messages = grouped.get(RetryTarget.COLLECTOR.value) or []
    queries: list[str] = []
    base = state.target_domain or state.product_description
    competitors = state.competitors or [state.product_description]
    for message in messages:
        issue = _compact_text(message.get("issue_type", ""))
        description = _compact_text(message.get("description", ""))
        fix = _compact_text(message.get("suggested_fix", ""))
        fields = " ".join(_compact_text(item) for item in message.get("affected_fields", [])[:3])
        focus = " ".join(part for part in [issue, description, fix, fields] if part)
        focus = _compact_text(focus, max_chars=120)
        for competitor in competitors:
            queries.extend(
                [
                    f"{competitor} {base} {focus} 官方 来源 证据",
                    f"{competitor} {base} {focus} 最新 数据 评测",
                ]
            )
    return _dedupe_strings(queries)[:limit]


def build_writer_constraints(state: QualityLoopState) -> list[dict]:
    """Build structured, auditable constraints for writer retries."""

    grouped = state.feedback_payload.get("grouped_by_agent") or {}
    messages = grouped.get(RetryTarget.WRITER.value) or []
    constraints: list[dict] = []
    for index, message in enumerate(messages, 1):
        constraints.append(
            {
                "constraint_id": f"writer_fix_{state.iteration_count:02d}_{index:02d}",
                "issue_type": message.get("issue_type", ""),
                "priority": message.get("priority", "medium"),
                "description": message.get("description", ""),
                "required_action": message.get("suggested_fix", ""),
                "affected_fields": list(message.get("affected_fields", []) or []),
            }
        )
    return constraints


def _run_collector(
    state: QualityLoopState,
    search_config: Optional[ReportSearchConfig],
    progress_printer: Optional[Callable[[str], None]],
) -> None:
    state.status = WorkflowStatus.COLLECTING
    config = search_config or ReportSearchConfig.from_env()
    if progress_printer:
        config.progress_printer = progress_printer
    bundle = search_for_report(
        state.product_description,
        competitors=state.competitors,
        extra_queries=state.feedback_search_queries,
        config=config,
    )
    state.queries = list(bundle.queries)
    state.search_results = list(bundle.results)
    state.search_errors = list(bundle.errors)
    if not state.search_results:
        detail = "; ".join(state.search_errors) if state.search_errors else "none"
        raise RuntimeError(f"No search results available. Search errors: {detail}")


def _run_analyst(
    state: QualityLoopState,
    writing_config: WritingAgentConfig,
) -> None:
    state.status = WorkflowStatus.ANALYZING
    state.report_state = run_analysis_agent(
        state.search_results,
        config=writing_config,
        task_id=state.task_id,
        analysis_goal=_analysis_goal_with_feedback(state),
        target_domain=state.target_domain,
        competitors=state.competitors,
    )


def _run_writer(
    state: QualityLoopState,
    writing_config: WritingAgentConfig,
) -> None:
    if state.report_state is None:
        raise RuntimeError("writer_agent requires report_state from analyst_agent")
    state.status = WorkflowStatus.WRITING
    _apply_writer_constraints(state)
    state.report_package = run_report_writer_agent(state.report_state, config=writing_config)


def _run_quality(
    state: QualityLoopState,
    quality_config: Optional[QualityConfig],
) -> None:
    if state.report_package is None:
        raise RuntimeError("quality_agent requires report_package from writer_agent")
    state.status = WorkflowStatus.INSPECTING
    state.quality_report = inspect_report_package(state.report_package, config=quality_config)
    state.feedback_payload = build_feedback_payload(
        state.quality_report,
        task_id=state.task_id,
    )
    state.feedback_search_queries = build_feedback_search_queries(state)
    state.writer_constraints = build_writer_constraints(state)


def _should_run_collector(state: QualityLoopState) -> bool:
    return not state.search_results or state.retry_target == RetryTarget.COLLECTOR


def _should_run_analyst(state: QualityLoopState) -> bool:
    return (
        state.report_state is None
        or state.retry_target in {RetryTarget.COLLECTOR, RetryTarget.ANALYST}
    )


def _should_run_writer(state: QualityLoopState) -> bool:
    return (
        state.report_package is None
        or state.retry_target
        in {RetryTarget.COLLECTOR, RetryTarget.ANALYST, RetryTarget.WRITER}
    )


def _analysis_goal_with_feedback(state: QualityLoopState) -> str:
    messages = state.feedback_payload.get("feedback_messages") or []
    if not messages:
        return state.analysis_goal
    lines = [state.analysis_goal, "", "质检反馈要求:"]
    for message in messages[:6]:
        lines.append(
            "- {target}: {issue} - {fix}".format(
                target=message.get("target_agent", "unknown"),
                issue=message.get("description", ""),
                fix=message.get("suggested_fix", ""),
            )
        )
    return "\n".join(lines)


def _apply_writer_constraints(state: QualityLoopState) -> None:
    if state.report_state is None:
        return
    state.report_state.analysis_goal = _analysis_goal_with_feedback(state)
    if not state.writer_constraints:
        return
    constraint_lines = []
    for constraint in state.writer_constraints:
        description = _compact_text(constraint.get("description", ""))
        action = _compact_text(constraint.get("required_action", ""))
        constraint_lines.append(f"{constraint['constraint_id']}: {description} -> {action}")
    state.report_state.missing_info = _dedupe_strings(
        [*state.report_state.missing_info, *constraint_lines]
    )
    state.report_state.low_confidence_claims = _dedupe_strings(
        [
            *state.report_state.low_confidence_claims,
            *[
                str(constraint.get("description", ""))
                for constraint in state.writer_constraints
                if constraint.get("description")
            ],
        ]
    )
    state.report_state.generation_trace.append(
        {
            "step": "writer_feedback_constraints",
            "input_refs": [
                str(constraint.get("constraint_id", "writer_fix"))
                for constraint in state.writer_constraints
            ],
            "output_refs": ["report_markdown", "missing_info", "low_confidence_claims"],
            "constraints": state.writer_constraints,
        }
    )


def _record_round(state: QualityLoopState) -> None:
    report = state.quality_report
    state.history.append(
        {
            "round": state.iteration_count,
            "status": state.status.value,
            "passed": bool(report and report.passed),
            "score": report.score if report else None,
            "issues": len(report.issues) if report else None,
            "retry_target": state.retry_target.value,
            "feedback_search_queries": list(state.feedback_search_queries),
            "writer_constraints": list(state.writer_constraints),
        }
    )


def _load_env() -> None:
    if load_dotenv:
        load_dotenv(ROOT / ".env")


def _required(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty")
    return cleaned


def _log(printer: Optional[Callable[[str], None]], message: str) -> None:
    if printer:
        printer(message)


def _compact_text(value: object, max_chars: int = 80) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_chars].strip()


def _dedupe_strings(values: list[str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _compact_text(value, max_chars=240)
        if item and item not in seen:
            seen.add(item)
            results.append(item)
    return results

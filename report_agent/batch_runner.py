"""Helpers for running chunked report-agent LLM work in parallel."""

from __future__ import annotations

import time
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, List, Optional, Sequence, TypeVar, cast

try:
    from .models import WritingAgentConfig
except ImportError:
    from report_agent.models import WritingAgentConfig


BatchT = TypeVar("BatchT")
ResultT = TypeVar("ResultT")
_LOG_LOCK = Lock()


def run_parallel_batches(
    *,
    label: str,
    batches: Sequence[BatchT],
    config: WritingAgentConfig,
    worker: Callable[[BatchT], ResultT],
    describe_batch: Optional[Callable[[BatchT], str]] = None,
) -> List[ResultT]:
    """Run chunk workers with bounded concurrency and return results in order."""

    batch_count = len(batches)
    if batch_count == 0:
        return []

    max_workers = _batch_workers(config, batch_count)
    _log(
        config,
        f"[writing-agent] chunk {label}: {batch_count} batches, workers={max_workers}",
    )

    if max_workers <= 1 or batch_count == 1:
        results: List[ResultT] = []
        for index, batch in enumerate(batches, 1):
            results.append(
                _run_one(
                    label=label,
                    index=index,
                    total=batch_count,
                    batch=batch,
                    config=config,
                    worker=worker,
                    describe_batch=describe_batch,
                )
            )
        return results

    results: List[Optional[ResultT]] = [None] * batch_count
    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix=f"report-agent-{_thread_prefix(label)}",
    ) as executor:
        future_to_index = {
            executor.submit(
                _run_one,
                label=label,
                index=index + 1,
                total=batch_count,
                batch=batch,
                config=config,
                worker=worker,
                describe_batch=describe_batch,
            ): index
            for index, batch in enumerate(batches)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            results[index] = future.result()

    return [cast(ResultT, result) for result in results]


def _run_one(
    *,
    label: str,
    index: int,
    total: int,
    batch: BatchT,
    config: WritingAgentConfig,
    worker: Callable[[BatchT], ResultT],
    describe_batch: Optional[Callable[[BatchT], str]],
) -> ResultT:
    detail = describe_batch(batch) if describe_batch else _default_batch_detail(batch)
    _log(config, f"[writing-agent] {label} batch {index}/{total} start{detail}")
    started_at = time.perf_counter()
    try:
        result = worker(batch)
    except Exception as exc:
        elapsed = time.perf_counter() - started_at
        _log(
            config,
            f"[writing-agent] {label} batch {index}/{total} failed "
            f"after {elapsed:.1f}s: {exc}",
        )
        raise
    elapsed = time.perf_counter() - started_at
    _log(config, f"[writing-agent] {label} batch {index}/{total} done in {elapsed:.1f}s")
    return result


def _batch_workers(config: WritingAgentConfig, batch_count: int) -> int:
    value = getattr(config, "llm_batch_workers", 1)
    try:
        workers = int(value)
    except (TypeError, ValueError):
        workers = 1
    return max(1, min(batch_count, workers))


def _default_batch_detail(batch: Any) -> str:
    try:
        size = len(batch)
    except TypeError:
        return ""
    return f" ({size} items)"


def _thread_prefix(label: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in label)[:24]


def _log(config: WritingAgentConfig, message: str) -> None:
    if config.verbose and config.progress_printer:
        with _LOG_LOCK:
            config.progress_printer(message)

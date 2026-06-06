"""Lightweight observability utilities for quality_agent."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class CallTrace:
    call_id: str
    operation: str
    start_time: float
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def finish(self, success: bool = True, error: Optional[str] = None) -> None:
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.success = success
        self.error_message = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "operation": self.operation,
            "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
            "end_time": datetime.fromtimestamp(self.end_time).isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


class ObservableLogger:
    """Append-only JSONL logger used for LLM adjudication traces."""

    def __init__(self, log_dir: str = "./logs/quality_agent"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def start_trace(self, operation: str, call_id: Optional[str] = None, **metadata) -> CallTrace:
        if call_id is None:
            call_id = f"{operation}_{int(time.time() * 1000)}"
        return CallTrace(
            call_id=call_id,
            operation=operation,
            start_time=time.time(),
            metadata=metadata,
        )

    def finish_trace(self, trace: CallTrace, success: bool = True, error: Optional[str] = None) -> None:
        trace.finish(success=success, error=error)
        self._append_jsonl("traces.jsonl", trace.to_dict())

    def log_prompt(self, prompt: str, operation: str, max_length: int = 500) -> None:
        self._append_jsonl("llm_io.jsonl", {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "kind": "prompt",
            "preview": self._preview(prompt, max_length),
            "length": len(prompt),
        })

    def log_response(self, response: str, operation: str, max_length: int = 500) -> None:
        self._append_jsonl("llm_io.jsonl", {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "kind": "response",
            "preview": self._preview(response, max_length),
            "length": len(response),
        })

    def _append_jsonl(self, filename: str, record: Dict[str, Any]) -> None:
        path = self.log_dir / filename
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _preview(self, text: str, max_length: int) -> str:
        return text[:max_length] + "..." if len(text) > max_length else text

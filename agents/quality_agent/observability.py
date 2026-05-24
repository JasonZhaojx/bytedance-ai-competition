"""可观测性模块 - 日志系统、Token追踪、调用追踪."""

import logging
import time
import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import threading


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class TokenUsage:
    """Token使用记录."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def add(self, other: "TokenUsage") -> None:
        """累加Token使用."""
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model,
            "timestamp": self.timestamp
        }


@dataclass
class CallTrace:
    """调用追踪记录."""
    call_id: str
    operation: str
    start_time: float
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def finish(self, success: bool = True, error: Optional[str] = None) -> None:
        """结束追踪."""
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
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "metadata": self.metadata
        }


class ObservableLogger:
    """可观测性日志记录器."""

    _instance: Optional["ObservableLogger"] = None
    _lock = threading.Lock()

    def __new__(cls, log_dir: str = "./logs"):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, log_dir: str = "./logs"):
        if self._initialized:
            return
        self._initialized = True

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self._setup_logger()
        self.token_usage: Dict[str, List[TokenUsage]] = {}
        self.traces: List[CallTrace] = []
        self.total_tokens = TokenUsage()
        self._trace_lock = threading.Lock()
        self._token_lock = threading.Lock()

    def _setup_logger(self) -> None:
        """设置日志记录器."""
        self.logger = logging.getLogger("quality_agent")
        self.logger.setLevel(logging.DEBUG)

        if not self.logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_formatter = logging.Formatter(
                "[%(levelname)s] %(message)s"
            )
            console_handler.setFormatter(console_formatter)

            file_handler = logging.FileHandler(
                self.log_dir / f"quality_{datetime.now().strftime('%Y%m%d')}.log",
                encoding="utf-8"
            )
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            file_handler.setFormatter(file_formatter)

            self.logger.addHandler(console_handler)
            self.logger.addHandler(file_handler)

    def log(self, level: LogLevel, message: str, **kwargs) -> None:
        """记录日志."""
        log_func = getattr(self.logger, level.value.lower())
        if kwargs:
            message = f"{message} | {json.dumps(kwargs, ensure_ascii=False)}"
        log_func(message)

    def debug(self, message: str, **kwargs) -> None:
        self.log(LogLevel.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        self.log(LogLevel.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        self.log(LogLevel.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        self.log(LogLevel.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs) -> None:
        self.log(LogLevel.CRITICAL, message, **kwargs)

    def start_trace(self, operation: str, call_id: Optional[str] = None, **metadata) -> CallTrace:
        """开始调用追踪."""
        if call_id is None:
            call_id = f"{operation}_{int(time.time() * 1000)}"
        trace = CallTrace(
            call_id=call_id,
            operation=operation,
            start_time=time.time(),
            metadata=metadata
        )
        with self._trace_lock:
            self.traces.append(trace)
        self.debug(f"Trace started: {operation}", call_id=call_id)
        return trace

    def finish_trace(self, trace: CallTrace, success: bool = True, error: Optional[str] = None) -> None:
        """结束调用追踪."""
        trace.finish(success=success, error=error)
        with self._trace_lock:
            self._save_trace(trace)
        if success:
            self.debug(
                f"Trace completed: {trace.operation}",
                call_id=trace.call_id,
                duration_ms=trace.duration_ms
            )
        else:
            self.error(
                f"Trace failed: {trace.operation}",
                call_id=trace.call_id,
                error=error,
                duration_ms=trace.duration_ms
            )

    def _save_trace(self, trace: CallTrace) -> None:
        """保存追踪记录."""
        trace_file = self.log_dir / "traces.jsonl"
        with open(trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(trace.to_dict(), ensure_ascii=False) + "\n")

    def record_token_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
        operation: str = "unknown"
    ) -> TokenUsage:
        """记录Token使用量."""
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            model=model
        )

        with self._token_lock:
            if operation not in self.token_usage:
                self.token_usage[operation] = []
            self.token_usage[operation].append(usage)
            self.total_tokens.add(usage)
            self._save_token_usage(usage, operation)

        self.info(
            f"Token usage recorded",
            operation=operation,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=usage.total_tokens,
            model=model
        )
        return usage

    def _save_token_usage(self, usage: TokenUsage, operation: str) -> None:
        """保存Token使用记录."""
        token_file = self.log_dir / "token_usage.jsonl"
        record = {
            **usage.to_dict(),
            "operation": operation
        }
        with open(token_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def get_total_tokens(self) -> TokenUsage:
        """获取总Token使用量."""
        with self._token_lock:
            return self.total_tokens

    def get_operation_tokens(self, operation: str) -> List[TokenUsage]:
        """获取指定操作的Token使用量."""
        with self._token_lock:
            return self.token_usage.get(operation, [])

    def log_prompt(self, prompt: str, operation: str, max_length: int = 500) -> None:
        """记录Prompt内容（截断超长部分）."""
        truncated = prompt[:max_length] + "..." if len(prompt) > max_length else prompt
        self.debug(f"Prompt ({operation})", prompt_preview=truncated, total_length=len(prompt))

    def log_response(self, response: str, operation: str, max_length: int = 500) -> None:
        """记录响应内容（截断超长部分）."""
        truncated = response[:max_length] + "..." if len(response) > max_length else response
        self.debug(f"Response ({operation})", response_preview=truncated, total_length=len(response))

    def get_summary(self) -> Dict[str, Any]:
        """获取可观测性摘要."""
        with self._trace_lock:
            total_traces = len(self.traces)
            successful_traces = sum(1 for t in self.traces if t.success)
            failed_traces = total_traces - successful_traces

        with self._token_lock:
            total_ops = len(self.token_usage)

        return {
            "total_traces": total_traces,
            "successful_traces": successful_traces,
            "failed_traces": failed_traces,
            "total_token_usage": self.total_tokens.to_dict(),
            "operations_count": total_ops,
            "log_dir": str(self.log_dir)
        }


def get_logger() -> ObservableLogger:
    """获取全局日志记录器实例."""
    return ObservableLogger()

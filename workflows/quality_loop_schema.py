"""Data structures for the report generation quality loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from agent.quality_agent.config import QualityReport
from report_agent.models import ReportPackage, ReportState


class RetryTarget(str, Enum):
    """Upstream node selected by quality feedback."""

    NONE = "none"
    COLLECTOR = "collector_agent"
    ANALYST = "analyst_agent"
    WRITER = "writer_agent"


class WorkflowStatus(str, Enum):
    """Quality-loop execution status."""

    PENDING = "pending"
    COLLECTING = "collecting"
    ANALYZING = "analyzing"
    WRITING = "writing"
    INSPECTING = "inspecting"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class QualityLoopState:
    """Mutable state shared by collector, analyst, writer, and quality nodes."""

    task_id: str
    product_description: str
    competitors: List[str] = field(default_factory=list)
    target_domain: str = ""
    analysis_goal: str = ""
    max_iterations: int = 3

    iteration_count: int = 0
    status: WorkflowStatus = WorkflowStatus.PENDING
    retry_target: RetryTarget = RetryTarget.NONE

    queries: List[str] = field(default_factory=list)
    search_results: List[Any] = field(default_factory=list)
    search_errors: List[str] = field(default_factory=list)
    report_state: Optional[ReportState] = None
    report_package: Optional[ReportPackage] = None
    quality_report: Optional[QualityReport] = None
    feedback_payload: Dict[str, Any] = field(default_factory=dict)
    feedback_search_queries: List[str] = field(default_factory=list)
    writer_constraints: List[Dict[str, Any]] = field(default_factory=list)
    output_paths: Dict[str, str] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class QualityLoopResult:
    """Final result returned by the quality-loop workflow."""

    state: QualityLoopState

    @property
    def passed(self) -> bool:
        report = self.state.quality_report
        return bool(report and report.passed and self.state.status == WorkflowStatus.APPROVED)

    @property
    def report_package(self) -> Optional[ReportPackage]:
        return self.state.report_package

    @property
    def quality_report(self) -> Optional[QualityReport]:
        return self.state.quality_report

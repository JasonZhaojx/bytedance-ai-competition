"""Writing agent public API."""

from __future__ import annotations

from .core import run_writing_agent
from .models import (
    EvidenceCard,
    PMInsight,
    ProductRecommendation,
    ReportPackage,
    ReportState,
    SWOTItem,
    SWOTResult,
    SourceRecord,
    WritingAgentConfig,
)


def run_search_and_report(*args, **kwargs):
    """Lazy public wrapper for the search + report pipeline."""

    from .pipeline import run_search_and_report as _run_search_and_report

    return _run_search_and_report(*args, **kwargs)


def __getattr__(name: str):
    if name == "SearchReportResult":
        from .pipeline import SearchReportResult

        return SearchReportResult
    raise AttributeError(f"module 'report_agent' has no attribute {name!r}")

__all__ = [
    "run_writing_agent",
    "run_search_and_report",
    "WritingAgentConfig",
    "SourceRecord",
    "EvidenceCard",
    "PMInsight",
    "SWOTItem",
    "SWOTResult",
    "ProductRecommendation",
    "ReportState",
    "ReportPackage",
    "SearchReportResult",
]

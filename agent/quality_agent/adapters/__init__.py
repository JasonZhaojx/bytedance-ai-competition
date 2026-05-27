"""Adapters for converting external data formats."""

from .report_adapter import ReportEvidence, ReportAnalysis, adapt_report_package

__all__ = [
    "ReportEvidence",
    "ReportAnalysis",
    "adapt_report_package",
]
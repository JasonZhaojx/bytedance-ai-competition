"""Quality inspection modules for reports."""

from .base_inspector import (
    check_claim_evidence_linkage,
    check_evidence_quality,
)
from .structure_inspector import check_report_structure
from .evidence_inspector import (
    check_evidence_diversity,
    check_evidence_timeliness,
)
from .competitor_inspector import check_competitor_coverage
from .logic_inspector import check_logical_consistency
from .recommendation_inspector import check_recommendation_feasibility
from .llm_inspector import LLMInspector
from .hybrid_inspector import HybridInspector

__all__ = [
    "check_claim_evidence_linkage",
    "check_evidence_quality",
    "check_report_structure",
    "check_evidence_diversity",
    "check_evidence_timeliness",
    "check_competitor_coverage",
    "check_logical_consistency",
    "check_recommendation_feasibility",
    "LLMInspector",
    "HybridInspector",
]
"""Data structures and adapter for ReportPackage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

try:
    from report_agent.models import ReportPackage
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from report_agent.models import ReportPackage


def _extract_competitor_name(item: Any) -> str:
    """Return a stable competitor name from report_agent profile shapes."""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("competitor", "name", "product_name", "title"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _normalize_competitors(raw_competitors: Any) -> List[str]:
    if not isinstance(raw_competitors, list):
        return []

    competitors: List[str] = []
    seen = set()
    for item in raw_competitors:
        name = _extract_competitor_name(item)
        if name and name not in seen:
            competitors.append(name)
            seen.add(name)
    return competitors


@dataclass
class ReportEvidence:
    """Adapted report evidence unit."""
    title: str
    url: str
    snippet: str = ""
    page_text: str = ""
    claim: str = ""
    confidence: float = 1.0
    source_id: str = ""
    source_type: str = ""
    publish_date: str = ""
    blocked_or_empty: bool = False


@dataclass
class ReportAnalysis:
    """Adapted report analysis result."""
    task_id: str
    product_name: str
    evidence_list: List[ReportEvidence]
    claims: List[Dict[str, Any]]
    pm_insights: List[Dict[str, Any]]
    swot: Dict[str, List[Dict[str, Any]]]
    recommendations: List[Dict[str, Any]]
    report_markdown: str
    summary: str = ""
    competitors: List[str] = field(default_factory=list)
    comparison_tables: List[Dict[str, Any]] = field(default_factory=list)


def adapt_report_package(package: ReportPackage) -> ReportAnalysis:
    """Convert ReportPackage to analysis format."""
    evidence_list: List[ReportEvidence] = []
    
    analysis = package.structured_analysis or {}
    
    # Get competitors
    competitors = _normalize_competitors(
        analysis.get('executive_summary', {}).get('competitors', [])
    )
    if not competitors:
        competitors = _normalize_competitors(analysis.get('competitor_profiles', []))
    
    # Get comparison tables
    comparison_tables = analysis.get('comparison_tables', [])
    
    # Get evidence cards
    evidence_cards = analysis.get("evidence_cards", [])
    source_map = {source.get("source_id"): source for source in package.sources}
    
    for card in evidence_cards:
        evidence_id = card.get("evidence_id", "")
        source_id = card.get("source_id", "")
        source = source_map.get(source_id, {})
        source_type = source.get("source", "") or source.get("content_source", "")
        
        evidence = ReportEvidence(
            title=source.get("title", "") or card.get("claim", "")[:50],
            url=source.get("url", ""),
            snippet=source.get("snippet", ""),
            page_text=source.get("content", ""),
            claim=card.get("claim", ""),
            confidence=card.get("confidence", 1.0),
            source_id=evidence_id if evidence_id else source_id,
            source_type=source_type,
            publish_date=source.get("publish_date", "") or source.get("retrieved_at", ""),
            blocked_or_empty=False,
        )
        evidence_list.append(evidence)
    
    # Fallback if no evidence cards
    if not evidence_list:
        for source in package.sources:
            evidence = ReportEvidence(
                title=source.get("title", ""),
                url=source.get("url", ""),
                snippet=source.get("snippet", ""),
                page_text=source.get("content", ""),
                source_id=source.get("source_id", ""),
                source_type=source.get("source", "") or source.get("content_source", ""),
                publish_date=source.get("publish_date", "") or source.get("retrieved_at", ""),
                blocked_or_empty=False,
            )
            evidence_list.append(evidence)
    
    claims = package.claim_evidence_map or []
    pm_insights = analysis.get("pm_insights", [])
    swot_data = analysis.get("swot", {})
    recommendations = analysis.get("recommendations", [])
    
    summary = f"任务ID: {package.task_id}\n"
    summary += f"领域: {analysis.get('executive_summary', {}).get('target_domain', '')}\n"
    summary += f"分析目标: {analysis.get('executive_summary', {}).get('analysis_goal', '')}\n"
    summary += f"关键发现: {', '.join(analysis.get('executive_summary', {}).get('key_findings', []))}"
    
    return ReportAnalysis(
        task_id=package.task_id,
        product_name=analysis.get('executive_summary', {}).get('target_domain', '') or package.task_id,
        evidence_list=evidence_list,
        claims=claims,
        pm_insights=pm_insights,
        swot=swot_data,
        recommendations=recommendations,
        report_markdown=package.report_markdown,
        summary=summary,
        competitors=competitors,
        comparison_tables=comparison_tables,
    )

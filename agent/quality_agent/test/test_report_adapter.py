"""Test quality agent with report_agent's ReportPackage."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from report_agent.models import (
    ReportPackage,
    EvidenceCard,
    PMInsight,
    SWOTResult,
    SWOTItem,
    ProductRecommendation,
    SourceRecord,
)
from agent.quality_agent import inspect_report_package, QualityReport


def create_mock_report_package() -> ReportPackage:
    """Create a mock ReportPackage for testing."""
    sources = [
        SourceRecord(
            source_id="src_001",
            title="Trae AI IDE 官方介绍",
            url="https://trae.example.com/features",
            snippet="Trae AI IDE 是一款强大的AI编程助手",
            content="Trae AI IDE 支持Python、JavaScript等编程语言",
            source="official",
            content_source="webpage",
            credibility_score=0.95,
        ),
        SourceRecord(
            source_id="src_002",
            title="Cursor AI 功能评测",
            url="https://review.example.com/cursor-review",
            snippet="Cursor AI 在代码补全方面表现出色",
            content="Cursor AI 代码补全准确率达到92%",
            source="review",
            content_source="article",
            credibility_score=0.85,
        ),
        SourceRecord(
            source_id="src_003",
            title="AI IDE 竞品对比分析",
            url="https://analysis.example.com/ai-ide-comparison",
            snippet="Trae、Cursor、GitHub Copilot 各有优劣",
            content="Trae以轻量级著称，Cursor在代码理解深度上领先",
            source="analysis",
            content_source="report",
            credibility_score=0.90,
        ),
    ]
    
    evidence_cards = [
        EvidenceCard(
            evidence_id="ev_001",
            source_id="src_001",
            competitor="Trae",
            dimension="features",
            claim="Trae AI IDE 支持多种编程语言",
            raw_excerpt="支持Python、JavaScript等编程语言",
            confidence=0.95,
            importance_for_pm="high",
        ),
        EvidenceCard(
            evidence_id="ev_002",
            source_id="src_002",
            competitor="Cursor",
            dimension="performance",
            claim="Cursor AI 代码补全准确率达到92%",
            raw_excerpt="代码补全准确率达到92%",
            confidence=0.90,
            importance_for_pm="high",
        ),
        EvidenceCard(
            evidence_id="ev_003",
            source_id="src_003",
            competitor="GitHub Copilot",
            dimension="features",
            claim="GitHub Copilot 拥有最广泛的语言支持",
            raw_excerpt="拥有最广泛的语言支持",
            confidence=0.88,
            importance_for_pm="high",
        ),
    ]
    
    pm_insights = [
        PMInsight(
            insight_id="ins_001",
            type="feature",
            title="多语言支持是核心竞争力",
            description="各产品都提供良好的多语言支持",
            related_competitors=["Trae", "Cursor", "GitHub Copilot"],
            evidence_ids=["ev_001", "ev_003"],
            pm_value="产品规划应优先考虑语言覆盖",
            confidence=0.92,
        ),
    ]
    
    swot = SWOTResult(
        strengths=[SWOTItem(
            point="Trae在响应速度上具有优势",
            why_it_matters="快速响应提升效率",
            evidence_ids=["ev_001"],
            pm_implication="继续优化响应速度",
            confidence=0.85,
        )],
        weaknesses=[SWOTItem(
            point="语言支持范围相对较窄",
            why_it_matters="可能无法满足部分用户需求",
            evidence_ids=["ev_003"],
            pm_implication="扩展语言支持",
            confidence=0.80,
        )],
        opportunities=[SWOTItem(
            point="AI编程助手市场增长迅速",
            why_it_matters="有较大市场空间",
            evidence_ids=["ev_003"],
            pm_implication="加大市场推广",
            confidence=0.90,
        )],
        threats=[SWOTItem(
            point="竞争激烈，GitHub Copilot占据主导",
            why_it_matters="市场份额获取难度大",
            evidence_ids=["ev_003"],
            pm_implication="差异化竞争策略",
            confidence=0.85,
        )],
    )
    
    recommendations = [
        ProductRecommendation(
            priority="high",
            timeframe="30天",
            action="优化代码补全算法",
            reason="提升准确率",
            expected_impact="提升用户满意度",
            risk="中等",
            evidence_ids=["ev_002"],
            success_metric="准确率提升5%",
        ),
    ]
    
    claim_evidence_map = []
    for idx, card in enumerate(evidence_cards, 1):
        claim_evidence_map.append({
            "claim_id": f"claim_{idx:03d}",
            "claim": card.claim,
            "evidence_ids": [card.evidence_id],
            "source_ids": [card.source_id],
            "confidence": card.confidence,
        })
    
    structured_analysis = {
        "executive_summary": {
            "analysis_goal": "AI IDE 竞品分析报告",
            "target_domain": "AI Agent",
            "competitors": ["Trae", "Cursor", "GitHub Copilot"],
            "key_findings": ["多语言支持是核心竞争力"],
        },
        "evidence_cards": [card.to_dict() for card in evidence_cards],
        "pm_insights": [insight.to_dict() for insight in pm_insights],
        "swot": swot.to_dict(),
        "recommendations": [rec.to_dict() for rec in recommendations],
    }
    
    return ReportPackage(
        task_id="test_task_001",
        report_markdown="# AI IDE 竞品分析报告\n\n## 执行摘要\n\n分析目标：AI IDE竞品分析",
        structured_analysis=structured_analysis,
        claim_evidence_map=claim_evidence_map,
        generation_trace=[],
        sources=[source.to_dict() for source in sources],
        missing_info=[],
        low_confidence_claims=[],
    )


def test_report_package_inspection():
    """Test inspecting ReportPackage."""
    print("=" * 60)
    print("Testing Report Quality Agent")
    print("=" * 60)
    
    package = create_mock_report_package()
    print(f"\nReport Package Info:")
    print(f"  Task ID: {package.task_id}")
    print(f"  Sources: {len(package.sources)}")
    print(f"  Claims: {len(package.claim_evidence_map)}")
    print(f"  Insights: {len(package.structured_analysis.get('pm_insights', []))}")
    
    report = inspect_report_package(package)
    
    print(f"\n--- Quality Report ---")
    print(f"Passed: {report.passed}")
    print(f"Score: {report.score:.2f}")
    print(f"Confidence Level: {report.confidence_level.value}")
    print(f"Needs Human Review: {report.needs_human_review}")
    print(f"Evidence Quality Avg: {report.evidence_quality_avg:.2f}")
    
    if report.issues:
        print(f"\n--- Issues ({len(report.issues)}) ---")
        for i, issue in enumerate(report.issues, 1):
            print(f"  {i}. [{issue.severity.value}] {issue.type.value}")
            print(f"     Description: {issue.description}")
    
    print(f"\n[OK] Report package inspection completed")
    return report


def main():
    """Run tests."""
    test_report_package_inspection()
    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
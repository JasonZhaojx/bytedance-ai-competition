"""Smoke tests for quality_agent against report_agent-style output."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from report_agent.models import ReportPackage
from agent.quality_agent import (
    InspectionMode,
    LLMConfig,
    QualityConfig,
    inspect_report_package,
)
from agent.quality_agent.feedback import build_feedback_payload


def create_realistic_report_package() -> ReportPackage:
    return ReportPackage(
        task_id="competitive_analysis_smoke",
        report_markdown=(
            "# AI IDE 竞品分析报告\n\n"
            "## 核心结论\n腾讯CodeBuddy和Qoder在不同开发场景中各有优势。\n\n"
            "## 重点竞品拆解\n### 腾讯CodeBuddy\n适合腾讯云和小程序生态。\n"
            "### qoder\n适合大代码库理解和异步任务执行。\n\n"
            "## SWOT 分析\n"
            "- Strengths: 中文生态适配强。\n"
            "- Weaknesses: 企业定价透明度不足。\n"
            "- Opportunities: 国产替代需求增长。\n"
            "- Threats: 海外AI IDE持续降价。\n\n"
            "## 产品策略建议\n1. 优先实现VS Code插件迁移能力。\n"
            "2. 免费版保留核心补全能力。\n"
            "3. 企业版突出私有部署和审计能力。\n\n"
            "[来源](https://example.com)\n"
        ),
        structured_analysis={
            "executive_summary": {
                "target_domain": "AI IDE",
                "competitors": ["腾讯CodeBuddy", "qoder"],
                "key_findings": ["VS Code兼容性是核心迁移因素"],
            },
            "evidence_cards": [
                {
                    "evidence_id": "ev_001",
                    "source_id": "src_001",
                    "claim": "腾讯CodeBuddy适合腾讯云生态。",
                    "confidence": 0.9,
                }
            ],
            "pm_insights": [
                {
                    "title": "插件迁移降低切换成本",
                    "evidence_ids": ["ev_001"],
                    "confidence": 0.9,
                }
            ],
            "swot": {
                "strengths": [{"point": "中文生态适配强"}],
                "weaknesses": [{"point": "定价透明度不足"}],
                "opportunities": [{"point": "国产替代需求增长"}],
                "threats": [{"point": "海外AI IDE竞争"}],
            },
            "recommendations": [
                {
                    "action": "优先实现VS Code插件迁移能力",
                    "timeframe": "30天",
                    "success_metric": "完成主流插件兼容验证",
                }
            ],
        },
        claim_evidence_map=[{"claim": "腾讯CodeBuddy适合腾讯云生态", "evidence_ids": ["ev_001"]}],
        generation_trace=[{"agent": "report_agent", "step": "compose"}],
        sources=[
            {
                "source_id": "src_001",
                "title": "CodeBuddy product page",
                "url": "https://example.com/codebuddy",
                "snippet": "CodeBuddy product details",
                "content": "CodeBuddy integrates with Tencent cloud developer workflows.",
                "source": "official",
                "retrieved_at": "2026-05-30T00:00:00Z",
            }
        ],
    )


def test_real_report_package_rule_only_smoke():
    package = create_realistic_report_package()
    config = QualityConfig(
        inspection_mode=InspectionMode.RULE_ONLY,
        llm=LLMConfig(enabled=False),
    )

    report = inspect_report_package(package, config=config)
    payload = build_feedback_payload(report, package.task_id)

    assert report.score >= 0.6
    assert payload["task_id"] == package.task_id
    assert "feedback_messages" in payload


def test_empty_report_is_flagged():
    package = ReportPackage(
        task_id="empty_report",
        report_markdown="",
        structured_analysis={},
        claim_evidence_map=[],
        generation_trace=[],
        sources=[],
    )
    config = QualityConfig(
        inspection_mode=InspectionMode.RULE_ONLY,
        llm=LLMConfig(enabled=False),
    )

    report = inspect_report_package(package, config=config)

    assert not report.passed
    assert report.issues

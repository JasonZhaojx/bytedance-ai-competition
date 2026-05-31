"""Compatibility checks for report_agent structured output."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agent.quality_agent.adapters.report_adapter import ReportAnalysis, ReportEvidence
from agent.quality_agent.config import IssueType
from agent.quality_agent.inspectors.competitor_inspector import check_competitor_coverage
from agent.quality_agent.inspectors.evidence_inspector import check_evidence_diversity
from agent.quality_agent.inspectors.recommendation_inspector import check_recommendation_feasibility
from agent.quality_agent.inspectors.structure_inspector import check_report_structure


def make_analysis(**overrides) -> ReportAnalysis:
    data = {
        "task_id": "compat",
        "product_name": "AI IDE",
        "evidence_list": [
            ReportEvidence(
                title="腾讯CodeBuddy 调研",
                url=r"E:\reports\codebuddy.md",
                snippet="CodeBuddy evidence",
                source_id="ev_001",
                source_type="local_report",
                claim="腾讯CodeBuddy supports AI coding.",
            ),
            ReportEvidence(
                title="qoder 调研",
                url=r"E:\reports\qoder.md",
                snippet="Qoder evidence",
                source_id="ev_002",
                source_type="local_report",
                claim="qoder supports agentic coding.",
            ),
            ReportEvidence(
                title="问卷分析",
                url=r"E:\questionnaires\ai_ide.md",
                snippet="User survey evidence",
                source_id="ev_003",
                source_type="local_report",
                claim="Users need VS Code compatibility.",
            ),
        ],
        "claims": [],
        "pm_insights": [],
        "swot": {},
        "recommendations": [],
        "report_markdown": (
            "# AI IDE 竞品分析报告\n\n"
            "## 核心结论\n结论 证据: ev_001, ev_002\n\n"
            "## 重点竞品拆解\n内容\n\n"
            "## SWOT分析\n内容\n\n"
            "## 产品策略建议\n- [30_days][P0] 做一件具体事情。证据: ev_003\n\n"
            "## 结论\n总结"
        ),
        "competitors": ["腾讯CodeBuddy", "qoder"],
        "comparison_tables": [],
    }
    data.update(overrides)
    return ReportAnalysis(**data)


def test_structure_accepts_report_agent_evidence_ids_as_sources():
    issues = check_report_structure(make_analysis())

    assert not [issue for issue in issues if issue.type == IssueType.MISSING_SOURCE]


def test_recommendations_accept_report_agent_day_timeframes():
    analysis = make_analysis(recommendations=[
        {
            "timeframe": "30_days",
            "action": "优先落地VS Code插件兼容和迁移验证",
            "success_metric": "插件兼容率达到95%",
        },
        {
            "timeframe": "60_days",
            "action": "上线中文编程场景专项优化",
            "success_metric": "中文需求转代码准确率达到96%",
        },
        {
            "timeframe": "90_days",
            "action": "启动企业私有化部署能力建设",
            "success_metric": "完成3家试点交付",
        },
    ])

    issues = check_recommendation_feasibility(analysis)

    assert not [issue for issue in issues if "时间框架" in issue.description]


def test_competitor_tables_accept_chinese_competitor_column():
    analysis = make_analysis(comparison_tables=[
        {
            "table_name": "基础定位对比",
            "rows": [
                {"竞品": "腾讯CodeBuddy", "产品定位": "AI编程工具"},
                {"竞品": "qoder", "产品定位": "Agentic IDE"},
            ],
            "columns": ["竞品", "产品定位"],
        }
    ])

    issues = check_competitor_coverage(analysis)

    assert not [issue for issue in issues if "对比表" in issue.description]


def test_local_report_sources_do_not_trigger_domain_diversity_issue():
    issues = check_evidence_diversity(make_analysis())

    assert not [issue for issue in issues if "域名" in issue.description]

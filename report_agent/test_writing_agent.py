"""Writing Agent 冒烟测试。

默认只跑 offline 模式，使用 mock 搜索结果和 deterministic fallback，不调用云端
模型或搜索 API。real 模式只在手动选择时启用。

Run offline flow test, without cloud API calls:
    python report_agent/test_writing_agent.py --mode offline

Run optional real LLM mode:
    python report_agent/test_writing_agent.py --mode real
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, List


def _load_agent_symbols():
    """加载被测对象。

    正常情况下走包导入；如果父包因搜索/爬虫依赖缺失导致导入失败，则退回到
    writing_agent 目录内的直接导入，让本模块流程测试不被无关模块阻塞。
    """

    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        from report_agent.core import run_writing_agent
        from report_agent.models import ReportPackage, WritingAgentConfig

        return run_writing_agent, WritingAgentConfig, ReportPackage
    except Exception:
        current_dir = Path(__file__).resolve().parent
        if str(current_dir) not in sys.path:
            sys.path.insert(0, str(current_dir))
        from core import run_writing_agent
        from models import ReportPackage, WritingAgentConfig

        return run_writing_agent, WritingAgentConfig, ReportPackage


run_writing_agent, WritingAgentConfig, ReportPackage = _load_agent_symbols()


def mock_search_results() -> List[dict[str, Any]]:
    """构造上游 SearchResult 的最小等价数据。"""

    return [
        {
            "title": "AgentFlow 企业版产品介绍",
            "url": "https://example.com/agentflow",
            "snippet": "siteName: AgentFlow\ndate: 2026-03-01\nAgentFlow 面向企业团队，强调多步骤任务规划、工具调用和审批日志。",
            "content": (
                "AgentFlow 面向企业团队，支持把调研、数据整理和报告生成拆成多步骤任务。"
                "产品提供工具调用、执行状态展示、审批日志和权限控制，帮助团队在自动化执行时保留人工确认。"
            ),
            "source": "mock",
            "content_source": "Playwright网页正文",
        },
        {
            "title": "ResearchPilot 评测：适合产品经理的竞品调研 Agent",
            "url": "https://example.com/researchpilot-review",
            "snippet": "date: 2026-02-10\n评测提到 ResearchPilot 模板丰富，但高级配置需要理解 API 和数据源权限。",
            "content": (
                "ResearchPilot 提供竞品调研模板、资料归纳和引用导出。"
                "评测认为它适合产品经理快速生成初稿，但在连接企业内部数据源时配置较复杂，普通用户需要学习成本。"
            ),
            "source": "mock",
            "content_source": "网页正文",
        },
        {
            "title": "AutoPM Agent 定价与集成说明",
            "url": "https://example.com/autopm-pricing",
            "snippet": "date: 2025-12-20\nAutoPM Agent 提供团队订阅和企业套餐，支持 API、Slack 与知识库集成。",
            "content": (
                "AutoPM Agent 采用团队订阅和企业套餐，主打 API、Slack、知识库和项目管理工具集成。"
                "企业套餐强调审计、权限、专属支持和数据隔离。"
            ),
            "source": "mock",
            "content_source": "网页正文",
        },
    ]


def config_for_mode(mode: str):
    """根据测试模式生成配置。

    offline 明确设置 `use_llm=False`；real 才读取主脚本里的 LLM 配置。
    """

    if mode == "offline":
        return WritingAgentConfig(use_llm=False, verbose=True)

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from run_similar_product_reports import provider_llm_config

    api_key, base_url, model = provider_llm_config()
    return WritingAgentConfig(
        llm_api_key=api_key,
        llm_base_url=base_url,
        llm_model=model,
        use_llm=True,
        verbose=True,
    )


def assert_report_package(package: ReportPackage) -> None:
    """断言输出包满足下游可消费的最低协议。"""

    assert package.report_markdown.strip(), "report_markdown should not be empty"
    assert package.sources, "sources should not be empty"
    assert package.claim_evidence_map, "claim_evidence_map should not be empty"

    analysis = package.structured_analysis
    for key in [
        "evidence_cards",
        "pm_insights",
        "comparison_tables",
        "swot",
        "recommendations",
    ]:
        assert key in analysis, f"structured_analysis missing key: {key}"
        assert analysis[key], f"structured_analysis key should not be empty: {key}"

    for item in package.claim_evidence_map:
        assert item.get("evidence_ids"), "claim should bind evidence_ids"
        assert item.get("source_ids"), "claim should bind source_ids"

    assert "pending_search_query" not in package.report_markdown
    assert "pending_search_query" not in str(analysis.get("comparison_tables", ""))

    for section in [
        "核心结论",
        "竞品分类",
        "用户场景",
        "重点竞品拆解",
        "横向能力对比",
        "SWOT",
        "产品策略建议",
        "资料来源",
    ]:
        assert section in package.report_markdown, f"report missing section: {section}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Writing agent smoke test")
    parser.add_argument(
        "--mode",
        choices=["offline", "real"],
        default=os.getenv("WRITING_AGENT_TEST_MODE", "offline"),
        help="offline only tests local flow; real calls the configured LLM API",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = config_for_mode(args.mode)
    package = run_writing_agent(
        mock_search_results(),
        config=config,
        task_id=f"test_{args.mode}",
        analysis_goal="验证 writing agent 是否能生成可检测的竞品分析报告包",
        target_domain="AI Agent 竞品调研工具",
        competitors=["AgentFlow", "ResearchPilot", "AutoPM Agent"],
    )
    assert_report_package(package)

    print("Writing agent smoke test passed")
    print(f"mode: {args.mode}")
    print(f"sources: {len(package.sources)}")
    print(f"claims: {len(package.claim_evidence_map)}")
    print(f"report_chars: {len(package.report_markdown)}")
    if package.missing_info:
        print(f"missing_info: {package.missing_info}")
    if package.low_confidence_claims:
        print(f"low_confidence_claims: {package.low_confidence_claims}")


if __name__ == "__main__":
    main()

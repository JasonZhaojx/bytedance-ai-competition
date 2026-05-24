"""搜索Agent和分析Agent测试脚本."""

from typing import Optional
from pathlib import Path

from agents.search_agent.search import SearchConfig, search, SearchSource
from agents.analysis_agent.product_workflow import (
    ProductWorkflowConfig,
    run_product_workflow,
)
from agents.quality_agent.quality_agent import QualityConfig


def test_search_agent(product_name: str = "iPhone 15") -> None:
    """测试搜索Agent基本功能."""
    print("\n" + "=" * 60)
    print("搜索Agent测试")
    print("=" * 60)

    config = SearchConfig(
        source=SearchSource.DUCKDUCKGO,
        count=3,
        timeout=10,
    )

    print(f"\n搜索关键词: {product_name}")
    results = search(product_name, config)

    print(f"\n搜索结果: {len(results)} 个")
    for i, result in enumerate(results, 1):
        print(f"\n{i}. {result.title}")
        print(f"   URL: {result.url}")
        print(f"   摘要: {result.snippet[:100]}..." if result.snippet else "")


def test_analysis_agent_simple(product_name: str = "iPhone 15") -> None:
    """简化版分析Agent测试（跳过质检）."""
    print("\n" + "=" * 60)
    print("分析Agent测试（简化版）")
    print("=" * 60)

    search_config = SearchConfig(
        source=SearchSource.DUCKDUCKGO,
        count=3,
        crawl_max_chars=2000,
    )

    config = ProductWorkflowConfig(
        llm_api_key="test",
        llm_base_url="https://api.example.com",
        llm_model="test-model",
        search_config=search_config,
        use_quality_inspection=False,
        max_items_per_platform=2,
        max_review_items=1,
    )

    print(f"\n分析产品: {product_name}")
    try:
        result = run_product_workflow(product_name, config)

        print(f"\n候选产品数量: {len(result.candidates)}")
        print(f"评论证据数量: {len(result.reviews)}")

        for i, candidate in enumerate(result.candidates, 1):
            print(f"\n候选 {i}: {candidate.title}")
            print(f"   平台: {candidate.platform}")
            print(f"   提取参数: {candidate.extracted_params}")

        print(f"\n总结长度: {len(result.summary)} 字符")
        print(f"\n测试完成！")

    except Exception as e:
        print(f"\n错误: {e}")
        print("\n提示: 本测试需要真实的LLM API key才能完整运行")


def test_quality_agent_with_mock() -> None:
    """使用模拟数据测试质检Agent."""
    from agents.quality_agent.quality_agent import inspect_quality
    from agents.quality_agent.quality_agent import QualityReport
    from agents.analysis_agent.product_workflow import ProductWorkflowResult

    print("\n" + "=" * 60)
    print("质检Agent测试（模拟数据）")
    print("=" * 60)

    config = QualityConfig(
        llm_api_key="test",
        llm_base_url="https://api.example.com",
        llm_model="test-model",
    )

    result = ProductWorkflowResult(
        product_name="Test Product",
        candidates=[],
        reviews=[],
        summary="Test summary",
        raw_prompt="",
    )

    report = inspect_quality(result, config)
    print(f"\n质检结果: {'通过' if report.passed else '未通过'}")
    print(f"质检分数: {report.score:.2f}")
    print(f"置信度等级: {report.confidence_level}")
    print(f"问题数量: {len(report.issues)}")


def main() -> None:
    """主测试函数."""
    print("\n" + "=" * 60)
    print("搜索Agent & 分析Agent 测试")
    print("=" * 60)

    # 测试搜索Agent
    test_search_agent("iPhone 15")

    # 测试分析Agent（简化版）
    # 注意: 需要真实LLM API才能运行
    test_quality_agent_with_mock()

    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()

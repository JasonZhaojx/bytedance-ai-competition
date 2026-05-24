"""简洁版搜索Agent和分析Agent测试."""

import sys
import os

# 确保输出编码为UTF-8
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from agents.search_agent.search import SearchConfig, search, SearchSource


def test_search_basic() -> None:
    """基础搜索测试."""
    print("\n" + "=" * 60)
    print("搜索Agent测试")
    print("=" * 60)

    config = SearchConfig(
        source=SearchSource.DUCKDUCKGO,
        count=3,
        timeout=10,
    )

    product_name = "iPhone 15"
    print(f"\n搜索: {product_name}")

    try:
        results = search(product_name, config)
        print(f"找到: {len(results)} 个结果")

        for i, result in enumerate(results, 1):
            # 安全打印（跳过可能有编码问题的字符）
            safe_title = result.title.encode('gbk', errors='ignore').decode('gbk')
            print(f"\n{i}. {safe_title}")
            print(f"   URL: {result.url}")

        print("\n✓ 搜索Agent正常工作")
        return True

    except Exception as e:
        print(f"\n✗ 错误: {e}")
        return False


def test_available_functions() -> None:
    """测试模块导入和基本功能."""
    print("\n" + "=" * 60)
    print("模块导入测试")
    print("=" * 60)

    tests = [
        ("搜索模块", "agents.search_agent.search"),
        ("分析模块", "agents.analysis_agent.product_workflow"),
        ("质检模块", "agents.quality_agent.quality_agent"),
        ("LLM客户端", "agents.workflow.llm_client"),
    ]

    for name, module_name in tests:
        try:
            __import__(module_name)
            print(f"✓ {name} - 导入成功")
        except Exception as e:
            print(f"✗ {name} - 导入失败: {e}")


def main() -> None:
    """主函数."""
    print("\n" + "=" * 60)
    print("智能产品分析系统 - 测试工具")
    print("=" * 60)

    test_available_functions()
    search_ok = test_search_basic()

    print("\n" + "=" * 60)
    print("如何使用")
    print("=" * 60)
    print("\n1. 运行完整工作流:")
    print("   python run_similar_product_reports.py \"产品名称\"")
    print("\n2. 查看测试指南:")
    print("   docs/AGENT_TESTING.md")
    print("\n3. 运行工具脚本:")
    print("   python tools/find_similar_products.py")

    if search_ok:
        print("\n\n✓ 基础功能测试通过")
    else:
        print("\n\n✗ 需要进一步排查问题")


if __name__ == "__main__":
    main()

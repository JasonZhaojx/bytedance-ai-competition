"""Test quality agent versatility across different product types."""

from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.quality_agent import (
    QualityConfig,
    DomainConfig,
    inspect_quality,
    ProductType,
)


@dataclass
class ProductCandidate:
    title: str
    url: str
    snippet: str = ""
    page_text: str = ""
    extracted_params: Dict[str, str] = field(default_factory=dict)
    blocked_or_empty: bool = False


@dataclass
class ReviewEvidence:
    source_type: str
    title: str
    url: str
    snippet: str = ""
    page_text: str = ""
    blocked_or_empty: bool = False


@dataclass
class ProductWorkflowResult:
    product_name: str
    candidates: List[ProductCandidate]
    reviews: List[ReviewEvidence]
    summary: str
    raw_prompt: str


def create_product(name: str, product_type: str, params: Dict[str, str]) -> ProductWorkflowResult:
    """创建测试用产品数据."""
    candidates = [
        ProductCandidate(
            title=f"{name} 官方产品页",
            url="https://example.com/product",
            snippet=f"{name} - 专业级产品",
            page_text=f"这是{product_type}类型的{product_type}产品，详细参数如下：{params}",
            extracted_params=params,
            blocked_or_empty=False,
        ),
    ]
    return ProductWorkflowResult(
        product_name=name,
        candidates=candidates,
        reviews=[],
        summary=f"# {name}\n\n这是一个{product_type}产品",
        raw_prompt=f"分析{name}",
    )


def test_product_type(product_name: str, product_type_hint: str, params: Dict[str, str], expected_type: ProductType):
    """测试单个产品类型识别."""
    result = create_product(product_name, product_type_hint, params)

    config = QualityConfig(
        llm_api_key="test",
        llm_base_url="https://test.com",
        llm_model="test",
        min_score_threshold=0.5,
        min_evidence_count=1,
        verbose=False,
    )

    report = inspect_quality(result, config)

    status = "OK" if report.domain_type == expected_type else "FAIL"
    print(f"[{status}] {product_name:20s} | Expected: {expected_type.value:12s} | Got: {report.domain_type.value:12s} | Score: {report.score:.2f}")

    return report.domain_type == expected_type


def main():
    print("=" * 70)
    print("Quality Agent Versatility Test - Different Product Types")
    print("=" * 70)

    results = []

    print("\n--- AI_TOOLS (AI编程工具) ---")
    results.append(test_product_type(
        "通义灵码", "AI编程工具",
        {"developer": "阿里云", "platform": "Windows/macOS", "pricing": "免费/Pro", "features": "代码补全、生成、解释"},
        ProductType.AI_TOOLS
    ))
    results.append(test_product_type(
        "CodeBuddy", "AI编程助手",
        {"developer": "腾讯", "platform": "IDE插件", "pricing": "免费版", "supported_languages": "Python/Java/JS"},
        ProductType.AI_TOOLS
    ))
    results.append(test_product_type(
        "Copilot", "AI代码助手",
        {"developer": "GitHub/Microsoft", "platform": "VS Code", "pricing": "$10/月", "features": "代码补全"},
        ProductType.AI_TOOLS
    ))

    print("\n--- SOFTWARE (软件产品) ---")
    results.append(test_product_type(
        "Photoshop", "图形编辑软件",
        {"developer": "Adobe", "platform": "Windows/macOS", "pricing": "$54.99/月", "rating": "4.5/5"},
        ProductType.SOFTWARE
    ))
    results.append(test_product_type(
        "钉钉", "企业通讯软件",
        {"developer": "阿里巴巴", "platform": "iOS/Android/PC", "pricing": "免费/专业版", "rating": "4.3/5"},
        ProductType.SOFTWARE
    ))
    results.append(test_product_type(
        "微信", "社交软件",
        {"developer": "腾讯", "platform": "多平台", "pricing": "免费", "rating": "4.6/5", "features": "聊天/支付/朋友圈"},
        ProductType.SOFTWARE
    ))

    print("\n--- HARDWARE (硬件产品) ---")
    results.append(test_product_type(
        "小米手机15", "智能手机",
        {"brand": "小米", "model": "15 Pro", "price": "4999元", "spec": "骁龙8 Gen4/16GB/512GB"},
        ProductType.HARDWARE
    ))
    results.append(test_product_type(
        "MacBook Pro", "笔记本电脑",
        {"brand": "Apple", "model": "MacBook Pro 14", "price": "14999元", "spec": "M4 Pro/36GB/1TB"},
        ProductType.HARDWARE
    ))
    results.append(test_product_type(
        "华为路由器", "网络设备",
        {"brand": "华为", "model": "AX12 Pro", "price": "399元", "spec": "WiFi 6+/3200Mbps"},
        ProductType.HARDWARE
    ))

    print("\n" + "=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"RESULT: {passed}/{total} tests passed")
    if passed == total:
        print("All product types correctly identified!")
    else:
        print(f"FAILED: {total - passed} tests failed")
    print("=" * 70)


if __name__ == "__main__":
    main()

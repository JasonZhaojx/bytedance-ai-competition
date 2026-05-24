"""单独测试质检Agent全流程."""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.quality_agent.config import (
    QualityConfig,
    DomainConfig,
    IssueType,
    IssueSeverity,
    ConfidenceLevel,
)
from agents.quality_agent.core import (
    inspect_quality,
    llm_enhanced_inspect,
    _detect_product_type_with_llm,
    _detect_product_type_by_keywords,
)


class MockCandidate:
    """模拟候选产品."""
    def __init__(self, title, url=None, extracted_params=None, page_text="", blocked_or_empty=False):
        self.title = title
        self.url = url
        self.extracted_params = extracted_params or {}
        self.page_text = page_text
        self.blocked_or_empty = blocked_or_empty


class MockReview:
    """模拟评论."""
    def __init__(self, title, page_text="", blocked_or_empty=False):
        self.title = title
        self.page_text = page_text
        self.blocked_or_empty = blocked_or_empty
        self.extracted_params = {}


class MockWorkflowResult:
    """模拟工作流结果."""
    def __init__(self, product_name, candidates=None, reviews=None, summary=""):
        self.product_name = product_name
        self.candidates = candidates or []
        self.reviews = reviews or []
        self.summary = summary


def create_test_data(product_type="hardware", quality="good"):
    """创建测试数据."""
    if product_type == "software":
        if quality == "good":
            candidates = [
                MockCandidate(
                    "微信APP官方下载",
                    url="https://weixin.qq.com/",
                    extracted_params={
                        "developer": "腾讯",
                        "platform": "iOS/Android",
                        "pricing": "免费",
                        "features": "社交聊天、支付、小程序",
                        "rating": "4.8"
                    },
                    page_text="微信是一款跨平台的通讯工具..." * 50
                ),
                MockCandidate(
                    "微信功能介绍",
                    url="https://apps.apple.com/cn/app/微信/id414478124",
                    extracted_params={
                        "developer": "腾讯",
                        "platform": "iOS",
                        "pricing": "免费",
                        "features": "朋友圈、公众号、视频号",
                        "rating": "4.7"
                    },
                    page_text="微信支持多种功能..." * 30
                ),
                MockCandidate(
                    "微信使用指南",
                    url="https://support.weixin.qq.com/",
                    extracted_params={
                        "developer": "腾讯",
                        "platform": "多平台",
                        "pricing": "免费"
                    },
                    page_text="微信使用教程..." * 20
                )
            ]
            reviews = [
                MockReview("微信用户评价", page_text="非常好用的社交软件...")
            ]
            summary = "微信是腾讯公司开发的一款社交应用，支持聊天、支付、小程序等功能，用户评价良好。"
        else:
            candidates = [
                MockCandidate(
                    "未知软件",
                    url=None,
                    extracted_params={},
                    page_text="short",
                    blocked_or_empty=False
                )
            ]
            reviews = []
            summary = "信息不足"
            
    else:  # hardware
        if quality == "good":
            candidates = [
                MockCandidate(
                    "iPhone 15 Pro 256GB",
                    url="https://www.apple.com.cn/shop/buy-iphone/iphone-15-pro",
                    extracted_params={
                        "brand": "Apple",
                        "model": "iPhone 15 Pro",
                        "price": 8999,
                        "spec": "256GB",
                        "color": "钛金属黑色",
                        "screen": "6.1英寸"
                    },
                    page_text="iPhone 15 Pro采用钛金属设计..." * 50
                ),
                MockCandidate(
                    "iPhone 15 Pro 京东自营",
                    url="https://jd.com/iphone15pro",
                    extracted_params={
                        "brand": "Apple",
                        "model": "iPhone 15 Pro",
                        "price": 8999,
                        "spec": "256GB",
                        "color": "钛金属白色"
                    },
                    page_text="京东自营正品保障..." * 30
                ),
                MockCandidate(
                    "iPhone 15 Pro 评测",
                    url="https://www.digitaltrends.com/mobile/iphone-15-pro-review/",
                    extracted_params={
                        "brand": "Apple",
                        "model": "iPhone 15 Pro",
                        "price": 8999,
                        "spec": "256GB",
                        "rating": "4.5"
                    },
                    page_text="iPhone 15 Pro评测报告..." * 40
                )
            ]
            reviews = [
                MockReview("iPhone 15 Pro用户评价", page_text="手感很好，拍照效果出色...")
            ]
            summary = "iPhone 15 Pro是Apple公司2023年发布的旗舰手机，采用钛金属设计，搭载A17 Pro芯片，起售价8999元。"
        else:
            candidates = [
                MockCandidate(
                    "未知手机",
                    url=None,
                    extracted_params={},
                    page_text="short"
                ),
                MockCandidate(
                    "另一款手机",
                    url="https://example.com",
                    extracted_params={"price": 100},
                    page_text="content"
                ),
                MockCandidate(
                    "价格冲突手机",
                    url="https://example.com",
                    extracted_params={"price": 300},  # 价格差异大
                    page_text="content"
                )
            ]
            reviews = []
            summary = "信息不足"
    
    return MockWorkflowResult(
        product_name="微信APP" if product_type == "software" else "iPhone 15 Pro",
        candidates=candidates,
        reviews=reviews,
        summary=summary
    )


def print_report(report, title="质检报告"):
    """打印质检报告."""
    print("\n" + "="*60)
    print(f"【{title}】")
    print("="*60)
    print(f"质检通过: {'[OK] 通过' if report.passed else '[FAIL] 未通过'}")
    print(f"质检分数: {report.score:.2f}")
    print(f"置信度等级: {report.confidence_level.value}")
    print(f"是否需要人工审核: {'是' if report.needs_human_review else '否'}")
    print(f"质检轮次: {report.inspection_rounds}")
    print(f"质检耗时: {report.inspection_time_sec:.2f}秒")
    
    if report.issues:
        print("\n【发现的问题】")
        for i, issue in enumerate(report.issues, 1):
            severity_icon = {
                IssueSeverity.CRITICAL: "[CRITICAL]",
                IssueSeverity.MAJOR: "[MAJOR]",
                IssueSeverity.MINOR: "[MINOR]"
            }[issue.severity]
            print(f"\n{i}. {severity_icon} {issue.type.value}")
            print(f"   描述: {issue.description}")
            print(f"   严重程度: {issue.severity.value}")
            print(f"   建议: {issue.suggestion}")
            print(f"   置信度: {issue.confidence:.2f}")
    
    if report.suggestions:
        print("\n【改进建议】")
        for i, suggestion in enumerate(report.suggestions, 1):
            print(f"{i}. {suggestion}")
    
    if report.required_resources:
        print("\n【需要补充的资源】")
        for i, resource in enumerate(report.required_resources, 1):
            print(f"{i}. {resource}")
    
    print("="*60 + "\n")


def main():
    """主函数."""
    print("[START] 质检Agent单独测试")
    print("-------------------")
    
    # 1. 配置质检Agent
    print("\n[STEP 1] 配置质检Agent")
    config = QualityConfig(
        llm_api_key="ARK_API_KEY_REDACTED",  # 请替换为实际API key
        llm_base_url="https://ark.cn-beijing.volces.com/api/text/",
        llm_model="Doubao-Seed-2.0-lite",
        verbose=True,
        enable_multistage_inspection=True
    )
    print(f"LLM模型: {config.llm_model}")
    print(f"是否启用多阶段质检: {config.enable_multistage_inspection}")
    print(f"分数阈值: {config.min_score_threshold}")
    
    # 2. 创建测试数据
    print("\n[STEP 2] 创建测试数据")
    print("请选择测试场景:")
    print("  [1] 硬件产品 - 高质量数据")
    print("  [2] 硬件产品 - 低质量数据")
    print("  [3] 软件产品 - 高质量数据")
    print("  [4] 软件产品 - 低质量数据")
    
    try:
        choice = int(input("请输入选择 (1-4): ") or "1")
    except:
        choice = 1
    
    scenarios = {
        1: ("hardware", "good"),
        2: ("hardware", "bad"),
        3: ("software", "good"),
        4: ("software", "bad")
    }
    product_type, quality = scenarios.get(choice, ("hardware", "good"))
    result = create_test_data(product_type, quality)
    print(f"测试场景: {product_type}产品 - {'高质量' if quality == 'good' else '低质量'}数据")
    print(f"候选产品数量: {len(result.candidates)}")
    print(f"评论数量: {len(result.reviews)}")
    
    # 3. 产品类型识别
    print("\n[STEP 3] 产品类型识别")
    from agents.quality_agent.core import _detect_product_type_by_keywords
    detected_type = _detect_product_type_by_keywords(result)
    print(f"关键词检测结果: {detected_type.value}")
    
    # 4. 快速质检
    print("\n[STEP 4] 执行快速质检")
    quick_report = inspect_quality(result, config)
    print_report(quick_report, "快速质检报告")
    
    # 5. LLM增强质检
    print("\n[STEP 5] 执行LLM增强质检")
    print("[WARN] 需要配置有效的LLM API Key才能运行")
    use_llm = input("是否继续运行LLM增强质检? (y/N): ").strip().lower() == "y"
    
    if use_llm:
        try:
            llm_report = llm_enhanced_inspect(result, config)
            print_report(llm_report, "LLM增强质检报告")
        except Exception as e:
            print(f"[ERROR] LLM增强质检失败: {str(e)}")
            print("请检查API Key配置是否正确")
    
    # 6. 总结
    print("\n[STEP 6] 测试总结")
    print("-------------------")
    print("快速质检结果:", "通过" if quick_report.passed else "未通过")
    print("快速质检分数:", f"{quick_report.score:.2f}")
    print("快速质检置信度:", quick_report.confidence_level.value)
    
    if quick_report.needs_human_review:
        print("\n[WARN] 需要人工审核")
        print("建议: " + ", ".join(quick_report.suggestions[:3]))


if __name__ == "__main__":
    main()

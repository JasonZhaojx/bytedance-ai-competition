"""Test file for quality agent."""

from __future__ import annotations

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.quality_agent import (
    LLMConfig,
    QualityConfig,
    OutputConfig,
    DomainConfig,
    QualityFeedbackRecorder,
    IssueType,
    IssueSeverity,
    ProductType,
)


def test_imports():
    """测试导入是否正常."""
    print("Testing imports...")
    print(f"QualityConfig: {QualityConfig}")
    print(f"DomainConfig: {DomainConfig}")
    print(f"IssueType: {list(IssueType)}")
    print(f"IssueSeverity: {list(IssueSeverity)}")
    print(f"ProductType: {list(ProductType)}")
    print("[OK] Imports test passed")


def test_config():
    """测试配置类."""
    print("\nTesting config classes...")
    
    # 测试 QualityConfig
    config = QualityConfig(
        min_score_threshold=0.7,
        output=OutputConfig(verbose=True),
    )
    print(f"QualityConfig created successfully: {config}")
    
    # 测试 DomainConfig
    hardware_config = DomainConfig.hardware()
    software_config = DomainConfig.software()
    print(f"Hardware config: {hardware_config.product_type}, required fields: {hardware_config.required_fields}")
    print(f"Software config: {software_config.product_type}, required fields: {software_config.required_fields}")
    print("[OK] Config classes test passed")


def test_feedback_recorder():
    """测试反馈记录器."""
    print("\nTesting feedback recorder...")
    
    recorder = QualityFeedbackRecorder(log_dir="./test_feedback")
    print(f"Feedback recorder created successfully, log dir: {recorder.log_dir}")
    
    # 列出反馈文件（应该是空的）
    feedbacks = recorder.list_feedbacks()
    print(f"Existing feedback files: {feedbacks}")
    print("[OK] Feedback recorder test passed")


def main():
    """运行所有测试."""
    print("=" * 50)
    print("Quality Agent Test")
    print("=" * 50)
    
    test_imports()
    test_config()
    test_feedback_recorder()
    
    print("\n" + "=" * 50)
    print("All tests passed!")
    print("=" * 50)


if __name__ == "__main__":
    main()

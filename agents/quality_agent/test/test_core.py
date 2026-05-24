"""Tests for quality agent core logic."""

import unittest
from unittest.mock import MagicMock, patch

from agents.quality_agent.config import (
    ConfidenceLevel,
    DomainConfig,
    IssueSeverity,
    IssueType,
    ProductType,
    QualityConfig,
    QualityReport,
)
from agents.quality_agent.core import (
    _calculate_confidence,
    _calculate_score,
    _calculate_aggregate_evidence_quality,
    _check_conflicting_evidence,
    _check_evidence_sufficiency,
    _check_field_completeness,
    _check_source_tracing,
    _detect_product_type_by_keywords,
    _evaluate_evidence_quality,
)


class MockCandidate:
    """模拟候选产品对象."""
    def __init__(self, title, extracted_params=None, url=None, page_text="", blocked_or_empty=False):
        self.title = title
        self.extracted_params = extracted_params or {}
        self.url = url
        self.page_text = page_text
        self.blocked_or_empty = blocked_or_empty


class MockReview:
    """模拟评论对象."""
    def __init__(self, title, page_text="", blocked_or_empty=False):
        self.title = title
        self.page_text = page_text
        self.blocked_or_empty = blocked_or_empty
        self.extracted_params = {}


class MockResult:
    """模拟工作流结果对象."""
    def __init__(self, product_name, candidates=None, reviews=None):
        self.product_name = product_name
        self.candidates = candidates or []
        self.reviews = reviews or []


class TestProductTypeDetection(unittest.TestCase):
    """测试产品类型检测."""

    def test_detect_software_by_keywords(self):
        """测试通过关键词检测软件产品."""
        result = MockResult("微信app")
        product_type = _detect_product_type_by_keywords(result)
        self.assertEqual(product_type, ProductType.SOFTWARE)

    def test_detect_hardware_by_keywords(self):
        """测试通过关键词检测硬件产品."""
        result = MockResult("iPhone 15手机")
        product_type = _detect_product_type_by_keywords(result)
        self.assertEqual(product_type, ProductType.HARDWARE)

    def test_default_to_hardware(self):
        """测试默认返回硬件类型."""
        result = MockResult("未知产品")
        product_type = _detect_product_type_by_keywords(result)
        self.assertEqual(product_type, ProductType.HARDWARE)


class TestEvidenceQuality(unittest.TestCase):
    """测试证据质量评估."""

    def test_blocked_evidence(self):
        """测试被拦截的证据."""
        candidate = MockCandidate("Test", blocked_or_empty=True)
        domain_config = DomainConfig.hardware()
        quality = _evaluate_evidence_quality(candidate, domain_config)
        self.assertEqual(quality.score, 1.0)
        self.assertTrue(quality.blocked)

    def test_high_quality_evidence(self):
        """测试高质量证据."""
        candidate = MockCandidate(
            "Test",
            extracted_params={"brand": "Apple", "model": "iPhone", "price": 5999, "spec": "128GB", "color": "black"},
            page_text="This is a very long content" * 200
        )
        domain_config = DomainConfig.hardware()
        quality = _evaluate_evidence_quality(candidate, domain_config)
        self.assertEqual(quality.score, 1.0)  # 分数被限制在1.0以内
        self.assertTrue(quality.content_length_ok)

    def test_low_quality_evidence(self):
        """测试低质量证据."""
        candidate = MockCandidate("Test", extracted_params={}, page_text="short")
        domain_config = DomainConfig.hardware()
        quality = _evaluate_evidence_quality(candidate, domain_config)
        self.assertEqual(quality.score, 1.0)


class TestAggregateEvidenceQuality(unittest.TestCase):
    """测试证据质量汇总."""

    def test_empty_evidence(self):
        """测试空证据列表."""
        result = MockResult("Test", candidates=[], reviews=[])
        domain_config = DomainConfig.hardware()
        quality = _calculate_aggregate_evidence_quality(result, domain_config)
        self.assertEqual(quality, 0.0)

    def test_multiple_evidence(self):
        """测试多个证据."""
        candidates = [
            MockCandidate("Product A", extracted_params={"price": 100}, page_text="content" * 100),
            MockCandidate("Product B", extracted_params={"price": 200}, page_text="content" * 50),
        ]
        result = MockResult("Test", candidates=candidates)
        domain_config = DomainConfig.hardware()
        quality = _calculate_aggregate_evidence_quality(result, domain_config)
        self.assertGreater(quality, 0.0)


class TestFieldCompleteness(unittest.TestCase):
    """测试字段完整性检查."""

    def test_all_fields_present(self):
        """测试所有字段都存在."""
        candidates = [
            MockCandidate("Product", extracted_params={"brand": "Apple", "model": "iPhone", "price": 5999, "spec": "128GB"})
        ]
        result = MockResult("Test", candidates=candidates)
        config = QualityConfig(
            llm_api_key="test",
            llm_base_url="https://api.example.com",
            llm_model="gpt-4o"
        )
        domain_config = DomainConfig.hardware()
        issues = _check_field_completeness(result, config, domain_config)
        self.assertEqual(len(issues), 0)

    def test_missing_fields(self):
        """测试缺少字段."""
        candidates = [
            MockCandidate("Product", extracted_params={"brand": "Apple", "model": "iPhone"})
        ]
        result = MockResult("Test", candidates=candidates)
        config = QualityConfig(
            llm_api_key="test",
            llm_base_url="https://api.example.com",
            llm_model="gpt-4o"
        )
        domain_config = DomainConfig.hardware()
        issues = _check_field_completeness(result, config, domain_config)
        self.assertGreater(len(issues), 0)


class TestEvidenceSufficiency(unittest.TestCase):
    """测试证据充分性检查."""

    def test_insufficient_evidence(self):
        """测试证据不足."""
        candidates = [MockCandidate("Product 1")]
        reviews = []
        result = MockResult("Test", candidates=candidates, reviews=reviews)
        config = QualityConfig(
            llm_api_key="test",
            llm_base_url="https://api.example.com",
            llm_model="gpt-4o",
            min_evidence_count=3
        )
        issues = _check_evidence_sufficiency(result, config)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].type, IssueType.INSUFFICIENT_EVIDENCE)

    def test_sufficient_evidence(self):
        """测试证据充足."""
        candidates = [MockCandidate("Product 1"), MockCandidate("Product 2"), MockCandidate("Product 3")]
        result = MockResult("Test", candidates=candidates)
        config = QualityConfig(
            llm_api_key="test",
            llm_base_url="https://api.example.com",
            llm_model="gpt-4o",
            min_evidence_count=3
        )
        issues = _check_evidence_sufficiency(result, config)
        self.assertEqual(len(issues), 0)


class TestSourceTracing(unittest.TestCase):
    """测试来源追溯性检查."""

    def test_missing_url(self):
        """测试缺少URL."""
        candidates = [MockCandidate("Product", url=None)]
        result = MockResult("Test", candidates=candidates)
        issues = _check_source_tracing(result)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].type, IssueType.MISSING_SOURCE)

    def test_url_present(self):
        """测试URL存在."""
        candidates = [MockCandidate("Product", url="https://example.com")]
        result = MockResult("Test", candidates=candidates)
        issues = _check_source_tracing(result)
        self.assertEqual(len(issues), 0)


class TestConflictingEvidence(unittest.TestCase):
    """测试冲突证据检查."""

    def test_price_conflict(self):
        """测试价格冲突（差异超过50%）."""
        candidates = [
            MockCandidate("Product A", extracted_params={"price": 100}),
            MockCandidate("Product B", extracted_params={"price": 250}),  # 差异60% > 50%阈值
        ]
        result = MockResult("Test", candidates=candidates)
        domain_config = DomainConfig.hardware()
        issues = _check_conflicting_evidence(result, domain_config)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].type, IssueType.CONFLICTING_EVIDENCE)

    def test_no_price_conflict(self):
        """测试无价格冲突."""
        candidates = [
            MockCandidate("Product A", extracted_params={"price": 100}),
            MockCandidate("Product B", extracted_params={"price": 110}),
        ]
        result = MockResult("Test", candidates=candidates)
        domain_config = DomainConfig.hardware()
        issues = _check_conflicting_evidence(result, domain_config)
        self.assertEqual(len(issues), 0)


class TestScoreCalculation(unittest.TestCase):
    """测试评分计算."""

    def test_no_issues(self):
        """测试无问题情况下的评分."""
        score = _calculate_score([], evidence_quality=1.0)
        self.assertEqual(score, 1.0)

    def test_with_issues(self):
        """测试有问题情况下的评分."""
        issues = [
            MagicMock(severity=IssueSeverity.MAJOR, confidence=1.0),
            MagicMock(severity=IssueSeverity.MINOR, confidence=1.0),
        ]
        score = _calculate_score(issues, evidence_quality=1.0)
        self.assertAlmostEqual(score, 0.8, places=6)  # 处理浮点数精度问题


class TestConfidenceCalculation(unittest.TestCase):
    """测试置信度计算."""

    def test_high_confidence(self):
        """测试高置信度."""
        issues = []
        confidence = _calculate_confidence(score=0.9, issues=issues, evidence_quality=0.8, total_evidence=5)
        self.assertEqual(confidence, ConfidenceLevel.HIGH)

    def test_medium_confidence(self):
        """测试中置信度."""
        issues = []
        confidence = _calculate_confidence(score=0.7, issues=issues, evidence_quality=0.7, total_evidence=3)
        self.assertEqual(confidence, ConfidenceLevel.MEDIUM)

    def test_low_confidence(self):
        """测试低置信度."""
        issues = [MagicMock(severity=IssueSeverity.CRITICAL)]
        confidence = _calculate_confidence(score=0.5, issues=issues, evidence_quality=0.5, total_evidence=2)
        self.assertEqual(confidence, ConfidenceLevel.LOW)


if __name__ == "__main__":
    unittest.main()

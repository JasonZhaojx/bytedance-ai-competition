"""Tests for quality agent configuration classes."""

from agents.analysis_agent.product_workflow import ProductWorkflowConfig
import unittest
from agents.quality_agent.config import (
    ConfidenceLevel,
    DomainConfig,
    EvidenceQualityScore,
    IssueSeverity,
    IssueType,
    ProductType,
    QualityConfig,
    QualityIssue,
    QualityReport,
)


class TestEnums(unittest.TestCase):
    """测试枚举类型."""

    def test_issue_severity_values(self):
        """测试问题严重程度枚举."""
        self.assertEqual(IssueSeverity.CRITICAL.value, "critical")
        self.assertEqual(IssueSeverity.MAJOR.value, "major")
        self.assertEqual(IssueSeverity.MINOR.value, "minor")

    def test_issue_type_values(self):
        """测试问题类型枚举."""
        self.assertEqual(IssueType.INCOMPLETE_INFO.value, "incomplete_info")
        self.assertEqual(IssueType.INSUFFICIENT_EVIDENCE.value, "insufficient_evidence")
        self.assertEqual(IssueType.MISSING_SOURCE.value, "missing_source")
        self.assertEqual(IssueType.CONFLICTING_EVIDENCE.value, "conflicting_evidence")

    def test_confidence_level_values(self):
        """测试置信度等级枚举."""
        self.assertEqual(ConfidenceLevel.HIGH.value, "high")
        self.assertEqual(ConfidenceLevel.MEDIUM.value, "medium")
        self.assertEqual(ConfidenceLevel.LOW.value, "low")

    def test_product_type_values(self):
        """测试产品类型枚举."""
        self.assertEqual(ProductType.HARDWARE.value, "hardware")
        self.assertEqual(ProductType.SOFTWARE.value, "software")
        self.assertEqual(ProductType.AUTO_DETECT.value, "auto")


class TestDataClasses(unittest.TestCase):
    """测试数据类."""

    def test_evidence_quality_score(self):
        """测试证据质量评分数据类."""
        score = EvidenceQualityScore(
            score=0.85,
            url_trusted=True,
            content_length_ok=True,
            structured_fields_ok=True,
            blocked=False,
            reasons=["内容长度优秀", "结构化字段丰富"]
        )
        self.assertEqual(score.score, 0.85)
        self.assertTrue(score.url_trusted)
        self.assertEqual(len(score.reasons), 2)

    def test_quality_issue(self):
        """测试质量问题数据类."""
        issue = QualityIssue(
            type=IssueType.INCOMPLETE_INFO,
            severity=IssueSeverity.MAJOR,
            description="缺少价格字段",
            suggestion="补充价格信息",
            explanation="价格是重要的产品信息",
            impact="影响定价分析",
            confidence=0.9,
            affected_fields=["price"]
        )
        self.assertEqual(issue.type, IssueType.INCOMPLETE_INFO)
        self.assertEqual(issue.severity, IssueSeverity.MAJOR)
        self.assertEqual(issue.confidence, 0.9)

    def test_quality_report_defaults(self):
        """测试质量报告默认值."""
        report = QualityReport(
            passed=True,
            score=0.8,
            issues=[],
            suggestions=[],
            required_resources=[]
        )
        self.assertEqual(report.confidence_level, ConfidenceLevel.HIGH)
        self.assertFalse(report.needs_human_review)
        self.assertEqual(report.inspection_rounds, 1)


class TestDomainConfig(unittest.TestCase):
    """测试领域配置."""

    def test_hardware_config(self):
        """测试硬件产品配置."""
        config = DomainConfig.hardware()
        self.assertEqual(config.product_type, ProductType.HARDWARE)
        self.assertIn("brand", config.required_fields)
        self.assertIn("model", config.required_fields)
        self.assertIn("price", config.required_fields)
        self.assertIn("spec", config.required_fields)
        self.assertEqual(config.conflict_threshold, 0.5)

    def test_software_config(self):
        """测试软件产品配置."""
        config = DomainConfig.software()
        self.assertEqual(config.product_type, ProductType.SOFTWARE)
        self.assertIn("developer", config.required_fields)
        self.assertIn("platform", config.required_fields)
        self.assertIn("pricing", config.required_fields)
        self.assertEqual(config.conflict_threshold, 0.3)

    def test_hardware_evidence_weights(self):
        """测试硬件证据权重."""
        config = DomainConfig.hardware()
        self.assertEqual(config.evidence_weight_factor["price"], 1.2)
        self.assertEqual(config.evidence_weight_factor["spec"], 1.1)

    def test_software_evidence_weights(self):
        """测试软件证据权重."""
        config = DomainConfig.software()
        self.assertEqual(config.evidence_weight_factor["features"], 1.3)
        self.assertEqual(config.evidence_weight_factor["platform"], 1.2)


class TestQualityConfig(unittest.TestCase):
    """测试质检配置."""

    def test_config_defaults(self):
        """测试配置默认值."""
        config = ProductWorkflowConfig(
            llm_api_key="ARK_API_KEY_REDACTED",
            llm_base_url="https://ark.cn-beijing.volces.com/api/text/",
            llm_model="Doubao-Seed-2.0-lite",
        )
        self.assertEqual(config.min_score_threshold, 0.6)
        self.assertEqual(config.min_evidence_count, 3)
        self.assertTrue(config.verbose)
        self.assertTrue(config.enable_multistage_inspection)

    def test_config_custom_values(self):
        """测试自定义配置值."""
        config = ProductWorkflowConfig(
            llm_api_key="test-key",
            llm_base_url="https://api.example.com",
            llm_model="gpt-4o",
            min_score_threshold=0.7,
            min_evidence_count=5,
            verbose=False,
            enable_multistage_inspection=False
        )
        self.assertEqual(config.min_score_threshold, 0.7)
        self.assertEqual(config.min_evidence_count, 5)
        self.assertFalse(config.verbose)
        self.assertFalse(config.enable_multistage_inspection)


if __name__ == "__main__":
    unittest.main()

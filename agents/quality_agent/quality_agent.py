"""Quality inspection agent for product analysis reports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Dict, List, Literal, Optional

from ..workflow.llm_client import chat_content

if TYPE_CHECKING:
    from ..analysis_agent.product_workflow import ProductWorkflowResult


class IssueSeverity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class IssueType(str, Enum):
    INCOMPLETE_INFO = "incomplete_info"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    MISSING_SOURCE = "missing_source"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    LOW_QUALITY_EVIDENCE = "low_quality_evidence"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class QualityIssue:
    type: IssueType
    severity: IssueSeverity
    description: str
    suggestion: str
    affected_fields: List[str] = field(default_factory=list)


@dataclass
class QualityReport:
    passed: bool
    score: float
    issues: List[QualityIssue]
    suggestions: List[str]
    required_resources: List[str]
    confidence_level: ConfidenceLevel = ConfidenceLevel.HIGH
    needs_human_review: bool = False
    low_confidence_reasons: List[str] = field(default_factory=list)


@dataclass
class QualityConfig:
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    min_score_threshold: float = 0.6
    min_evidence_count: int = 3
    required_fields: List[str] = field(
        default_factory=lambda: ["brand", "model", "price", "spec"]
    )
    temperature: float = 0.2
    max_tokens: int = 2000
    verbose: bool = True


def _log(config: QualityConfig, message: str) -> None:
    if config.verbose:
        print(f"[quality] {message}")


def _check_field_completeness(
    result: ProductWorkflowResult, config: QualityConfig
) -> List[QualityIssue]:
    issues: List[QualityIssue] = []

    missing_fields = []
    for field_name in config.required_fields:
        found = False

        for candidate in result.candidates:
            if field_name in candidate.extracted_params:
                found = True
                break

        if not found:
            for review in result.reviews:
                if field_name.lower() in (review.snippet.lower() + review.page_text.lower()):
                    found = True
                    break

        if not found:
            missing_fields.append(field_name)

    if missing_fields:
        issues.append(
            QualityIssue(
                type=IssueType.INCOMPLETE_INFO,
                severity=IssueSeverity.MAJOR,
                description=f"缺少必要的产品信息字段: {', '.join(missing_fields)}",
                suggestion=f"建议补充搜索关于{', '.join(missing_fields)}的信息",
                affected_fields=missing_fields,
            )
        )

    return issues


def _check_evidence_sufficiency(
    result: ProductWorkflowResult, config: QualityConfig
) -> List[QualityIssue]:
    issues: List[QualityIssue] = []

    total_evidence = len(result.candidates) + len(result.reviews)

    if total_evidence < config.min_evidence_count:
        issues.append(
            QualityIssue(
                type=IssueType.INSUFFICIENT_EVIDENCE,
                severity=IssueSeverity.MAJOR,
                description=f"证据数量不足，当前只有{total_evidence}条，至少需要{config.min_evidence_count}条",
                suggestion="建议扩大搜索范围获取更多证据",
                affected_fields=["evidence_count"],
            )
        )

    blocked_count = sum(1 for c in result.candidates if c.blocked_or_empty) + \
                    sum(1 for r in result.reviews if r.blocked_or_empty)

    if blocked_count > 0:
        issues.append(
            QualityIssue(
                type=IssueType.LOW_QUALITY_EVIDENCE,
                severity=IssueSeverity.MINOR,
                description=f"{blocked_count}条证据无法获取完整内容（可能被反爬拦截）",
                suggestion="建议尝试更换代理或调整搜索策略",
                affected_fields=["evidence_quality"],
            )
        )

    return issues


def _check_source_tracing(result: ProductWorkflowResult) -> List[QualityIssue]:
    issues: List[QualityIssue] = []

    evidence_without_url = []

    for idx, candidate in enumerate(result.candidates):
        if not candidate.url:
            evidence_without_url.append(f"产品候选#{idx+1}")

    for idx, review in enumerate(result.reviews):
        if not review.url:
            evidence_without_url.append(f"评论证据#{idx+1}")

    if evidence_without_url:
        issues.append(
            QualityIssue(
                type=IssueType.MISSING_SOURCE,
                severity=IssueSeverity.MINOR,
                description=f"部分证据缺少来源URL: {', '.join(evidence_without_url)}",
                suggestion="建议补充来源URL以支持溯源",
                affected_fields=["source_url"],
            )
        )

    return issues


def _check_conflicting_evidence(result: ProductWorkflowResult) -> List[QualityIssue]:
    issues: List[QualityIssue] = []

    prices = []
    for candidate in result.candidates:
        if "price" in candidate.extracted_params:
            price_str = candidate.extracted_params["price"].strip()
            try:
                price = float(price_str)
                prices.append((price, candidate.url))
            except ValueError:
                pass

    if len(prices) >= 2:
        min_price = min(p[0] for p in prices)
        max_price = max(p[0] for p in prices)
        if max_price > min_price * 1.5:
            issues.append(
                QualityIssue(
                    type=IssueType.CONFLICTING_EVIDENCE,
                    severity=IssueSeverity.MAJOR,
                    description=f"价格信息存在较大差异，最低{min_price}，最高{max_price}",
                    suggestion="建议进一步验证价格信息的准确性",
                    affected_fields=["price"],
                )
            )

    return issues


def _calculate_score(issues: List[QualityIssue]) -> float:
    """Calculate quality score based on issue severity."""
    score = 1.0

    for issue in issues:
        if issue.severity == IssueSeverity.CRITICAL:
            score -= 0.3
        elif issue.severity == IssueSeverity.MAJOR:
            score -= 0.15
        elif issue.severity == IssueSeverity.MINOR:
            score -= 0.05

    return max(0.0, min(1.0, score))


def _calculate_confidence(
    score: float,
    issues: List[QualityIssue],
    result: ProductWorkflowResult,
) -> tuple[ConfidenceLevel, bool, List[str]]:
    """Calculate confidence level based on score, issues, and evidence quality."""
    low_confidence_reasons: List[str] = []

    critical_count = sum(1 for i in issues if i.severity == IssueSeverity.CRITICAL)
    major_count = sum(1 for i in issues if i.severity == IssueSeverity.MAJOR)
    minor_count = sum(1 for i in issues if i.severity == IssueSeverity.MINOR)

    total_evidence = len(result.candidates) + len(result.reviews)
    blocked_count = sum(1 for c in result.candidates if c.blocked_or_empty) + \
                    sum(1 for r in result.reviews if r.blocked_or_empty)

    if score >= 0.85 and critical_count == 0 and major_count <= 1:
        confidence_level = ConfidenceLevel.HIGH
    elif score >= 0.6 and critical_count == 0:
        confidence_level = ConfidenceLevel.MEDIUM
    else:
        confidence_level = ConfidenceLevel.LOW

    if critical_count > 0:
        low_confidence_reasons.append(f"存在{critical_count}个严重问题")

    if major_count > 2:
        low_confidence_reasons.append(f"存在{major_count}个主要问题，较多")
        confidence_level = ConfidenceLevel.LOW if confidence_level == ConfidenceLevel.MEDIUM else confidence_level

    if blocked_count > total_evidence * 0.3 and total_evidence > 0:
        low_confidence_reasons.append(f"超过30%的证据被拦截({blocked_count}/{total_evidence})")
        if confidence_level == ConfidenceLevel.HIGH:
            confidence_level = ConfidenceLevel.MEDIUM

    if total_evidence < 3:
        low_confidence_reasons.append(f"证据总数不足({total_evidence}<3)")
        if confidence_level == ConfidenceLevel.HIGH:
            confidence_level = ConfidenceLevel.MEDIUM

    needs_human_review = (
        confidence_level == ConfidenceLevel.LOW or
        critical_count > 0 or
        score < config.min_score_threshold
    )

    return confidence_level, needs_human_review, low_confidence_reasons


def _generate_search_suggestions(
    result: ProductWorkflowResult, issues: List[QualityIssue]
) -> List[str]:
    """Generate search query suggestions based on identified issues."""
    suggestions = []
    missing_fields = set()

    for issue in issues:
        if issue.type == IssueType.INCOMPLETE_INFO:
            missing_fields.update(issue.affected_fields)
        elif issue.type == IssueType.INSUFFICIENT_EVIDENCE:
            suggestions.append(f"{result.product_name} 更多参数 评测")
        elif issue.type == IssueType.CONFLICTING_EVIDENCE:
            suggestions.append(f"{result.product_name} 官方价格 确认")

    for field_name in missing_fields:
        field_aliases = {
            "brand": "品牌",
            "model": "型号",
            "price": "价格",
            "spec": "规格",
            "capacity": "容量",
            "version": "版本",
        }
        field_display = field_aliases.get(field_name, field_name)
        suggestions.append(f"{result.product_name} {field_display} 参数")

    return suggestions[:5]


def inspect_quality(
    result: ProductWorkflowResult, config: QualityConfig
) -> QualityReport:
    """Perform quality inspection on the product analysis result."""
    _log(config, f"Starting quality inspection for: {result.product_name}")

    issues: List[QualityIssue] = []

    issues.extend(_check_field_completeness(result, config))
    issues.extend(_check_evidence_sufficiency(result, config))
    issues.extend(_check_source_tracing(result))
    issues.extend(_check_conflicting_evidence(result))

    score = _calculate_score(issues)
    passed = score >= config.min_score_threshold

    confidence_level, needs_human_review, low_confidence_reasons = _calculate_confidence(
        score, issues, result
    )

    suggestions = _generate_search_suggestions(result, issues)

    report = QualityReport(
        passed=passed,
        score=score,
        issues=issues,
        suggestions=suggestions,
        required_resources=[field for issue in issues for field in issue.affected_fields],
        confidence_level=confidence_level,
        needs_human_review=needs_human_review,
        low_confidence_reasons=low_confidence_reasons,
    )

    _log(config, f"Quality inspection completed. Score: {score:.2f}, Passed: {passed}")
    _log(config, f"Confidence level: {confidence_level.value}, Needs human review: {needs_human_review}")
    for issue in issues:
        _log(config, f"  - [{issue.severity}] {issue.description}")

    return report


def llm_enhanced_inspect(
    result: ProductWorkflowResult, config: QualityConfig
) -> QualityReport:
    """Use LLM to enhance quality inspection with deep analysis."""
    _log(config, "Starting LLM-enhanced quality inspection")

    prompt = f"""
你是一个产品分析报告质检专家。请仔细分析以下产品分析结果，检查其完整性、证据充分性和结论可信度。

产品名称: {result.product_name}

产品候选信息 ({len(result.candidates)}条):
{json.dumps([{
    'platform': c.platform,
    'title': c.title[:50],
    'url': c.url,
    'params': list(c.extracted_params.keys()),
    'blocked': c.blocked_or_empty
} for c in result.candidates], ensure_ascii=False, indent=2)}

评论/评测证据 ({len(result.reviews)}条):
{json.dumps([{
    'title': r.title[:50],
    'url': r.url,
    'blocked': r.blocked_or_empty
} for r in result.reviews], ensure_ascii=False, indent=2)}

总结内容摘要:
{result.summary[:1000]}

请按照以下标准进行评估:
1. 完整性: 是否包含品牌、型号、价格、规格等关键信息
2. 证据充分性: 是否有足够的证据支持结论
3. 溯源性: 是否每条结论都有可追溯的来源
4. 一致性: 不同来源之间是否存在矛盾
5. 置信度: 基于上述所有因素，评估报告的可信程度

请返回JSON格式的评估结果:
{{
  "score": 0.0-1.0,
  "passed": true/false,
  "confidence_level": "high|medium|low",
  "needs_human_review": true/false,
  "low_confidence_reasons": ["原因1", "原因2"],
  "issues": [
    {{
      "type": "incomplete_info|insufficient_evidence|missing_source|conflicting_evidence",
      "severity": "critical|major|minor",
      "description": "问题描述",
      "suggestion": "改进建议"
    }}
  ],
  "suggestions": ["搜索建议1", "搜索建议2"]
}}
"""

    try:
        content = chat_content(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个严格的质检专家，专注于评估产品分析报告的质量。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )

        if content:
            cleaned = content.replace("```json", "").replace("```", "").strip()
            llm_result = json.loads(cleaned)

            issues = []
            for issue_data in llm_result.get("issues", []):
                issues.append(QualityIssue(
                    type=IssueType(issue_data.get("type", "incomplete_info")),
                    severity=IssueSeverity(issue_data.get("severity", "minor")),
                    description=issue_data.get("description", ""),
                    suggestion=issue_data.get("suggestion", ""),
                ))

            confidence_str = llm_result.get("confidence_level", "medium")
            try:
                confidence_level = ConfidenceLevel(confidence_str)
            except ValueError:
                confidence_level = ConfidenceLevel.MEDIUM

            report = QualityReport(
                passed=llm_result.get("passed", False),
                score=llm_result.get("score", 0.0),
                issues=issues,
                suggestions=llm_result.get("suggestions", []),
                required_resources=[],
                confidence_level=confidence_level,
                needs_human_review=llm_result.get("needs_human_review", False),
                low_confidence_reasons=llm_result.get("low_confidence_reasons", []),
            )

            _log(config, f"LLM inspection completed. Score: {report.score:.2f}")
            _log(config, f"Confidence level: {report.confidence_level.value}, Needs human review: {report.needs_human_review}")
            return report
    except Exception as exc:
        _log(config, f"LLM inspection failed, falling back to rule-based: {exc}")

    return inspect_quality(result, config)

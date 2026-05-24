"""Core quality inspection agent logic."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Dict, List, Optional

from ..workflow.llm_client import chat_content
from .config import (
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

if TYPE_CHECKING:
    from ..analysis_agent.product_workflow import ProductWorkflowResult


# ========== 辅助函数 ==========

def _log(config: QualityConfig, message: str) -> None:
    if config.verbose:
        print(f"[quality] {message}")


# ========== 产品类型识别 ==========

def _detect_product_type_with_llm(
    result: ProductWorkflowResult, config: QualityConfig
) -> ProductType:
    """使用 LLM 智能判断产品类型."""
    try:
        product_evidence = []
        for candidate in result.candidates[:3]:
            product_evidence.append({
                "title": candidate.title,
                "params": list(candidate.extracted_params.keys()),
            })
        
        for review in result.reviews[:2]:
            product_evidence.append({"title": review.title})
        
        prompt = f"""请判断这个产品是硬件还是软件。

产品名称: {result.product_name}

证据摘要:
{json.dumps(product_evidence, ensure_ascii=False, indent=2)}

请回答:
1. 这是一个硬件产品还是软件产品?
2. 简要说明理由

请返回纯JSON格式:
{{
  "product_type": "hardware|software",
  "confidence": 0.0-1.0,
  "reasoning": "理由说明"
}}
"""
        
        content = chat_content(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
            messages=[
                {"role": "system", "content": "你是一个产品分类专家，只需要判断产品是硬件还是软件。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=500,
        )
        
        if content:
            cleaned = content.replace("```json", "").replace("```", "").strip()
            llm_result = json.loads(cleaned)
            
            type_str = llm_result.get("product_type", "hardware")
            confidence = llm_result.get("confidence", 0.0)
            
            _log(config, f"LLM identified type: {type_str}, confidence: {confidence}")
            if confidence >= 0.6:
                return ProductType.SOFTWARE if type_str == "software" else ProductType.HARDWARE
    
    except Exception as exc:
        _log(config, f"LLM product type detection failed, falling back: {exc}")
    
    return _detect_product_type_by_keywords(result)


def _detect_product_type_by_keywords(result: ProductWorkflowResult) -> ProductType:
    """基于关键词判断产品类型（降级方案）."""
    software_keywords = ["软件", "应用", "app", "website", "平台", "系统", "程序"]
    hardware_keywords = ["手机", "电脑", "设备", "机器", "产品", "硬件"]
    
    product_name_lower = result.product_name.lower()
    
    if any(k in product_name_lower for k in software_keywords):
        return ProductType.SOFTWARE
    if any(k in product_name_lower for k in hardware_keywords):
        return ProductType.HARDWARE
    
    return ProductType.HARDWARE


def _detect_product_type(
    result: ProductWorkflowResult, config: Optional[QualityConfig] = None
) -> ProductType:
    """自动检测产品类型（优先 LLM，降级关键词）."""
    if config:
        return _detect_product_type_with_llm(result, config)
    else:
        return _detect_product_type_by_keywords(result)


def _get_domain_config(config: QualityConfig, result: ProductWorkflowResult) -> DomainConfig:
    """获取领域配置."""
    if config.domain_config:
        return config.domain_config
    
    product_type = config.product_type
    if product_type == ProductType.AUTO_DETECT:
        product_type = _detect_product_type(result, config)
    
    return DomainConfig.software() if product_type == ProductType.SOFTWARE else DomainConfig.hardware()


# ========== 证据质量评估 ==========

def _evaluate_evidence_quality(
    candidate_or_review, domain_config: DomainConfig
) -> EvidenceQualityScore:
    """评估单个证据的质量（基于实际内容）."""
    reasons: List[str] = []
    url_trusted = False
    content_length_ok = False
    structured_fields = 0
    
    blocked = getattr(candidate_or_review, "blocked_or_empty", False)
    page_text = getattr(candidate_or_review, "page_text", "")
    content_length = len(page_text) if page_text else 0
    
    if blocked:
        score = 1.0
        reasons.append("证据被拦截，内容不可评估")
    else:
        score = 1.0
        if content_length > 1000:
            content_length_ok = True
            score += 0.15
            reasons.append(f"内容长度优秀: {content_length} 字符")
        elif content_length > 500:
            content_length_ok = True
            score += 0.1
            reasons.append(f"内容长度良好: {content_length} 字符")
        elif content_length > 200:
            score += 0.05
            reasons.append(f"内容长度一般: {content_length} 字符")
        
        extracted_params = getattr(candidate_or_review, "extracted_params", {})
        structured_fields = len(extracted_params)
        if structured_fields >= 5:
            score += 0.15
            reasons.append(f"结构化字段丰富: {structured_fields} 个")
        elif structured_fields >= 3:
            score += 0.1
            reasons.append(f"结构化字段适中: {structured_fields} 个")
        elif structured_fields >= 1:
            score += 0.05
            reasons.append(f"结构化字段较少: {structured_fields} 个")
    
    return EvidenceQualityScore(
        score=max(0.0, min(1.0, score)),
        url_trusted=url_trusted,
        content_length_ok=content_length_ok,
        structured_fields_ok=structured_fields >= 3,
        blocked=blocked,
        reasons=reasons
    )


def _calculate_aggregate_evidence_quality(
    result: ProductWorkflowResult, domain_config: DomainConfig
) -> float:
    """计算所有证据的平均质量分数."""
    all_quality_scores: List[float] = []
    
    for candidate in result.candidates:
        quality = _evaluate_evidence_quality(candidate, domain_config)
        all_quality_scores.append(quality.score)
    
    for review in result.reviews:
        quality = _evaluate_evidence_quality(review, domain_config)
        all_quality_scores.append(quality.score)
    
    return sum(all_quality_scores) / len(all_quality_scores) if all_quality_scores else 0.0


# ========== 规则检测 ==========

def _check_field_completeness(
    result: ProductWorkflowResult, config: QualityConfig, domain_config: DomainConfig
) -> List[QualityIssue]:
    """检查字段完整性."""
    issues: List[QualityIssue] = []
    required_fields = config.required_fields or domain_config.required_fields
    
    for candidate in result.candidates:
        missing_fields = [
            field for field in required_fields
            if field not in candidate.extracted_params
        ]
        
        if missing_fields:
            issues.append(QualityIssue(
                type=IssueType.INCOMPLETE_INFO,
                severity=IssueSeverity.MAJOR,
                description=f"产品 {candidate.title} 缺少字段: {', '.join(missing_fields)}",
                suggestion=f"补充搜索 {candidate.title} 的 {', '.join(missing_fields)} 信息",
                explanation=f"完整的产品信息需要包含所有必要字段",
                impact=f"缺少关键信息可能影响分析准确性",
                affected_fields=missing_fields
            ))
    
    return issues


def _check_evidence_sufficiency(
    result: ProductWorkflowResult, config: QualityConfig
) -> List[QualityIssue]:
    """检查证据充分性."""
    issues: List[QualityIssue] = []
    total_evidence = len(result.candidates) + len(result.reviews)
    
    if total_evidence < config.min_evidence_count:
        issues.append(QualityIssue(
            type=IssueType.INSUFFICIENT_EVIDENCE,
            severity=IssueSeverity.MAJOR,
            description=f"证据数量不足: 当前 {total_evidence} 条，需要至少 {config.min_evidence_count} 条",
            suggestion=f"增加搜索关键词或扩大搜索范围",
            explanation=f"足够的证据数量是结论可信度的基础",
            impact=f"证据不足可能导致分析结论片面"
        ))
    
    return issues


def _check_source_tracing(result: ProductWorkflowResult) -> List[QualityIssue]:
    """检查来源溯源性."""
    issues: List[QualityIssue] = []
    
    for candidate in result.candidates:
        if not getattr(candidate, "url", None):
            issues.append(QualityIssue(
                type=IssueType.MISSING_SOURCE,
                severity=IssueSeverity.MINOR,
                description=f"产品 {candidate.title} 缺少来源URL",
                suggestion=f"确保搜索结果包含完整的URL",
                explanation=f"来源URL是验证信息真实性的重要依据",
                impact=f"无法追踪信息来源可能影响可信度"
            ))
    
    return issues


def _check_conflicting_evidence(
    result: ProductWorkflowResult, domain_config: DomainConfig
) -> List[QualityIssue]:
    """检查冲突证据."""
    issues: List[QualityIssue] = []
    price_values: List[float] = []
    
    for candidate in result.candidates:
        price = candidate.extracted_params.get("price")
        if price and isinstance(price, (int, float)):
            price_values.append(price)
    
    if len(price_values) >= 2:
        max_price = max(price_values)
        min_price = min(price_values)
        if max_price > 0 and (max_price - min_price) / max_price > domain_config.conflict_threshold:
            issues.append(QualityIssue(
                type=IssueType.CONFLICTING_EVIDENCE,
                severity=IssueSeverity.MAJOR,
                description=f"价格存在显著差异: 最高 {max_price}, 最低 {min_price}",
                suggestion=f"进一步验证价格信息的准确性",
                explanation=f"价格差异超过 {domain_config.conflict_threshold * 100}% 可能存在信息冲突",
                impact=f"冲突的价格信息会影响定价分析的准确性"
            ))
    
    return issues


# ========== 评分与置信度计算 ==========

def _calculate_score(
    issues: List[QualityIssue], evidence_quality: float
) -> float:
    """计算质检分数."""
    score = 1.0
    
    for issue in issues:
        if issue.severity == IssueSeverity.CRITICAL:
            score -= 0.3 * issue.confidence
        elif issue.severity == IssueSeverity.MAJOR:
            score -= 0.15 * issue.confidence
        elif issue.severity == IssueSeverity.MINOR:
            score -= 0.05 * issue.confidence
    
    score += (evidence_quality - 1.0) * 0.3
    
    return max(0.0, min(1.0, score))


def _calculate_confidence(
    score: float,
    issues: List[QualityIssue],
    evidence_quality: float,
    total_evidence: int
) -> ConfidenceLevel:
    """计算置信度等级."""
    critical_issues = [i for i in issues if i.severity == IssueSeverity.CRITICAL]
    major_issues = [i for i in issues if i.severity == IssueSeverity.MAJOR]
    
    if score >= 0.85 and not critical_issues and len(major_issues) <= 1:
        if evidence_quality < 0.6 or total_evidence < 3:
            return ConfidenceLevel.MEDIUM
        return ConfidenceLevel.HIGH
    
    if score >= 0.6 and not critical_issues:
        if len(major_issues) > 2:
            return ConfidenceLevel.LOW
        return ConfidenceLevel.MEDIUM
    
    return ConfidenceLevel.LOW


# ========== 核心质检函数 ==========

def inspect_quality(
    result: ProductWorkflowResult, config: QualityConfig
) -> QualityReport:
    """执行规则引擎质检."""
    start_time = time.time()
    
    domain_config = _get_domain_config(config, result)
    evidence_quality = _calculate_aggregate_evidence_quality(result, domain_config)
    
    issues: List[QualityIssue] = []
    issues.extend(_check_field_completeness(result, config, domain_config))
    issues.extend(_check_evidence_sufficiency(result, config))
    issues.extend(_check_source_tracing(result))
    issues.extend(_check_conflicting_evidence(result, domain_config))
    
    score = _calculate_score(issues, evidence_quality)
    total_evidence = len(result.candidates) + len(result.reviews)
    confidence_level = _calculate_confidence(score, issues, evidence_quality, total_evidence)
    
    suggestions = [issue.suggestion for issue in issues]
    
    needs_human_review = (
        confidence_level == ConfidenceLevel.LOW or
        any(i.severity == IssueSeverity.CRITICAL for i in issues) or
        evidence_quality < 0.5
    )
    
    low_confidence_reasons: List[str] = []
    if confidence_level == ConfidenceLevel.LOW:
        if score < 0.6:
            low_confidence_reasons.append("质检分数低于阈值")
        if evidence_quality < 0.6:
            low_confidence_reasons.append("证据质量较低")
        if any(i.severity == IssueSeverity.CRITICAL for i in issues):
            low_confidence_reasons.append("存在严重问题")
    
    return QualityReport(
        passed=score >= config.min_score_threshold,
        score=score,
        issues=issues,
        suggestions=suggestions,
        required_resources=[],
        confidence_level=confidence_level,
        needs_human_review=needs_human_review,
        low_confidence_reasons=low_confidence_reasons,
        evidence_quality_avg=evidence_quality,
        domain_type=domain_config.product_type,
        inspection_time_sec=time.time() - start_time,
        inspection_rounds=1
    )


def llm_enhanced_inspect(
    result: ProductWorkflowResult, config: QualityConfig
) -> QualityReport:
    """执行 LLM 增强质检."""
    try:
        _log(config, "Starting LLM enhanced inspection")
        
        candidates_info = []
        for candidate in result.candidates:
            candidates_info.append({
                "title": candidate.title,
                "platform": getattr(candidate, "platform", ""),
                "params": candidate.extracted_params,
                "blocked": getattr(candidate, "blocked_or_empty", False),
            })
        
        reviews_info = []
        for review in result.reviews:
            reviews_info.append({
                "title": review.title,
                "blocked": getattr(review, "blocked_or_empty", False),
            })
        
        prompt = f"""你是一个质检专家，请分析以下产品分析结果的质量。

产品名称: {result.product_name}

候选产品信息:
{json.dumps(candidates_info, ensure_ascii=False, indent=2)}

用户评论信息:
{json.dumps(reviews_info, ensure_ascii=False, indent=2)}

请从以下维度进行分析:
1. 完整性: 是否包含所有必要信息
2. 一致性: 证据之间是否存在矛盾
3. 逻辑性: 分析结论是否合理

请返回JSON格式的质检报告:
{{
  "passed": true/false,
  "score": 0.0-1.0,
  "issues": [
    {{
      "type": "incomplete_info|insufficient_evidence|conflicting_evidence|logical_inconsistency|other",
      "severity": "critical|major|minor",
      "description": "问题描述",
      "suggestion": "改进建议",
      "explanation": "问题解释",
      "impact": "影响评估",
      "confidence": 0.0-1.0
    }}
  ],
  "confidence_level": "high|medium|low",
  "needs_human_review": true/false,
  "low_confidence_reasons": ["原因1", "原因2"]
}}
"""
        
        content = chat_content(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
            messages=[
                {"role": "system", "content": "你是一个专业的质检专家，负责评估产品分析报告的质量。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=2000,
        )
        
        if content:
            cleaned = content.replace("```json", "").replace("```", "").strip()
            llm_result = json.loads(cleaned)
            
            issues = []
            for issue_dict in llm_result.get("issues", []):
                issues.append(QualityIssue(
                    type=IssueType(issue_dict.get("type", "other")),
                    severity=IssueSeverity(issue_dict.get("severity", "minor")),
                    description=issue_dict.get("description", ""),
                    suggestion=issue_dict.get("suggestion", ""),
                    explanation=issue_dict.get("explanation", ""),
                    impact=issue_dict.get("impact", ""),
                    confidence=issue_dict.get("confidence", 1.0)
                ))
            
            domain_config = _get_domain_config(config, result)
            
            return QualityReport(
                passed=llm_result.get("passed", False),
                score=llm_result.get("score", 0.0),
                issues=issues,
                suggestions=[issue.suggestion for issue in issues],
                required_resources=[],
                confidence_level=ConfidenceLevel(llm_result.get("confidence_level", "medium")),
                needs_human_review=llm_result.get("needs_human_review", False),
                low_confidence_reasons=llm_result.get("low_confidence_reasons", []),
                evidence_quality_avg=_calculate_aggregate_evidence_quality(result, domain_config),
                domain_type=domain_config.product_type,
                inspection_time_sec=0.0,
                inspection_rounds=1
            )
    
    except Exception as exc:
        _log(config, f"LLM inspection failed, falling back to rule-based: {exc}")
    
    return inspect_quality(result, config)


# ========== 公开接口 ==========

def inspect(
    result: ProductWorkflowResult, config: QualityConfig
) -> QualityReport:
    """执行质检（多阶段）."""
    start_time = time.time()
    
    if config.enable_multistage_inspection:
        quick_result = inspect_quality(result, config)
        if quick_result.passed and quick_result.confidence_level == ConfidenceLevel.HIGH:
            _log(config, "Quick check passed, returning early")
            return quick_result
    
    report = llm_enhanced_inspect(result, config)
    report.inspection_time_sec = time.time() - start_time
    
    return report

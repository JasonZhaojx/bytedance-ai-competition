"""LLM-assisted inspection functions for report quality.

This module provides LLM-powered quality checks that complement
rule-based inspectors. It handles semantic-level analysis that
is difficult to implement with pure rules.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..adapters.report_adapter import ReportAnalysis
from ..config import IssueSeverity, IssueType, QualityIssue
from ..observability import ObservableLogger


@dataclass
class _OpenAICompatResponse:
    content: str


class _OpenAICompatChatClient:
    """Small adapter exposing the invoke() shape used by LLMInspector."""

    def __init__(
        self,
        api_key: Optional[str],
        base_url: Optional[str],
        model: Optional[str],
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def invoke(self, prompt: str) -> _OpenAICompatResponse:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        content = response.choices[0].message.content or ""
        return _OpenAICompatResponse(content=content)


class LLMInspector:
    """LLM辅助检查器，负责语义级别的质量检查"""
    
    def __init__(
        self,
        llm_api_key: Optional[str] = None,
        llm_base_url: Optional[str] = None,
        llm_model: Optional[str] = None,
        enabled: bool = True
    ):
        self.llm_api_key = llm_api_key
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model
        self.enabled = enabled
        self._client = None
    
    @property
    def client(self):
        """延迟初始化LLM客户端"""
        if self._client is None and self.enabled:
            self._client = self._create_client()
        return self._client
    
    def _create_client(self):
        """创建LLM客户端"""
        try:
            return _OpenAICompatChatClient(
                api_key=self.llm_api_key,
                base_url=self.llm_base_url,
                model=self.llm_model,
                temperature=0.1,
                max_tokens=2000,
            )
        except ImportError:
            pass

        try:
            from langchain_openai import ChatOpenAI
            
            return ChatOpenAI(
                api_key=self.llm_api_key,
                base_url=self.llm_base_url,
                model=self.llm_model,
                temperature=0.1,
                max_tokens=2000
            )
        except ImportError:
            self.enabled = False
            return None
    
    def check_semantic_consistency(self, analysis: ReportAnalysis) -> List[QualityIssue]:
        """使用LLM检查报告语义一致性"""
        issues: List[QualityIssue] = []
        if not self.enabled or not self.client:
            return issues
        
        try:
            prompt = self._build_semantic_consistency_prompt(analysis)
            response = self.client.invoke(prompt)
            issues = self._parse_llm_response(response, IssueType.LOGICAL_INCONSISTENCY)
        except Exception as e:
            # LLM调用失败，不抛出异常，返回空列表
            pass
        
        return issues
    
    def check_factual_accuracy(self, analysis: ReportAnalysis) -> List[QualityIssue]:
        """使用LLM检查事实准确性"""
        issues: List[QualityIssue] = []
        if not self.enabled or not self.client:
            return issues
        
        try:
            prompt = self._build_factual_accuracy_prompt(analysis)
            response = self.client.invoke(prompt)
            issues = self._parse_llm_response(response, IssueType.WEAK_EVIDENCE_SUPPORT)
        except Exception as e:
            pass
        
        return issues
    
    def check_analysis_depth(self, analysis: ReportAnalysis) -> List[QualityIssue]:
        """使用LLM评估分析深度"""
        issues: List[QualityIssue] = []
        if not self.enabled or not self.client:
            return issues
        
        try:
            prompt = self._build_analysis_depth_prompt(analysis)
            response = self.client.invoke(prompt)
            issues = self._parse_llm_response(response, IssueType.INCOMPLETE_INFO)
        except Exception as e:
            pass
        
        return issues
    
    def check_language_quality(self, analysis: ReportAnalysis) -> List[QualityIssue]:
        """使用LLM检查语言表达质量"""
        issues: List[QualityIssue] = []
        if not self.enabled or not self.client:
            return issues
        
        try:
            prompt = self._build_language_quality_prompt(analysis)
            response = self.client.invoke(prompt)
            issues = self._parse_llm_response(response, IssueType.LOW_QUALITY_EVIDENCE)
        except Exception as e:
            pass
        
        return issues

    def adjudicate_missing_sections(
        self,
        analysis: ReportAnalysis,
        missing_sections: List[str],
    ) -> Dict[str, Dict[str, object]]:
        """Use LLM to decide whether reported missing sections exist semantically."""
        if not missing_sections or not self.enabled or not self.client:
            return {}

        logger = ObservableLogger()
        trace = logger.start_trace(
            "llm_structure_adjudication",
            missing_sections=missing_sections,
            task_id=analysis.task_id,
        )
        try:
            prompt = self._build_structure_adjudication_prompt(analysis, missing_sections)
            logger.log_prompt(prompt, "llm_structure_adjudication")
            response = self.client.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            logger.log_response(content, "llm_structure_adjudication")
            result = self._parse_json_object(content)
            sections = result.get("sections", result)
            if not isinstance(sections, dict):
                logger.finish_trace(trace, success=False, error="LLM response missing sections object")
                return {}
            adjudication = {
                str(name): value
                for name, value in sections.items()
                if isinstance(value, dict)
            }
            trace.metadata["adjudication"] = adjudication
            logger.finish_trace(trace)
            return adjudication
        except Exception as exc:
            logger.finish_trace(trace, success=False, error=str(exc))
            return {}

    def adjudicate_quality_dimensions(self, analysis: ReportAnalysis) -> List[QualityIssue]:
        """Use LLM to adjudicate business-level semantic quality dimensions."""
        if not self.enabled or not self.client:
            return []

        logger = ObservableLogger()
        trace = logger.start_trace(
            "llm_quality_dimension_adjudication",
            task_id=analysis.task_id,
            dimensions=[
                "claim_evidence_support",
                "competitor_fairness",
                "swot_evidence_consistency",
                "recommendation_derivation",
            ],
        )
        try:
            prompt = self._build_quality_dimension_adjudication_prompt(analysis)
            logger.log_prompt(prompt, "llm_quality_dimension_adjudication")
            response = self.client.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            logger.log_response(content, "llm_quality_dimension_adjudication")

            issues = self._parse_quality_dimension_response(content)
            trace.metadata["issue_count"] = len(issues)
            logger.finish_trace(trace)
            return issues
        except Exception as exc:
            logger.finish_trace(trace, success=False, error=str(exc))
            return []

    def _extract_headings(self, markdown: str, limit: int = 80) -> str:
        headings = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("====="):
                headings.append(stripped)
            if len(headings) >= limit:
                break
        return "\n".join(headings)

    def _build_structure_adjudication_prompt(
        self,
        analysis: ReportAnalysis,
        missing_sections: List[str],
    ) -> str:
        headings = self._extract_headings(analysis.report_markdown)
        snippet = analysis.report_markdown[:2500]
        missing = ", ".join(missing_sections)

        return f"""
你是竞品分析报告质检裁判。规则检查认为报告缺少这些章节：{missing}

请只根据报告目录和正文片段判断这些章节是否以同义标题或等价内容存在。
常见等价关系：
- 执行摘要 等价于 核心结论、FINAL COMPARISON SUMMARY
- 竞品分析 等价于 单产品深度拆解、重点竞品拆解、竞品分类与选择理由
- 策略建议 等价于 选型建议、产品策略建议、落地建议
- 结论 等价于 核心结论、最终建议、选型建议中的总结性结论
- SWOT分析 必须明确包含 SWOT 或优势/劣势/机会/威胁四类分析，不要把普通优缺点列表误判为 SWOT

报告目录：
{headings}

正文片段：
{snippet}

只返回 JSON 对象，不要输出解释。格式：
{{
  "sections": {{
    "竞品分析": {{"present": true, "matched_heading": "一、单产品深度拆解", "reason": "该章节逐个拆解竞品"}},
    "SWOT分析": {{"present": false, "matched_heading": null, "reason": "未发现SWOT四象限"}}
  }}
}}
"""

    def _build_quality_dimension_adjudication_prompt(self, analysis: ReportAnalysis) -> str:
        claims = self._compact_claims(analysis.claims[:8])
        evidence = self._compact_evidence(analysis.evidence_list[:8])
        swot = self._compact_json(analysis.swot)
        recommendations = self._compact_json(analysis.recommendations[:8])
        comparison_tables = self._compact_json(analysis.comparison_tables[:4])
        competitors = ", ".join(analysis.competitors[:8]) or "None detected"
        snippet = analysis.report_markdown[:3000]

        return f"""
你是竞品分析报告的质量裁判。请只基于下面给出的报告内容和结构化数据，复核四个业务质量维度：

1. claim_evidence_support: 证据是否真的支持报告里的 claim，不要只看是否有 evidence_id。
2. competitor_fairness: 竞品对比是否公平，是否存在只强调某一方优点/缺点、比较维度不一致、遗漏关键竞品事实。
3. swot_evidence_consistency: SWOT 是否能从证据、竞品对比和正文分析推出，是否存在凭空 SWOT。
4. recommendation_derivation: 建议是否由证据、竞品分析和 SWOT 自然推出，是否存在跳跃建议。

只有当问题会影响业务判断时才输出 issue。轻微表述问题不要输出。

Claims:
{claims}

Evidence:
{evidence}

Competitors:
{competitors}

Comparison tables:
{comparison_tables}

SWOT:
{swot}

Recommendations:
{recommendations}

Report snippet:
{snippet}

只返回 JSON，不要解释。格式：
{{
  "issues": [
    {{
      "dimension": "claim_evidence_support",
      "issue_type": "weak_evidence_support",
      "severity": "MAJOR",
      "description": "具体问题",
      "suggestion": "可执行修改建议",
      "evidence_ids": ["ev_001"],
      "confidence": 0.82
    }}
  ]
}}
如果没有问题，返回 {{"issues": []}}。
"""

    def _compact_claims(self, claims: List[Dict[str, Any]]) -> str:
        if not claims:
            return "[]"
        compact = []
        for claim in claims:
            compact.append({
                "claim": claim.get("claim", ""),
                "evidence_ids": claim.get("evidence_ids", []),
            })
        return self._compact_json(compact)

    def _compact_evidence(self, evidence_list) -> str:
        if not evidence_list:
            return "[]"
        compact = []
        for evidence in evidence_list:
            compact.append({
                "id": evidence.source_id,
                "title": evidence.title,
                "snippet": (evidence.snippet or evidence.page_text or evidence.claim)[:300],
                "confidence": evidence.confidence,
                "source_type": evidence.source_type,
            })
        return self._compact_json(compact)

    def _compact_json(self, value: Any, limit: int = 3500) -> str:
        text = json.dumps(value, ensure_ascii=False, default=str, indent=2)
        if len(text) > limit:
            return text[:limit] + "\n...[truncated]"
        return text

    def _parse_quality_dimension_response(self, content: str) -> List[QualityIssue]:
        parsed = self._parse_json_value(content)
        if isinstance(parsed, dict):
            raw_issues = parsed.get("issues", [])
        elif isinstance(parsed, list):
            raw_issues = parsed
        else:
            return []

        if not isinstance(raw_issues, list):
            return []

        dimension_defaults = {
            "claim_evidence_support": IssueType.WEAK_EVIDENCE_SUPPORT,
            "competitor_fairness": IssueType.LOGICAL_INCONSISTENCY,
            "swot_evidence_consistency": IssueType.LOGICAL_INCONSISTENCY,
            "recommendation_derivation": IssueType.LOGICAL_INCONSISTENCY,
        }
        issues: List[QualityIssue] = []
        for item in raw_issues:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description", "")).strip()
            if not description:
                continue

            dimension = str(item.get("dimension", "")).strip()
            issue_type_raw = str(item.get("issue_type", "")).strip().lower()
            try:
                issue_type = IssueType(issue_type_raw)
            except ValueError:
                issue_type = dimension_defaults.get(dimension, IssueType.LOGICAL_INCONSISTENCY)

            severity_raw = str(item.get("severity", "MINOR")).strip().upper()
            severity = IssueSeverity.MAJOR if severity_raw == "MAJOR" else IssueSeverity.MINOR
            if severity_raw == "CRITICAL":
                severity = IssueSeverity.CRITICAL

            evidence_ids = item.get("evidence_ids", [])
            affected_fields = [dimension] if dimension else []
            if isinstance(evidence_ids, list):
                affected_fields.extend(str(eid) for eid in evidence_ids if eid)

            confidence = item.get("confidence", 0.75)
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = 0.75

            issues.append(QualityIssue(
                type=issue_type,
                severity=severity,
                description=description,
                suggestion=str(item.get("suggestion", "")).strip(),
                explanation="LLM semantic adjudicator found a business-quality issue.",
                impact="May cause unsupported conclusions, unfair comparison, or weak strategy decisions.",
                confidence=max(0.0, min(1.0, confidence)),
                affected_fields=affected_fields,
            ))

        return issues

    def _parse_json_object(self, content: str) -> dict:
        parsed = self._parse_json_value(content)
        if not isinstance(parsed, dict):
            raise ValueError("Expected JSON object")
        return parsed

    def _parse_json_value(self, content: str):
        content = content.strip()
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
        if fence_match:
            content = fence_match.group(1).strip()

        try:
            return json.loads(content)
        except Exception:
            object_match = re.search(r"\{[\s\S]*\}", content)
            if object_match:
                return json.loads(object_match.group(0))
            list_match = re.search(r"\[[\s\S]*\]", content)
            if list_match:
                return json.loads(list_match.group(0))
            raise
    
    def _build_semantic_consistency_prompt(self, analysis: ReportAnalysis) -> str:
        """构建语义一致性检查prompt"""
        swot_text = "\n".join([
            f"{cat}: {', '.join([str(item) for item in analysis.swot.get(cat, [])[:3]])}"
            for cat in ['strengths', 'weaknesses', 'opportunities', 'threats']
        ])
        
        recommendations_text = "\n".join([
            f"{i+1}. {rec.get('action', '')}"
            for i, rec in enumerate(analysis.recommendations[:5])
        ])
        
        return f"""
你是一个专业的报告质量检查专家。请分析以下竞品分析报告的语义一致性：

**SWOT分析内容：**
{swot_text}

**策略建议内容：**
{recommendations_text}

请检查：
1. 策略建议是否基于SWOT分析结果
2. 是否存在逻辑矛盾或不一致
3. 建议是否合理且有针对性

请以JSON格式输出问题列表，每个问题包含：
- description: 问题描述
- severity: 严重程度（MAJOR/MINOR）
- suggestion: 改进建议

如果没有问题，请返回空数组[]。
"""
    
    def _build_factual_accuracy_prompt(self, analysis: ReportAnalysis) -> str:
        """构建事实准确性检查prompt"""
        claims_text = "\n".join([
            f"声明{i+1}: {claim.get('claim', '')} (证据ID: {claim.get('evidence_ids', [])})"
            for i, claim in enumerate(analysis.claims[:10])
        ])
        
        evidence_text = "\n".join([
            f"证据{e.source_id}: {e.title} - {e.snippet[:100]}..."
            for e in analysis.evidence_list[:5]
        ])
        
        return f"""
你是一个专业的事实核查专家。请分析以下声明与证据的匹配度：

**声明列表：**
{claims_text}

**证据列表：**
{evidence_text}

请检查：
1. 声明是否有足够的证据支持
2. 证据内容是否能支撑声明
3. 是否存在虚假或误导性的声明

请以JSON格式输出问题列表，每个问题包含：
- description: 问题描述
- severity: 严重程度（MAJOR/MINOR）
- suggestion: 改进建议

如果没有问题，请返回空数组[]。
"""
    
    def _build_analysis_depth_prompt(self, analysis: ReportAnalysis) -> str:
        """构建分析深度评估prompt"""
        report_snippet = analysis.report_markdown[:3000]
        
        return f"""
你是一个资深的竞品分析专家。请评估以下报告的分析深度：

**报告内容（前3000字符）：**
{report_snippet}

请评估：
1. 分析是否深入透彻
2. 是否有独到的见解和洞察
3. 分析维度是否全面
4. 是否提供了有价值的洞察

请以JSON格式输出问题列表，每个问题包含：
- description: 问题描述
- severity: 严重程度（MAJOR/MINOR）
- suggestion: 改进建议

如果没有问题，请返回空数组[]。
"""
    
    def _build_language_quality_prompt(self, analysis: ReportAnalysis) -> str:
        """构建语言质量检查prompt"""
        report_snippet = analysis.report_markdown[:3000]
        
        return f"""
你是一个专业的编辑和语言专家。请检查以下报告的语言表达质量：

**报告内容（前3000字符）：**
{report_snippet}

请检查：
1. 语法和拼写错误
2. 语句通顺度和可读性
3. 专业术语使用是否恰当
4. 整体语言风格是否专业

请以JSON格式输出问题列表，每个问题包含：
- description: 问题描述
- severity: 严重程度（MAJOR/MINOR）
- suggestion: 改进建议

如果没有问题，请返回空数组[]。
"""
    
    def _parse_llm_response(self, response, issue_type: IssueType) -> List[QualityIssue]:
        """解析LLM响应为QualityIssue列表"""
        issues: List[QualityIssue] = []
        
        try:
            content = response.content if hasattr(response, 'content') else str(response)
            
            # 尝试解析JSON
            result = json.loads(content)
            
            if isinstance(result, list):
                for item in result:
                    if isinstance(item, dict):
                        severity = IssueSeverity.MAJOR if item.get('severity') == 'MAJOR' else IssueSeverity.MINOR
                        issues.append(QualityIssue(
                            type=issue_type,
                            severity=severity,
                            description=item.get('description', ''),
                            suggestion=item.get('suggestion', ''),
                            explanation="LLM检测发现的问题",
                            impact="语义层面的质量问题"
                        ))
        except Exception:
            # JSON解析失败，忽略
            pass
        
        return issues

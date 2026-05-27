"""LLM-assisted inspection functions for report quality.

This module provides LLM-powered quality checks that complement
rule-based inspectors. It handles semantic-level analysis that
is difficult to implement with pure rules.
"""

from typing import List, Optional

from ..adapters.report_adapter import ReportAnalysis
from ..config import IssueSeverity, IssueType, QualityIssue


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
            import json
            
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

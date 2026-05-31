"""Hybrid inspection combining LLM and rule-based approaches.

This module implements a hybrid quality inspection system that:
1. Uses LLM as the primary detector (default)
2. Falls back to rule-based detection when LLM fails
3. Supports hybrid voting mechanism for conflicting results
4. Configurable via QualityConfig hyperparameters
"""

import re
from typing import Dict, List, Optional

from ..adapters.report_adapter import ReportAnalysis
from ..config import InspectionMode, IssueSeverity, IssueType, QualityConfig, QualityIssue
from .base_inspector import check_claim_evidence_linkage, check_evidence_quality
from .competitor_inspector import check_competitor_coverage
from .evidence_inspector import check_evidence_diversity, check_evidence_timeliness
from .llm_inspector import LLMInspector
from .logic_inspector import check_logical_consistency
from .recommendation_inspector import check_recommendation_feasibility
from .structure_inspector import check_report_structure


class HybridInspector:
    """混合检查器，整合LLM和规则检查"""
    
    def __init__(
        self,
        mode: InspectionMode = InspectionMode.HYBRID_VOTING,
        llm_api_key: Optional[str] = None,
        llm_base_url: Optional[str] = None,
        llm_model: Optional[str] = None,
        llm_enabled: bool = True,
        voting_threshold: float = 0.6,      # 投票通过阈值
        voting_llm_weight: float = 0.5,     # LLM在投票中的权重
        fallback_on_llm_failure: bool = True  # LLM失败时是否兜底
    ):
        self.mode = mode
        self.voting_threshold = voting_threshold
        self.voting_llm_weight = voting_llm_weight
        self.fallback_on_llm_failure = fallback_on_llm_failure
        
        # 初始化LLM检查器
        self.llm_inspector = LLMInspector(
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            enabled=llm_enabled
        )
    
    @classmethod
    def from_config(cls, config: QualityConfig) -> "HybridInspector":
        """从QualityConfig创建混合检查器"""
        return cls(
            mode=config.inspection_mode,
            llm_api_key=config.llm_api_key,
            llm_base_url=config.llm_base_url,
            llm_model=config.llm_model,
            llm_enabled=config.llm_enabled,
            voting_threshold=config.voting_threshold,
            voting_llm_weight=config.voting_llm_weight,
            fallback_on_llm_failure=True
        )
    
    def inspect(self, analysis: ReportAnalysis) -> List[QualityIssue]:
        """执行混合检查"""
        if self.mode == InspectionMode.LLM_ONLY:
            return self._llm_only_inspect(analysis)
        elif self.mode == InspectionMode.RULE_ONLY:
            return self._rule_only_inspect(analysis)
        elif self.mode == InspectionMode.HYBRID_VOTING:
            return self._hybrid_voting_inspect(analysis)
        elif self.mode == InspectionMode.LLM_FALLBACK:
            return self._llm_fallback_inspect(analysis)
        else:
            return self._rule_only_inspect(analysis)
    
    def _llm_only_inspect(self, analysis: ReportAnalysis) -> List[QualityIssue]:
        """仅使用LLM检测"""
        issues: List[QualityIssue] = []
        
        # 收集所有LLM检查结果
        issues.extend(self.llm_inspector.check_semantic_consistency(analysis))
        issues.extend(self.llm_inspector.check_factual_accuracy(analysis))
        issues.extend(self.llm_inspector.check_analysis_depth(analysis))
        issues.extend(self.llm_inspector.check_language_quality(analysis))
        
        return issues
    
    def _rule_only_inspect(self, analysis: ReportAnalysis) -> List[QualityIssue]:
        """仅使用规则检测（兜底模式）"""
        issues: List[QualityIssue] = []
        
        # 执行所有规则检查
        issues.extend(check_claim_evidence_linkage(analysis))
        issues.extend(check_evidence_quality(analysis))
        issues.extend(check_report_structure(analysis))
        issues.extend(check_evidence_diversity(analysis))
        issues.extend(check_evidence_timeliness(analysis))
        issues.extend(check_competitor_coverage(analysis))
        issues.extend(check_logical_consistency(analysis))
        issues.extend(check_recommendation_feasibility(analysis))
        
        return issues
    
    def _hybrid_voting_inspect(self, analysis: ReportAnalysis) -> List[QualityIssue]:
        """混合投票模式：LLM和规则都检测，通过投票决定最终结果"""
        if not self.llm_inspector.enabled:
            return self._rule_only_inspect(analysis)

        # 先运行规则检查，再用LLM裁判复核规则报告的可疑结构缺项。
        rule_issues = self._rule_only_inspect(analysis)
        rule_issues = self._adjudicate_structure_issues(analysis, rule_issues)
        semantic_issues = self.llm_inspector.adjudicate_quality_dimensions(analysis)

        # 获取LLM检查结果
        llm_issues = self._llm_only_inspect(analysis)
        llm_issues = self._merge_issues(llm_issues, semantic_issues)

        # 执行投票融合，同时保留LLM未明确否决的规则问题。
        final_issues = self._vote_on_issues(llm_issues, rule_issues)
        final_issues = self._merge_issues(final_issues, rule_issues)
        final_issues = self._merge_issues(final_issues, semantic_issues)

        return final_issues

    def _adjudicate_structure_issues(
        self,
        analysis: ReportAnalysis,
        rule_issues: List[QualityIssue],
    ) -> List[QualityIssue]:
        corrected_issues: List[QualityIssue] = []

        for issue in rule_issues:
            missing_sections = self._extract_missing_sections(issue)
            if not missing_sections:
                corrected_issues.append(issue)
                continue

            adjudication = self.llm_inspector.adjudicate_missing_sections(
                analysis,
                missing_sections,
            )
            if not adjudication:
                corrected_issues.append(issue)
                continue

            remaining_sections = [
                section for section in missing_sections
                if not self._section_confirmed_present(adjudication, section)
            ]
            if not remaining_sections:
                continue

            issue.description = f"报告缺少必要章节: {', '.join(remaining_sections)}"
            issue.suggestion = f"补充缺失的章节内容: {', '.join(remaining_sections)}"
            issue.explanation = (
                issue.explanation
                + "；LLM结构裁判已复核并移除语义等价章节的误报"
            )
            corrected_issues.append(issue)

        return corrected_issues

    def _extract_missing_sections(self, issue: QualityIssue) -> List[str]:
        if issue.type != IssueType.INCOMPLETE_INFO:
            return []
        if "缺少必要章节" not in issue.description:
            return []

        match = re.search(r"[:：]\s*(.+)$", issue.description)
        if not match:
            return []
        return [
            section.strip()
            for section in re.split(r"[,，、]", match.group(1))
            if section.strip()
        ]

    def _section_confirmed_present(
        self,
        adjudication: Dict[str, Dict[str, object]],
        section: str,
    ) -> bool:
        result = adjudication.get(section)
        if not result:
            return False
        return bool(result.get("present"))
    
    def _llm_fallback_inspect(self, analysis: ReportAnalysis) -> List[QualityIssue]:
        """LLM为主，规则兜底模式"""
        try:
            # 优先使用LLM检测
            llm_issues = self._llm_only_inspect(analysis)
            
            # 如果LLM返回了结果，返回LLM结果
            if llm_issues:
                return llm_issues
            
            # 如果LLM没有发现问题，也运行规则检查作为补充
            rule_issues = self._rule_only_inspect(analysis)
            
            # 合并结果（去重）
            return self._merge_issues(llm_issues, rule_issues)
            
        except Exception:
            # LLM调用失败，使用规则兜底
            if self.fallback_on_llm_failure:
                return self._rule_only_inspect(analysis)
            raise
    
    def _vote_on_issues(self, llm_issues: List[QualityIssue], rule_issues: List[QualityIssue]) -> List[QualityIssue]:
        """投票机制：合并LLM和规则检查结果（支持权重配置）"""
        # 创建问题描述到问题对象的映射
        llm_issue_map = {issue.description: issue for issue in llm_issues}
        rule_issue_map = {issue.description: issue for issue in rule_issues}
        
        all_descriptions = set(llm_issue_map.keys()) | set(rule_issue_map.keys())
        final_issues: List[QualityIssue] = []
        
        # 权重配置
        llm_weight = self.voting_llm_weight
        rule_weight = 1.0 - llm_weight
        
        for description in all_descriptions:
            llm_vote = 1.0 if description in llm_issue_map else 0.0
            rule_vote = 1.0 if description in rule_issue_map else 0.0
            
            # 计算加权投票分数
            weighted_score = (llm_vote * llm_weight) + (rule_vote * rule_weight)
            
            # 判断是否通过
            if weighted_score >= self.voting_threshold:
                # 选择更严重的问题
                if llm_vote and rule_vote:
                    llm_issue = llm_issue_map[description]
                    rule_issue = rule_issue_map[description]
                    # 选择严重程度更高的
                    if llm_issue.severity.value >= rule_issue.severity.value:
                        final_issues.append(llm_issue)
                    else:
                        final_issues.append(rule_issue)
                elif llm_vote:
                    issue = llm_issue_map[description]
                    # 标记置信度为加权分数
                    issue.confidence = weighted_score
                    final_issues.append(issue)
                elif rule_vote:
                    issue = rule_issue_map[description]
                    # 标记置信度为加权分数
                    issue.confidence = weighted_score
                    final_issues.append(issue)
        
        return final_issues
    
    def _merge_issues(self, llm_issues: List[QualityIssue], rule_issues: List[QualityIssue]) -> List[QualityIssue]:
        """合并两个问题列表（去重）"""
        seen_descriptions = set()
        merged = []
        
        for issue in llm_issues + rule_issues:
            if issue.description not in seen_descriptions:
                seen_descriptions.add(issue.description)
                merged.append(issue)
        
        return merged

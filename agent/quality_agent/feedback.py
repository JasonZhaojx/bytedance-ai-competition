"""Quality feedback recorder for continuous learning."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .config import IssueSeverity, IssueType, QualityConfig, QualityIssue, QualityReport


AGENT_TARGETS: Dict[IssueType, str] = {
    IssueType.MISSING_SOURCE: "collector_agent",
    IssueType.INSUFFICIENT_EVIDENCE: "collector_agent",
    IssueType.LOW_QUALITY_EVIDENCE: "collector_agent",
    IssueType.OUTDATED_EVIDENCE: "collector_agent",
    IssueType.CONFLICTING_EVIDENCE: "analyst_agent",
    IssueType.LOGICAL_INCONSISTENCY: "analyst_agent",
    IssueType.INCOMPLETE_INFO: "writer_agent",
    IssueType.WEAK_EVIDENCE_SUPPORT: "writer_agent",
}


@dataclass
class AgentFeedbackMessage:
    """Structured feedback message for upstream agent retry loops."""

    target_agent: str
    action: str
    priority: str
    issue_type: str
    description: str
    suggested_fix: str
    affected_fields: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "target_agent": self.target_agent,
            "action": self.action,
            "priority": self.priority,
            "issue_type": self.issue_type,
            "description": self.description,
            "suggested_fix": self.suggested_fix,
            "affected_fields": self.affected_fields,
        }


def _priority_from_severity(severity: IssueSeverity) -> str:
    if severity == IssueSeverity.CRITICAL:
        return "high"
    if severity == IssueSeverity.MAJOR:
        return "medium"
    return "low"


def build_agent_feedback_messages(report: QualityReport) -> List[AgentFeedbackMessage]:
    """Convert quality issues into retry messages for collector/analyst/writer agents."""
    messages: List[AgentFeedbackMessage] = []
    for issue in report.issues:
        target_agent = AGENT_TARGETS.get(issue.type, "writer_agent")
        messages.append(AgentFeedbackMessage(
            target_agent=target_agent,
            action="revise_report" if target_agent == "writer_agent" else "补充或重做上游产物",
            priority=_priority_from_severity(issue.severity),
            issue_type=issue.type.value,
            description=issue.description,
            suggested_fix=issue.suggestion,
            affected_fields=issue.affected_fields,
        ))
    return messages


def build_feedback_payload(report: QualityReport, task_id: str = "") -> Dict[str, object]:
    """Create a structured feedback-loop payload consumable by workflow/DAG code."""
    messages = build_agent_feedback_messages(report)
    grouped: Dict[str, List[Dict[str, object]]] = {}
    for message in messages:
        grouped.setdefault(message.target_agent, []).append(message.to_dict())

    return {
        "task_id": task_id,
        "passed": report.passed,
        "score": report.score,
        "confidence_level": report.confidence_level.value,
        "needs_human_review": report.needs_human_review,
        "retry_required": not report.passed or bool(report.issues),
        "feedback_messages": [message.to_dict() for message in messages],
        "grouped_by_agent": grouped,
    }


@dataclass
# 质检反馈记录
class QualityFeedback:
    """质检反馈记录."""
    # 质检报告
    report: QualityReport
    # 产品名称
    product_name: str
    # 人工审批结果
    human_approved: bool
    # 人工审批评论
    human_comment: str = ""
    # 时间戳
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class QualityFeedbackRecorder:
    """质检反馈记录器，用于持续学习."""
    # 日志目录
    def __init__(self, log_dir: Optional[str] = None):
        """初始化反馈记录器."""
        if log_dir:
            self.log_dir = Path(log_dir)
        else:
            self.log_dir = Path("./quality_feedback")
        
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    # 记录人工复核反馈
    def record_feedback(
        self,
        report: QualityReport,
        product_name: str,
        human_approved: bool,
        human_comment: str = ""
    ) -> str:
        """记录人工复核反馈."""
        feedback = QualityFeedback(
            # 质检报告
            report=report,
            # 产品名称
            product_name=product_name,
            # 人工审批结果
            human_approved=human_approved,
            # 人工审批评论
            human_comment=human_comment
        )
        
        # 转换为可序列化的字典
        feedback_dict = {
            "product_name": feedback.product_name,
            "human_approved": feedback.human_approved,
            "human_comment": feedback.human_comment,
            "timestamp": feedback.timestamp,
            "agent_feedback": build_feedback_payload(report, product_name),
            "report": {
                "passed": report.passed,
                "score": report.score,
                "confidence_level": report.confidence_level.value,
                "needs_human_review": report.needs_human_review,
                "evidence_quality_avg": report.evidence_quality_avg,
                "domain_type": report.domain_type.value,
                "inspection_rounds": report.inspection_rounds,
                "issue_count": len(report.issues),
                "issues": [
                    {
                        "type": issue.type.value,
                        "severity": issue.severity.value,
                        "description": issue.description,
                        "confidence": issue.confidence
                    }
                    for issue in report.issues
                ],
                "suggestions": report.suggestions,
                "low_confidence_reasons": report.low_confidence_reasons
            }
        }
        
        # 生成文件名
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"feedback_{timestamp_str}.json"
        file_path = self.log_dir / filename
        
        # 保存反馈
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(feedback_dict, f, ensure_ascii=False, indent=2)
        
        return str(file_path)
    
    def load_feedback(self, file_path: str) -> dict:
        """加载反馈记录."""
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def list_feedbacks(self) -> list[str]:
        """列出所有反馈记录文件."""
        return sorted([str(f) for f in self.log_dir.glob("feedback_*.json")])

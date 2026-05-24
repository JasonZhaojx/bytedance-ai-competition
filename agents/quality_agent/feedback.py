"""Quality feedback recorder for continuous learning."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import QualityConfig, QualityReport


@dataclass
class QualityFeedback:
    """质检反馈记录."""
    report: QualityReport
    product_name: str
    human_approved: bool
    human_comment: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class QualityFeedbackRecorder:
    """质检反馈记录器，用于持续学习."""
    
    def __init__(self, log_dir: Optional[str] = None):
        """初始化反馈记录器."""
        if log_dir:
            self.log_dir = Path(log_dir)
        else:
            self.log_dir = Path("./quality_feedback")
        
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def record_feedback(
        self,
        report: QualityReport,
        product_name: str,
        human_approved: bool,
        human_comment: str = ""
    ) -> str:
        """记录人工复核反馈."""
        feedback = QualityFeedback(
            report=report,
            product_name=product_name,
            human_approved=human_approved,
            human_comment=human_comment
        )
        
        # 转换为可序列化的字典
        feedback_dict = {
            "product_name": feedback.product_name,
            "human_approved": feedback.human_approved,
            "human_comment": feedback.human_comment,
            "timestamp": feedback.timestamp,
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

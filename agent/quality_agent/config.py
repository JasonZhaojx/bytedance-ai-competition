"""Quality inspection configuration and data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ========== 枚举类型 ==========

class IssueSeverity(str, Enum):
    """问题严重程度."""
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class IssueType(str, Enum):
    """问题类型."""
    INCOMPLETE_INFO = "incomplete_info"          # 缺失信息
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # 缺失证据
    MISSING_SOURCE = "missing_source"            # 缺失来源
    CONFLICTING_EVIDENCE = "conflicting_evidence"    # 冲突证据
    LOW_QUALITY_EVIDENCE = "low_quality_evidence"    # 低质量证据
    LOGICAL_INCONSISTENCY = "logical_inconsistency"  # 逻辑不一致
    WEAK_EVIDENCE_SUPPORT = "weak_evidence_support"  # 证据支持不足


class ConfidenceLevel(str, Enum):
    """置信度等级."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ProductType(str, Enum):
    """产品类型."""
    HARDWARE = "hardware"
    SOFTWARE = "software"
    AUTO_DETECT = "auto"
    AI_TOOLS = "ai_tools"  # AI编程工具等软件产品


# AI编程工具专用配置
AI_TOOLS_KEYWORDS = [
    "编程", "代码", "开发", "IDE", "copilot", "coding",
    "智能", "AI", "大模型", "模型", "api", "插件", "tool"
]

NAVIGATION_KEYWORDS = [
    "登录", "注册", "首页", "社区", "直播", "专栏", "文章",
    "视频", "问答", "论坛", "帮助", "关于", "联系",
    "copyright", "隐私", "协议", "条款", "404", "error",
    "question-list", "login", "register", "home"
]


def is_navigation_url(url: str, title: str = "") -> bool:
    """判断是否为导航/无关链接."""
    if not isinstance(url, str):
        url = str(url) if url else ""
    if not isinstance(title, str):
        title = str(title) if title else ""

    url_lower = url.lower()
    title_lower = title.lower()

    for keyword in NAVIGATION_KEYWORDS:
        if keyword in url_lower or keyword in title_lower:
            return True

    if "/login" in url_lower or "/register" in url_lower:
        return True
    if url_lower.endswith("/pages/") or "/pages/" in url_lower and ".json" in url_lower:
        return True

    return False


# ========== 数据结构 ==========

@dataclass
class EvidenceQualityScore:
    """单个证据的质量评估."""
    score: float              # 证据质量分数
    url_trusted: bool         # 是否信任URL
    content_length_ok: bool   # 内容长度是否符合要求
    structured_fields_ok: bool # 结构化字段数量是否符合要求
    blocked: bool             # 是否被阻塞
    reasons: List[str] = field(default_factory=list)  # 评分原因


@dataclass
class QualityIssue:
    """增强的质量问题，包含可解释性信息."""
    type: IssueType              # 问题类型
    severity: IssueSeverity      # 问题严重程度
    description: str             # 问题描述
    suggestion: str              # 建议
    explanation: str = ""        # 解释
    impact: str = ""             # 影响
    confidence: float = 1.0      # 置信度
    affected_fields: List[str] = field(default_factory=list)  # 受影响的字段


@dataclass
class QualityReport:
    """增强的质量报告."""
    passed: bool                 # 是否通过质检
    score: float                 # 质检分数
    issues: List[QualityIssue]   # 质检问题列表
    suggestions: List[str]       # 建议列表
    required_resources: List[str] # 所需资源列表
    
    # 增强字段
    confidence_level: ConfidenceLevel = ConfidenceLevel.HIGH
    # 是否需要人工审核
    needs_human_review: bool = False
    # 低置信度原因列表
    low_confidence_reasons: List[str] = field(default_factory=list)
    # 证据质量平均值
    evidence_quality_avg: float = 1.0
    # 领域类型
    domain_type: ProductType = ProductType.HARDWARE
    # 质检时间（秒）
    inspection_time_sec: float = 0.0
    # 质检轮次
    inspection_rounds: int = 1


# ========== 配置类 ==========

@dataclass
class DomainConfig:
    """领域特定配置."""
    # 产品类型
    product_type: ProductType
    # 所需字段列表
    required_fields: List[str]
    # 证据权重因子
    evidence_weight_factor: Dict[str, float]
    # 冲突阈值
    conflict_threshold: float = 0.5
    
    @classmethod
    def hardware(cls) -> DomainConfig:
        """创建硬件产品配置."""
        return cls(
            product_type=ProductType.HARDWARE,
            required_fields=["brand", "model", "price", "spec"],
            evidence_weight_factor={
                "price": 1.2,
                "spec": 1.1,
                "brand": 1.0,
                "model": 1.0,
            },
            conflict_threshold=0.5
        )
    
    @classmethod
    def software(cls) -> DomainConfig:
        """创建软件产品配置."""
        return cls(
            product_type=ProductType.SOFTWARE,
            required_fields=["developer", "platform", "pricing", "rating", "features"],
            evidence_weight_factor={
                "features": 1.3,
                "platform": 1.2,
                "pricing": 1.1,
                "rating": 1.1,
                "developer": 1.0,
            },
            conflict_threshold=0.3
        )

    @classmethod
    def ai_tools(cls) -> DomainConfig:
        """创建AI编程工具配置."""
        return cls(
            product_type=ProductType.AI_TOOLS,
            required_fields=["developer", "platform", "pricing", "supported_languages", "features"],
            evidence_weight_factor={
                "features": 1.3,
                "platform": 1.2,
                "pricing": 1.1,
                "supported_languages": 1.1,
                "developer": 1.0,
            },
            conflict_threshold=0.4
        )


@dataclass
class QualityConfig:
    """增强的质检配置."""
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    
    # 基础配置
    min_score_threshold: float = 0.6
    min_evidence_count: int = 3
    required_fields: Optional[List[str]] = None
    temperature: float = 0.2
    max_tokens: int = 2000
    verbose: bool = True
    
    # 领域配置
    domain_config: Optional[DomainConfig] = None
    product_type: ProductType = ProductType.AUTO_DETECT
    
    # 增强功能配置
    enable_quality_feedback: bool = False
    feedback_log_dir: Optional[str] = None
    enable_multistage_inspection: bool = True
    quick_check_timeout_sec: float = 5.0

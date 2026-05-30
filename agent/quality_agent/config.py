"""Quality inspection configuration and data structures.

所有配置集中管理，支持通过超参数、环境变量或配置文件进行控制。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


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
    OUTDATED_EVIDENCE = "outdated_evidence"      # 过期证据


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


class InspectionMode(str, Enum):
    """检查模式."""
    LLM_ONLY = "llm_only"           # 仅使用LLM检测
    RULE_ONLY = "rule_only"         # 仅使用规则检测
    HYBRID_VOTING = "hybrid_voting" # 混合投票模式（LLM+规则投票）
    LLM_FALLBACK = "llm_fallback"   # LLM为主，规则兜底


class OutputFormat(str, Enum):
    """输出格式."""
    JSON = "json"
    CSV = "csv"
    TEXT = "text"
    MARKDOWN = "markdown"


# ========== 全局常量/关键词配置 ==========

# AI编程工具专用关键词
AI_TOOLS_KEYWORDS = [
    "编程", "代码", "开发", "IDE", "copilot", "coding",
    "智能", "AI", "大模型", "模型", "api", "插件", "tool",
    "compiler", "debugger", "lint", "refactor", "autocomplete"
]

# 导航/无关链接关键词
NAVIGATION_KEYWORDS = [
    "登录", "注册", "首页", "社区", "直播", "专栏", "文章",
    "视频", "问答", "论坛", "帮助", "关于", "联系",
    "copyright", "隐私", "协议", "条款", "404", "error",
    "question-list", "login", "register", "home", "index",
    "terms", "privacy", "contact", "about", "help", "support"
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
    needs_human_review: bool = False         # 是否需要人工审核
    low_confidence_reasons: List[str] = field(default_factory=list)  # 低置信度原因列表
    evidence_quality_avg: float = 1.0        # 证据质量平均值
    domain_type: ProductType = ProductType.HARDWARE  # 领域类型
    inspection_time_sec: float = 0.0         # 质检时间（秒）
    inspection_rounds: int = 1               # 质检轮次
    
    # 投票相关字段
    llm_score: Optional[float] = None        # LLM评分
    rule_score: Optional[float] = None       # 规则评分
    final_decision: Optional[str] = None     # 最终决策来源


# ========== 子配置类 ==========

@dataclass
class DomainConfig:
    """领域特定配置."""
    product_type: ProductType
    required_fields: List[str]
    evidence_weight_factor: Dict[str, float]
    conflict_threshold: float = 0.5
    min_evidence_count: int = 3
    
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
            conflict_threshold=0.5,
            min_evidence_count=3
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
            conflict_threshold=0.3,
            min_evidence_count=3
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
            conflict_threshold=0.4,
            min_evidence_count=3
        )


@dataclass
class LLMConfig:
    """LLM相关配置."""
    api_key: str = ""
    base_url: str = "https://api.siliconflow.cn/v1/chat/completions"
    model: str = "deepseek-ai/DeepSeek-V4-Flash"
    temperature: float = 0.2
    max_tokens: int = 2000
    timeout_sec: float = 30.0
    max_retries: int = 2
    enabled: bool = True


@dataclass
class ConcurrentConfig:
    """并发配置."""
    max_workers: int = 4              # 线程池最大线程数
    max_concurrent: int = 4           # 异步最大并发数
    show_progress: bool = True        # 是否显示进度条
    progress_bar_color: str = "green" # 进度条颜色
    batch_size: int = 100             # 批量处理大小


@dataclass
class OutputConfig:
    """输出配置."""
    format: OutputFormat = OutputFormat.JSON
    verbose: bool = True
    show_summary: bool = True
    save_results: bool = False
    output_dir: str = "./results"
    file_prefix: str = "quality_report"


@dataclass
class VotingConfig:
    """投票机制配置."""
    threshold: float = 0.6            # 投票通过阈值（0-1）
    llm_weight: float = 0.5           # LLM在投票中的权重（0-1）
    rule_weight: float = 0.5          # 规则在投票中的权重（0-1）
    enable_tie_breaker: bool = True   # 启用平局处理
    tie_breaker_strategy: str = "llm" # 平局策略: llm / rule / human


# ========== 主配置类 ==========

@dataclass
class QualityConfig:
    """
    统一的质检配置类。
    
    所有配置参数集中管理，支持：
    1. 直接代码配置
    2. 环境变量配置
    3. 配置文件加载
    
    超参数说明：
    - inspection_mode: 检查模式（llm_only/rule_only/hybrid_voting/llm_fallback）
    - voting_threshold: 投票通过阈值（0-1）
    - voting_llm_weight: LLM投票权重（0-1）
    - min_score_threshold: 最低分数阈值
    - max_workers: 最大并发线程数
    """
    
    # ========== 检查模式配置（核心超参数）==========
    inspection_mode: InspectionMode = InspectionMode.HYBRID_VOTING
    
    # ========== LLM配置 ==========
    llm: LLMConfig = field(default_factory=LLMConfig)
    
    # ========== 规则检测配置 ==========
    rule_enabled: bool = True
    
    # ========== 投票机制配置 ==========
    voting: VotingConfig = field(default_factory=VotingConfig)
    
    # ========== 并发配置 ==========
    concurrent: ConcurrentConfig = field(default_factory=ConcurrentConfig)
    
    # ========== 输出配置 ==========
    output: OutputConfig = field(default_factory=OutputConfig)
    
    # ========== 基础配置 ==========
    min_score_threshold: float = 0.6
    min_evidence_count: int = 3
    required_fields: Optional[List[str]] = None
    
    # ========== 领域配置 ==========
    domain_config: Optional[DomainConfig] = None
    product_type: ProductType = ProductType.AUTO_DETECT
    
    # ========== 增强功能配置 ==========
    enable_quality_feedback: bool = False
    feedback_log_dir: Optional[str] = None
    enable_multistage_inspection: bool = True
    quick_check_timeout_sec: float = 5.0
    
    # ========== 快捷属性 ==========
    @property
    def llm_enabled(self) -> bool:
        return self.llm.enabled and bool(self.llm.api_key)
    
    @llm_enabled.setter
    def llm_enabled(self, value: bool):
        self.llm.enabled = value
    
    @property
    def llm_api_key(self) -> str:
        return self.llm.api_key
    
    @llm_api_key.setter
    def llm_api_key(self, value: str):
        self.llm.api_key = value
    
    @property
    def llm_base_url(self) -> str:
        return self.llm.base_url
    
    @llm_base_url.setter
    def llm_base_url(self, value: str):
        self.llm.base_url = value
    
    @property
    def llm_model(self) -> str:
        return self.llm.model
    
    @llm_model.setter
    def llm_model(self, value: str):
        self.llm.model = value
    
    @property
    def max_workers(self) -> int:
        return self.concurrent.max_workers
    
    @max_workers.setter
    def max_workers(self, value: int):
        self.concurrent.max_workers = value
    
    @property
    def voting_threshold(self) -> float:
        return self.voting.threshold

    @voting_threshold.setter
    def voting_threshold(self, value: float):
        self.voting.threshold = value

    @property
    def voting_llm_weight(self) -> float:
        return self.voting.llm_weight

    @voting_llm_weight.setter
    def voting_llm_weight(self, value: float):
        self.voting.llm_weight = value

    @property
    def voting_rule_weight(self) -> float:
        return self.voting.rule_weight

    @voting_rule_weight.setter
    def voting_rule_weight(self, value: float):
        self.voting.rule_weight = value

    @property
    def verbose(self) -> bool:
        return self.output.verbose
    
    @verbose.setter
    def verbose(self, value: bool):
        self.output.verbose = value
    
    # ========== 配置加载方法 ==========
    @classmethod
    def from_env(cls) -> "QualityConfig":
        """从环境变量加载配置."""
        
        # 解析检查模式
        mode_str = os.getenv("INSPECTION_MODE", "hybrid_voting").lower()
        try:
            mode = InspectionMode(mode_str)
        except ValueError:
            mode = InspectionMode.HYBRID_VOTING
        
        # 解析输出格式
        output_format_str = os.getenv("OUTPUT_FORMAT", "json").lower()
        try:
            output_format = OutputFormat(output_format_str)
        except ValueError:
            output_format = OutputFormat.JSON
        
        return cls(
            # 检查模式
            inspection_mode=mode,
            
            # LLM配置
            llm=LLMConfig(
                api_key=os.getenv("LLM_API_KEY", ""),
                base_url=os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1/chat/completions"),
                model=os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
                temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
                max_tokens=int(os.getenv("LLM_MAX_TOKENS", "2000")),
                timeout_sec=float(os.getenv("LLM_TIMEOUT_SEC", "30.0")),
                max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
                enabled=bool(os.getenv("LLM_API_KEY")),
            ),
            
            # 规则配置
            rule_enabled=cls._parse_bool(os.getenv("RULE_ENABLED", "true")),
            
            # 投票配置
            voting=VotingConfig(
                threshold=float(os.getenv("VOTING_THRESHOLD", "0.6")),
                llm_weight=float(os.getenv("VOTING_LLM_WEIGHT", "0.5")),
                rule_weight=float(os.getenv("VOTING_RULE_WEIGHT", "0.5")),
                enable_tie_breaker=cls._parse_bool(os.getenv("ENABLE_TIE_BREAKER", "true")),
                tie_breaker_strategy=os.getenv("TIE_BREAKER_STRATEGY", "llm"),
            ),
            
            # 并发配置
            concurrent=ConcurrentConfig(
                max_workers=int(os.getenv("MAX_WORKERS", "4")),
                max_concurrent=int(os.getenv("MAX_CONCURRENT", "4")),
                show_progress=cls._parse_bool(os.getenv("SHOW_PROGRESS", "true")),
                progress_bar_color=os.getenv("PROGRESS_COLOR", "green"),
                batch_size=int(os.getenv("BATCH_SIZE", "100")),
            ),
            
            # 输出配置
            output=OutputConfig(
                format=output_format,
                verbose=cls._parse_bool(os.getenv("VERBOSE", "true")),
                show_summary=cls._parse_bool(os.getenv("SHOW_SUMMARY", "true")),
                save_results=cls._parse_bool(os.getenv("SAVE_RESULTS", "false")),
                output_dir=os.getenv("OUTPUT_DIR", "./results"),
                file_prefix=os.getenv("FILE_PREFIX", "quality_report"),
            ),
            
            # 基础配置
            min_score_threshold=float(os.getenv("MIN_SCORE_THRESHOLD", "0.6")),
            min_evidence_count=int(os.getenv("MIN_EVIDENCE_COUNT", "3")),
            
            # 领域配置
            product_type=ProductType(os.getenv("PRODUCT_TYPE", "auto")),
            
            # 增强功能配置
            enable_quality_feedback=cls._parse_bool(os.getenv("ENABLE_FEEDBACK", "false")),
            feedback_log_dir=os.getenv("FEEDBACK_LOG_DIR"),
            enable_multistage_inspection=cls._parse_bool(os.getenv("ENABLE_MULTISTAGE", "true")),
            quick_check_timeout_sec=float(os.getenv("QUICK_CHECK_TIMEOUT", "5.0")),
        )
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "QualityConfig":
        """从字典加载配置."""
        return cls(
            inspection_mode=InspectionMode(config_dict.get("inspection_mode", "hybrid_voting")),
            
            llm=LLMConfig(
                api_key=config_dict.get("llm_api_key", ""),
                base_url=config_dict.get("llm_base_url", "https://api.siliconflow.cn/v1/chat/completions"),
                model=config_dict.get("llm_model", "deepseek-ai/DeepSeek-V4-Flash"),
                temperature=config_dict.get("temperature", 0.2),
                max_tokens=config_dict.get("max_tokens", 2000),
                timeout_sec=config_dict.get("llm_timeout_sec", 30.0),
                max_retries=config_dict.get("llm_max_retries", 2),
                enabled=config_dict.get("llm_enabled", True),
            ),
            
            rule_enabled=config_dict.get("rule_enabled", True),
            
            voting=VotingConfig(
                threshold=config_dict.get("voting_threshold", 0.6),
                llm_weight=config_dict.get("voting_llm_weight", 0.5),
                rule_weight=config_dict.get("voting_rule_weight", 0.5),
                enable_tie_breaker=config_dict.get("enable_tie_breaker", True),
                tie_breaker_strategy=config_dict.get("tie_breaker_strategy", "llm"),
            ),
            
            concurrent=ConcurrentConfig(
                max_workers=config_dict.get("max_workers", 4),
                max_concurrent=config_dict.get("max_concurrent", 4),
                show_progress=config_dict.get("show_progress", True),
                progress_bar_color=config_dict.get("progress_bar_color", "green"),
                batch_size=config_dict.get("batch_size", 100),
            ),
            
            output=OutputConfig(
                format=OutputFormat(config_dict.get("output_format", "json")),
                verbose=config_dict.get("verbose", True),
                show_summary=config_dict.get("show_summary", True),
                save_results=config_dict.get("save_results", False),
                output_dir=config_dict.get("output_dir", "./results"),
                file_prefix=config_dict.get("file_prefix", "quality_report"),
            ),
            
            min_score_threshold=config_dict.get("min_score_threshold", 0.6),
            min_evidence_count=config_dict.get("min_evidence_count", 3),
            product_type=ProductType(config_dict.get("product_type", "auto")),
            
            enable_quality_feedback=config_dict.get("enable_quality_feedback", False),
            feedback_log_dir=config_dict.get("feedback_log_dir"),
            enable_multistage_inspection=config_dict.get("enable_multistage_inspection", True),
            quick_check_timeout_sec=config_dict.get("quick_check_timeout_sec", 5.0),
        )
    
    @classmethod
    def load_from_file(cls, file_path: str) -> "QualityConfig":
        """从配置文件加载配置."""
        import json
        
        with open(file_path, "r", encoding="utf-8") as f:
            config_dict = json.load(f)
        
        return cls.from_dict(config_dict)
    
    def save_to_file(self, file_path: str) -> None:
        """保存配置到文件."""
        import json
        
        config_dict = {
            "inspection_mode": self.inspection_mode.value,
            "llm_api_key": self.llm.api_key,
            "llm_base_url": self.llm.base_url,
            "llm_model": self.llm.model,
            "temperature": self.llm.temperature,
            "max_tokens": self.llm.max_tokens,
            "llm_timeout_sec": self.llm.timeout_sec,
            "llm_max_retries": self.llm.max_retries,
            "llm_enabled": self.llm.enabled,
            "rule_enabled": self.rule_enabled,
            "voting_threshold": self.voting.threshold,
            "voting_llm_weight": self.voting.llm_weight,
            "voting_rule_weight": self.voting.rule_weight,
            "enable_tie_breaker": self.voting.enable_tie_breaker,
            "tie_breaker_strategy": self.voting.tie_breaker_strategy,
            "max_workers": self.concurrent.max_workers,
            "max_concurrent": self.concurrent.max_concurrent,
            "show_progress": self.concurrent.show_progress,
            "progress_bar_color": self.concurrent.progress_bar_color,
            "batch_size": self.concurrent.batch_size,
            "output_format": self.output.format.value,
            "verbose": self.output.verbose,
            "show_summary": self.output.show_summary,
            "save_results": self.output.save_results,
            "output_dir": self.output.output_dir,
            "file_prefix": self.output.file_prefix,
            "min_score_threshold": self.min_score_threshold,
            "min_evidence_count": self.min_evidence_count,
            "product_type": self.product_type.value,
            "enable_quality_feedback": self.enable_quality_feedback,
            "feedback_log_dir": self.feedback_log_dir,
            "enable_multistage_inspection": self.enable_multistage_inspection,
            "quick_check_timeout_sec": self.quick_check_timeout_sec,
        }
        
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=2, ensure_ascii=False)
    
    def validate(self) -> List[str]:
        """验证配置的有效性."""
        errors = []
        
        # 检查阈值范围
        if not (0 <= self.voting.threshold <= 1):
            errors.append(f"voting_threshold must be between 0 and 1, got {self.voting.threshold}")
        if not (0 <= self.voting.llm_weight <= 1):
            errors.append(f"voting_llm_weight must be between 0 and 1, got {self.voting.llm_weight}")
        if not (0 <= self.voting.rule_weight <= 1):
            errors.append(f"voting_rule_weight must be between 0 and 1, got {self.voting.rule_weight}")
        if not (0 <= self.min_score_threshold <= 1):
            errors.append(f"min_score_threshold must be between 0 and 1, got {self.min_score_threshold}")
        
        # 检查并发数
        if self.concurrent.max_workers < 1:
            errors.append(f"max_workers must be at least 1, got {self.concurrent.max_workers}")
        if self.concurrent.max_concurrent < 1:
            errors.append(f"max_concurrent must be at least 1, got {self.concurrent.max_concurrent}")
        
        # 检查LLM配置
        if self.llm.enabled and not self.llm.api_key:
            errors.append("llm_enabled is True but llm_api_key is empty")
        
        # 检查投票权重和
        if abs(self.voting.llm_weight + self.voting.rule_weight - 1.0) > 0.01:
            errors.append(f"voting weights should sum to 1.0, got {self.voting.llm_weight + self.voting.rule_weight}")
        
        return errors
    
    def print_summary(self) -> None:
        """打印配置摘要."""
        print("=" * 60)
        print("Quality Config Summary")
        print("=" * 60)
        print(f"Inspection Mode: {self.inspection_mode.value}")
        print(f"LLM Enabled: {self.llm_enabled}")
        print(f"Rule Enabled: {self.rule_enabled}")
        print(f"Min Score Threshold: {self.min_score_threshold}")
        print(f"Min Evidence Count: {self.min_evidence_count}")
        print(f"Product Type: {self.product_type.value}")
        print()
        print("Voting Configuration:")
        print(f"  Threshold: {self.voting.threshold}")
        print(f"  LLM Weight: {self.voting.llm_weight}")
        print(f"  Rule Weight: {self.voting.rule_weight}")
        print()
        print("Concurrent Configuration:")
        print(f"  Max Workers: {self.concurrent.max_workers}")
        print(f"  Max Concurrent: {self.concurrent.max_concurrent}")
        print(f"  Batch Size: {self.concurrent.batch_size}")
        print()
        print("Output Configuration:")
        print(f"  Format: {self.output.format.value}")
        print(f"  Verbose: {self.output.verbose}")
        print(f"  Save Results: {self.output.save_results}")
        print("=" * 60)
    
    @staticmethod
    def _parse_bool(value: Optional[str]) -> bool:
        """解析布尔字符串."""
        if value is None:
            return False
        return value.lower() in ("true", "1", "yes", "on")


# ========== 预设配置 ==========

def create_default_config() -> QualityConfig:
    """创建默认配置."""
    return QualityConfig()


def create_llm_only_config() -> QualityConfig:
    """创建仅LLM检测配置."""
    return QualityConfig(
        inspection_mode=InspectionMode.LLM_ONLY,
        rule_enabled=False,
    )


def create_rule_only_config() -> QualityConfig:
    """创建仅规则检测配置."""
    return QualityConfig(
        inspection_mode=InspectionMode.RULE_ONLY,
        llm=LLMConfig(enabled=False),
    )


def create_hybrid_voting_config(
    llm_weight: float = 0.5,
    threshold: float = 0.6,
) -> QualityConfig:
    """创建混合投票配置."""
    return QualityConfig(
        inspection_mode=InspectionMode.HYBRID_VOTING,
        voting=VotingConfig(
            threshold=threshold,
            llm_weight=llm_weight,
            rule_weight=1.0 - llm_weight,
        ),
    )


def create_high_performance_config() -> QualityConfig:
    """创建高性能配置（适合大批量处理）."""
    return QualityConfig(
        concurrent=ConcurrentConfig(
            max_workers=8,
            max_concurrent=8,
            batch_size=200,
        ),
        llm=LLMConfig(
            timeout_sec=60.0,
            max_retries=3,
        ),
    )


# ========== 配置模板生成 ==========

def generate_config_template(file_path: str = "quality_config_template.json") -> None:
    """生成配置文件模板."""
    template = {
        "description": "Quality Agent Configuration Template",
        "inspection_mode": "hybrid_voting",  # llm_only / rule_only / hybrid_voting / llm_fallback
        
        "llm_api_key": "",                    # LLM API Key
        "llm_base_url": "https://api.siliconflow.cn/v1/chat/completions",
        "llm_model": "deepseek-ai/DeepSeek-V4-Flash",
        "temperature": 0.2,
        "max_tokens": 2000,
        "llm_timeout_sec": 30.0,
        "llm_max_retries": 2,
        "llm_enabled": True,
        
        "rule_enabled": True,
        
        # Voting Configuration
        "voting_threshold": 0.6,              # 投票通过阈值 (0-1)
        "voting_llm_weight": 0.5,             # LLM权重 (0-1)
        "voting_rule_weight": 0.5,            # 规则权重 (0-1)
        "enable_tie_breaker": True,           # 启用平局处理
        "tie_breaker_strategy": "llm",        # llm / rule / human
        
        # Concurrent Configuration
        "max_workers": 4,                     # 线程池大小
        "max_concurrent": 4,                  # 异步并发数
        "show_progress": True,                # 显示进度条
        "progress_bar_color": "green",
        "batch_size": 100,                    # 批量处理大小
        
        # Output Configuration
        "output_format": "json",              # json / csv / text / markdown
        "verbose": True,
        "show_summary": True,
        "save_results": False,
        "output_dir": "./results",
        "file_prefix": "quality_report",
        
        # Basic Configuration
        "min_score_threshold": 0.6,           # 最低分数阈值
        "min_evidence_count": 3,              # 最小证据数量
        
        # Domain Configuration
        "product_type": "auto",               # hardware / software / auto / ai_tools
        
        # Advanced Features
        "enable_quality_feedback": False,
        "feedback_log_dir": None,
        "enable_multistage_inspection": True,
        "quick_check_timeout_sec": 5.0,
    }
    
    import json
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2, ensure_ascii=False)
    
    print(f"Config template generated: {file_path}")

# 质检Agent改进清单

## 已实现功能 ✅

### 1. 可观测性模块

**状态**: ✅ 已实现
**文件**: `agents/quality_agent/observability.py`

#### 功能列表

| 功能 | 描述 | 状态 |
|------|------|------|
| 日志系统 | 结构化日志记录，支持多级别 | ✅ |
| Token追踪 | 记录每次LLM调用的Token消耗 | ✅ |
| 调用追踪 | 追踪每次操作的时间、成功率 | ✅ |
| Prompt记录 | 记录Prompt和Response内容 | ✅ |
| 统计摘要 | 提供可观测性统计信息 | ✅ |

#### 使用示例

```python
from agents.quality_agent.observability import get_logger, ObservableLogger

# 获取日志记录器
logger = get_logger()

# 记录日志
logger.info("质检开始", product_name="iPhone 15")

# 追踪调用
trace = logger.start_trace("llm_call", model="gpt-4o")
# ... 执行操作 ...
logger.finish_trace(trace, success=True)

# 记录Token使用
logger.record_token_usage(
    prompt_tokens=100,
    completion_tokens=50,
    model="gpt-4o",
    operation="quality_inspection"
)

# 获取统计摘要
summary = logger.get_summary()
```

---

### 2. 上下文管理与幻觉抑制

**状态**: ✅ 已实现
**文件**: `agents/quality_agent/hallucination_suppressor.py`

#### 功能列表

| 功能 | 描述 | 状态 |
|------|------|------|
| 上下文分片 | 处理超长上下文，避免超出限制 | ✅ |
| 自一致性校验 | 检测LLM输出与原始证据的一致性 | ✅ |
| 引用追溯 | 验证结论是否有原始证据支撑 | ✅ |
| 幻觉信号检测 | 检测绝对化表述、模糊来源等信号 | ✅ |
| 可追溯性报告 | 生成详细的引用验证报告 | ✅ |

#### 使用示例

```python
from agents.quality_agent.hallucination_suppressor import (
    create_chunked_context,
    check_hallucination,
    get_traceability_report
)

# 上下文分片
chunks = create_chunked_context(long_text, max_tokens=8192)

# 自一致性校验
result = check_hallucination(
    summary="iPhone 15 起售价 5999 元",
    evidence_text="iPhone 15 128GB 售价 5999 元，来自 Apple 官网"
)

# 可追溯性报告
report = get_traceability_report(summary, candidates, reviews)
print(f"可追溯性得分: {report['traceability_score']}")
```

---

### 3. 规则引擎质检

**状态**: ✅ 已实现
**文件**: `agents/quality_agent/core.py`

- 字段完整性检查
- 证据充分性检查
- 来源追溯性检查
- 冲突证据检测

---

### 4. LLM增强质检

**状态**: ✅ 已实现
**文件**: `agents/quality_agent/core.py`

- 基于LLM的深度语义分析
- 自动降级到规则引擎

---

### 5. 置信度评估

**状态**: ✅ 已实现
**文件**: `agents/quality_agent/core.py`

- 高/中/低三档置信度
- 多因素综合判定

---

### 6. 自动重试机制

**状态**: ✅ 已实现
**文件**: `agents/analysis_agent/product_workflow.py`

- 根据建议生成新搜索查询
- 自动触发搜索Agent重新搜索

---

## 待实现功能 ⏳

### 1. 真正人工介入机制

**状态**: ⏳ 待实现
**依赖**: 前端UI支持

#### 功能描述
当质检报告标记为 `needs_human_review = True` 时，系统应暂停并等待人工审核。

#### 实现需求

| 需求项 | 描述 | 优先级 |
|--------|------|--------|
| 审核队列 | 创建人工审核任务队列 | 高 |
| 审核界面 | 前端展示待审核报告列表 | 高 |
| 审核操作 | 支持通过/拒绝/修改报告 | 高 |
| 通知机制 | 通知审核人员有新任务 | 中 |
| 超时处理 | 设置审核超时自动降级策略 | 中 |

#### 接口设计

```python
class HumanReviewService:
    def submit_for_review(self, report: QualityReport) -> str:
        """提交报告到审核队列，返回任务ID"""
        pass

    def get_review_task(self, task_id: str) -> ReviewTask:
        """获取审核任务详情"""
        pass

    def submit_review_result(self, task_id: str, result: ReviewResult) -> None:
        """提交审核结果"""
        pass

    def get_pending_tasks(self) -> List[ReviewTask]:
        """获取待审核任务列表"""
        pass
```

---

### 2. 审核记录与反馈追踪

**状态**: ⏳ 待实现
**依赖**: 反馈记录器支持

#### 功能描述
记录所有审核操作和结果，支持后续分析和模型优化。

#### 实现需求

| 需求项 | 描述 | 优先级 |
|--------|------|--------|
| 审核日志 | 记录每次审核的时间、人员、结果 | 高 |
| 反馈关联 | 将人工审核结果与原始质检报告关联 | 高 |
| 统计分析 | 统计人工介入率、审核通过/拒绝率 | 中 |
| 模型优化 | 基于审核记录优化质检规则和权重 | 低 |

#### 数据结构

```python
@dataclass
class ReviewRecord:
    id: str
    quality_report_id: str
    reviewer_id: str
    review_time: datetime
    result: Literal["approved", "rejected", "modified"]
    comments: str
    modified_content: Optional[str] = None
    confidence_adjustment: float = 0.0
```

---

### 3. 动态字段配置

**状态**: ⏳ 待实现
**依赖**: 配置管理系统

#### 功能描述
允许根据页面类型动态调整必填字段要求。

#### 实现需求

| 需求项 | 描述 | 优先级 |
|--------|------|--------|
| 页面分类 | 识别页面类型（产品页、评测页、使用指南等） | 中 |
| 字段规则 | 不同页面类型使用不同的必填字段规则 | 中 |
| 配置界面 | 前端配置字段规则 | 低 |

---

### 4. 多轮质检策略优化

**状态**: ⏳ 待实现
**依赖**: 工作流引擎

#### 功能描述
支持更智能的多轮质检策略，减少不必要的重试。

#### 实现需求

| 需求项 | 描述 | 优先级 |
|--------|------|--------|
| 重试次数限制 | 设置最大重试次数 | 高 |
| 渐进式阈值 | 每轮重试提高通过阈值 | 中 |
| 智能跳过 | 对于无法通过规则修复的问题直接标记 | 中 |

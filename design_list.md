# 多 Agent 竞品分析系统设计文档

## 一、需求分析

### 1.1 核心功能需求

根据业务需求，系统需要实现以下核心功能：

| 功能模块 | 需求描述 | 重要性 |
|---------|---------|-------|
| **信息采集 Agent** | 支持问卷设计、问卷调研、用户访谈等信息采集能力 | 高 |
| **分析师 Agent** | 负责数据抓取、结构化整理、竞品知识提取 | 高 |
| **报告撰写 Agent** | 生成竞品分析报告，支持 SWOT 分析等 | 高 |
| **质检 Agent** | 事实校验、质量检查、问题识别 | 高 |
| **知识结构化** | 定义竞品知识 Schema（功能树、定价模型、用户画像） | 高 |
| **协作与反馈闭环** | DAG 式任务流转，质检打回机制，迭代闭环 | 高 |
| **信息溯源** | 每条分析结论标注数据来源，支持 traceability | 高 |
| **可观测性** | 日志可查看，每个 Agent 的决策过程与中间产物均可追溯 | 中 |

### 1.2 技术考察要点

| 考察要点 | 需求描述 |
|---------|---------|
| 多 Agent 编排 | 使用 LangGraph/CrewAI 进行多 Agent 协作编排 |
| 结构化知识抽取 | 设计统一的知识 Schema，确保输出一致性 |
| Agent 间通信 | 采用结构化消息传递（类似 function calling） |
| 信息溯源 | 每条结论可定位到原始数据源 |
| 反馈闭环 | 质检 Agent 能识别问题并打回重做 |
| 可观测性 | 完整的日志、追踪、中间产物存储 |

---

## 二、当前实现状态评估

### 2.1 已完成功能

| 功能 | 状态 | 文件位置 |
|------|------|---------|
| 信息采集（搜索） | ✅ 已实现 | `report_agent/search_adapter.py` |
| 报告撰写 Agent | ✅ 已实现 | `report_agent/core.py` |
| 质检 Agent 基础功能 | ✅ 已实现 | `agent/quality_agent/` |
| 工作流雏形 | ✅ 已实现 | `workflows/competitor_analysis_workflow.py` |

### 2.2 缺失功能

| 功能 | 状态 | 原因 |
|------|------|------|
| 知识 Schema 定义 | ❌ 未实现 | 缺少统一的数据模型定义 |
| DAG 任务编排 | ❌ 未实现 | 当前为线性流程 |
| 反馈闭环机制 | ❌ 未实现 | 没有质检打回逻辑 |
| 可观测性 | ❌ 未实现 | 缺少完整的追踪能力 |
| Agent 间结构化通信 | ❌ 未实现 | 缺少消息协议设计 |

---

## 三、LangGraph 架构设计

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                    多 Agent 竞品分析系统架构                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │  Collector   │───▶│  Analyst     │───▶│  Writer      │          │
│  │  Agent       │    │  Agent       │    │  Agent       │          │
│  │  (信息采集)  │    │  (分析处理)  │    │  (报告撰写)  │          │
│  └──────────────┘    └──────────────┘    └──────────────┘          │
│         ▲                                           │              │
│         │                                           ▼              │
│  ┌──────────────┐    ┌──────────────────────────────────────┐      │
│  │  Feedback    │◀───│         Quality Agent                │      │
│  │  Loop        │    │    (质检、打回决策、迭代控制)           │      │
│  └──────────────┘    └──────────────────────────────────────┘      │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              CompetitorKnowledge Schema                      │   │
│  │  ┌─────────┐ ┌───────────┐ ┌─────────────┐                  │   │
│  │  │Feature  │ │Pricing    │ │UserProfile  │                  │   │
│  │  │ Tree    │ │ Model     │ │             │                  │   │
│  │  └─────────┘ └───────────┘ └─────────────┘                  │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 核心数据结构设计

#### 3.2.1 知识 Schema

```python
# 功能树节点
FeatureNode:
  - id: str                    # 节点唯一标识
  - name: str                  # 功能名称
  - parent_id: Optional[str]   # 父节点 ID
  - description: str           # 功能描述
  - competitors: List[str]     # 涉及竞品
  - evidence_urls: List[str]   # 证据来源

# 定价模型
PricingModel:
  - competitor: str            # 竞品名称
  - price: float               # 价格
  - currency: str              # 货币类型
  - tier: str                  # 定价层级
  - features: List[str]        # 包含功能
  - evidence_urls: List[str]   # 证据来源

# 用户画像
UserProfile:
  - competitor: str            # 竞品名称
  - demographics: Dict         # 人口统计学特征
  - use_cases: List[str]       # 使用场景
  - pain_points: List[str]     # 用户痛点
  - evidence_urls: List[str]   # 证据来源

# 竞品知识
CompetitorKnowledge:
  - task_id: str               # 任务 ID
  - product_description: str   # 产品描述
  - features: List[FeatureNode]
  - pricing: List[PricingModel]
  - user_profiles: List[UserProfile]
  - created_at: datetime       # 创建时间
  - version: str               # 版本号
```

#### 3.2.2 Agent 状态

```python
AgentState:
  - task_id: str                     # 任务 ID
  - product_description: str         # 产品描述
  - competitors: List[str]           # 竞品列表
  - search_results: List[Dict]       # 搜索结果
  - knowledge: CompetitorKnowledge   # 结构化知识
  - report_markdown: str             # 报告内容
  - quality_issues: List[Issue]      # 质检问题
  - iteration_count: int             # 当前迭代次数
  - max_iterations: int = 3          # 最大迭代次数
  - status: Enum                     # 状态: pending/collecting/analyzing/writing/quality/approved/rejected
```

### 3.3 Agent 节点设计

#### 3.3.1 Collector Agent（信息采集）

| 职责 | 实现说明 |
|------|---------|
| 搜索竞品信息 | 调用搜索接口获取竞品相关数据 |
| 数据预处理 | 清洗、去重、初步筛选 |
| 来源记录 | 记录每条数据的来源 URL |

#### 3.3.2 Analyst Agent（分析师）

| 职责 | 实现说明 |
|------|---------|
| 功能树抽取 | 从搜索结果中提取功能点，构建功能树 |
| 定价信息整理 | 提取各竞品的定价策略 |
| 用户画像分析 | 分析用户群体特征和使用场景 |
| Schema 校验 | 确保输出符合 CompetitorKnowledge Schema |

#### 3.3.3 Writer Agent（报告撰写）

| 职责 | 实现说明 |
|------|---------|
| 报告结构生成 | 生成标准化报告结构 |
| SWOT 分析 | 基于知识生成 SWOT 矩阵 |
| 自然语言润色 | 使用 LLM 提升报告可读性 |
| 溯源标记 | 在报告中标注数据来源 |

#### 3.3.4 Quality Agent（质检）

| 职责 | 实现说明 |
|------|---------|
| 证据完整性检查 | 验证每条结论有足够证据支持 |
| 逻辑一致性检查 | 检查结论之间是否存在矛盾 |
| 结构完整性检查 | 验证报告结构完整 |
| 打回决策 | 根据问题类型决定打回哪个 Agent |

### 3.4 DAG 工作流设计

```
                    ┌──────────────┐
                    │   Start      │
                    └──────┬───────┘
                           ▼
              ┌──────────────────────┐
              │  Collector Agent     │
              │   (信息采集)         │
              └──────────┬───────────┘
                         ▼
              ┌──────────────────────┐
              │  Analyst Agent       │
              │   (分析处理)         │
              └──────────┬───────────┘
                         ▼
              ┌──────────────────────┐
              │  Writer Agent        │
              │   (报告撰写)         │
              └──────────┬───────────┘
                         ▼
              ┌──────────────────────┐
              │  Quality Agent       │
              │   (质量检查)         │
              └──────────┬───────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   ┌─────────┐    ┌───────────┐    ┌───────────┐
   │ Approve │    │ Retry     │    │ Retry     │
   │  (通过) │    │ Collector │    │ Analyst   │
   └────┬────┘    └─────┬─────┘    └─────┬─────┘
        │               │                 │
        ▼               └────────┬────────┘
   ┌─────────┐                   │
   │  End    │◀──────────────────┘
   └─────────┘
```

### 3.5 条件分支逻辑

| 条件 | 目标节点 | 说明 |
|------|---------|------|
| 无质量问题 | END | 报告通过，流程结束 |
| 缺少证据 | Collector Agent | 打回采集 Agent 补充数据 |
| 结构错误 | Analyst Agent | 打回分析 Agent 重新整理 |
| 内容错误 | Writer Agent | 打回撰写 Agent 重新生成 |
| 达到最大迭代 | END | 强制结束，记录问题 |

### 3.6 专业反馈闭环设计

#### 3.6.1 问题类型与打回目标映射

| 问题类型 | 问题枚举 | 打回目标 | 修复策略 |
|---------|---------|---------|---------|
| 内容错误 | `CONTENT_ERROR` | Writer Agent | 重新撰写报告内容 |
| 语言表达问题 | `LANGUAGE_ERROR` | Writer Agent | 优化语言表达 |
| 报告结构不完整 | `STRUCTURE_ERROR` | Writer Agent | 补充缺失章节 |
| 逻辑不一致 | `LOGICAL_INCONSISTENCY` | Analyst Agent | 重新分析逻辑 |
| 分析不完整 | `ANALYSIS_INCOMPLETE` | Analyst Agent | 补充分析维度 |
| 证据不足 | `INSUFFICIENT_EVIDENCE` | Collector Agent | 补充数据采集 |
| 低质量证据 | `LOW_QUALITY_EVIDENCE` | Collector Agent | 更新数据源 |
| 证据过时 | `OUTDATED_EVIDENCE` | Collector Agent | 获取最新数据 |

#### 3.6.2 智能打回决策机制

```python
# 打回优先级：数据采集 > 分析处理 > 报告撰写
def decide_feedback_target(issues):
    # 1. 检查数据采集类问题（最高优先级）
    collector_issues = {
        INSUFFICIENT_EVIDENCE, LOW_QUALITY_EVIDENCE, OUTDATED_EVIDENCE
    }
    if any(issue.type in collector_issues for issue in issues):
        return "collector"
    
    # 2. 检查分析类问题
    analyst_issues = {
        LOGICAL_INCONSISTENCY, ANALYSIS_INCOMPLETE
    }
    if any(issue.type in analyst_issues for issue in issues):
        return "analyst"
    
    # 3. 其他问题打回撰写
    writer_issues = {
        CONTENT_ERROR, STRUCTURE_ERROR, LANGUAGE_ERROR
    }
    if any(issue.type in writer_issues for issue in issues):
        return "writer"
    
    return None  # 无需打回
```

#### 3.6.3 状态保留机制

为提高效率，打回时保留上游阶段的输出：

| 打回目标 | 保留的上游状态 | 重新执行的阶段 |
|---------|--------------|---------------|
| Writer Agent | search_results, knowledge | 仅重新撰写报告 |
| Analyst Agent | search_results | 重新分析 + 重新撰写 |
| Collector Agent | 无 | 重新采集 + 重新分析 + 重新撰写 |

#### 3.6.4 效率对比

| 场景 | 线性流程耗时 | 专业闭环耗时 | 效率提升 |
|------|------------|-------------|---------|
| 报告内容小问题 | 5分钟 | 1分钟 | **80%** |
| 分析逻辑问题 | 5分钟 | 2分钟 | **60%** |
| 数据采集问题 | 5分钟 | 5分钟 | 0%（必须重新采集） |

---

## 四、关键设计决策

### 4.1 技术选型

| 维度 | 选型 | 理由 |
|------|------|------|
| Agent 编排框架 | LangGraph | 原生支持 DAG、状态管理、可观测性 |
| LLM 接口 | LangChain | 统一的 LLM 调用接口，支持多种模型 |
| 数据序列化 | Pydantic | 强类型校验，便于 Schema 定义 |
| 日志追踪 | LangSmith | 与 LangGraph 深度集成，支持完整追踪 |

### 4.2 容错与稳定性设计

| 策略 | 实现方式 |
|------|---------|
| 超时重试 | 每个 Agent 设置超时时间，自动重试 |
| 降级机制 | LLM 服务不可用时使用缓存结果 |
| 幻检测控 | 通过自一致性校验识别幻觉 |
| 最大迭代限制 | 防止无限循环，最多迭代 3 次 |

### 4.3 可观测性设计

| 追踪维度 | 实现内容 |
|----------|---------|
| 输入输出 | 记录每个 Agent 的输入输出 |
| 决策过程 | 记录 Agent 的思考过程 |
| Token 消耗 | 统计每次 LLM 调用的 Token 使用 |
| 执行时间 | 记录每个步骤的耗时 |
| 中间产物 | 持久化搜索结果、知识结构、报告草稿 |

---

## 五、实现计划

### 5.1 阶段划分

| 阶段 | 时间 | 任务 |
|------|------|------|
| **Phase 1** | 0.5 周 | 架构设计、Schema 定义 |
| **Phase 2** | 1 周 | Agent 单体开发 |
| **Phase 3** | 1 周 | LangGraph 编排、反馈闭环 |
| **Phase 4** | 0.5 周 | 测试验证、文档准备 |

### 5.2 文件结构

```
bytedance-ai-competition/
├── workflows/
│   ├── __init__.py
│   ├── langgraph_schema.py      # 知识 Schema 定义
│   ├── langgraph_agents.py      # Agent 节点实现
│   ├── langgraph_workflow.py    # LangGraph 工作流
│   └── observability.py         # 可观测性支持
├── report_agent/                # 报告生成模块（复用）
├── agent/quality_agent/         # 质检模块（复用）
└── tests/
    └── test_langgraph_workflow.py  # 工作流测试
```

### 5.3 关键实现步骤

#### Step 1: 定义知识 Schema
```bash
文件: workflows/langgraph_schema.py
内容: CompetitorKnowledge, FeatureNode, PricingModel, UserProfile
```

#### Step 2: 实现 Agent 节点
```bash
文件: workflows/langgraph_agents.py
内容: CollectorAgent, AnalystAgent, WriterAgent, QualityAgent
```

#### Step 3: 构建 LangGraph 工作流
```bash
文件: workflows/langgraph_workflow.py
内容: StateGraph 定义、条件边、决策函数
```

#### Step 4: 添加可观测性
```bash
文件: workflows/observability.py
内容: 日志记录、中间产物存储、追踪集成
```

#### Step 5: 测试与验证
```bash
文件: tests/test_langgraph_workflow.py
内容: 完整工作流测试、反馈闭环测试
```

---

## 六、预期成果

### 6.1 功能达成

| 需求 | 达成状态 |
|------|---------|
| 多 Agent 编排 | ✅ 使用 LangGraph |
| 知识 Schema 定义 | ✅ 统一的数据模型 |
| 反馈闭环机制 | ✅ DAG 条件分支 |
| 信息溯源 | ✅ 证据来源记录 |
| 可观测性 | ✅ 完整追踪能力 |

### 6.2 技术指标

| 指标 | 目标 |
|------|------|
| 工作流成功率 | ≥ 95% |
| 迭代收敛率 | ≥ 90%（3 次迭代内通过） |
| 平均响应时间 | ≤ 5 分钟 |
| 可观测覆盖率 | 100%（所有 Agent 节点） |

---

## 七、风险与应对

| 风险 | 应对策略 |
|------|---------|
| LLM 服务不稳定 | 增加重试机制、降级方案 |
| 迭代陷入死循环 | 设置最大迭代次数限制 |
| 数据来源不可靠 | 增加证据质量评估 |
| Schema 变更 | 使用版本化 Schema 管理 |

---

**文档版本**: v1.0  
**创建时间**: 2026-05-27  
**适用场景**: 多 Agent 竞品分析系统设计
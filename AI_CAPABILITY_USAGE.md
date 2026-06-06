# 大模型 / AI 能力使用说明

<div style="display: grid; grid-template-columns: repeat(2, minmax(280px, 1fr)); gap: 24px; margin-top: 20px;">

<div style="border: 1px solid #7aa2ff; border-radius: 8px; background: #f3f6ff; padding: 22px 26px;">

### 🤖 模型调用

- **主模型**：火山方舟 / 豆包兼容模型，可通过环境变量切换。

- **兼容模型**：支持 SiliconFlow、小米 MiMo 等 OpenAI 兼容接口。

- **调用方式**：统一通过自定义 LLM Client 调用模型接口。

- **主要用途**：搜索词改写、竞品信息理解、问卷生成、问卷分析、证据结构化、竞品对比、SWOT 分析、策略建议、报告撰写。

- **长文本处理**：问卷答卷按 50 份切块，并行总结后逐级合并，降低上下文过长风险。

</div>

<div style="border: 1px solid #7aa2ff; border-radius: 8px; background: #f3f6ff; padding: 22px 26px;">

### 🔧 Agent 设计

- **编排方式**：自研 Python 多 Agent 编排，不依赖 LangGraph / CrewAI 框架。

- **核心角色**：信息采集 Agent、问卷调研 Agent、分析师 Agent、报告撰写 Agent、质检 Agent、知识库构建 Agent。

- **通信协议**：通过结构化数据包传递，包括来源、证据卡、洞察、对比表、报告包、质检反馈。

- **溯源机制**：每条结论绑定 `source_id`、`evidence_id` 和 `claim_evidence_map`，支持追踪来源。

- **反馈机制**：质检 Agent 将问题打回到采集、分析或撰写环节，触发补证据、改结构或重写报告。

</div>

<div style="border: 1px solid #7aa2ff; border-radius: 8px; background: #f3f6ff; padding: 22px 26px;">

### 🧰 工具调用

- **搜索工具**：调用博查搜索、Google 自定义搜索等外部搜索服务，获取竞品官网、评测、参数、价格和用户反馈信息。

- **网页抓取**：支持 requests、Playwright、trafilatura、Crawl4AI 等抓取方式，将网页内容转换为可分析文本。

- **问卷工具**：自动生成问卷、模拟填写答卷、读取真实答卷，并对问卷结果进行统计和大模型总结。

- **表格补全工具**：先生成对比表结构，再识别缺失字段，对缺失内容进行定向搜索和回填。

- **知识库工具**：将最终报告和分析总报告沉淀为 Skill Wiki，支持后续问答、复用和证据追溯。

</div>

<div style="border: 1px solid #7aa2ff; border-radius: 8px; background: #f3f6ff; padding: 22px 26px;">

### 📌 生成依据

- **公开信息依据**：竞品官网、公开评测、搜索结果摘要、网页正文和产品参数资料。

- **用户侧依据**：我方产品参数、问卷分析报告、用户画像、使用场景、价格敏感度、采购顾虑和替换意愿。

- **结构化依据**：系统将原始资料转换为来源记录、证据卡、洞察、对比表、SWOT 和策略建议。

- **质检依据**：Quality Agent 根据报告结构、证据覆盖、逻辑一致性、建议可执行性等维度进行检查。

- **可追溯依据**：最终报告保留证据卡索引、来源映射和生成轨迹，便于复核每条结论的来源。

</div>

</div>


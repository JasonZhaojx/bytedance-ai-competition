# 多 Agent 竞品分析系统

这是一个面向竞品研究和产品分析的多 Agent 工作流项目。系统可以从产品描述出发，自动搜索候选竞品、整理竞品资料、生成 Markdown 竞品分析报告，并通过 Quality Agent 对报告结构、证据、逻辑和建议可执行性做质量检查。

项目同时提供 Web 工作台和命令行/脚本入口，适合用于课程作业、产品调研原型、竞品分析报告生成和多 Agent 工作流演示。

## 主要功能

- 竞品分析任务：输入产品或分析方向，自动搜索、分析并生成竞品报告。
- 报告撰写 Agent：生成竞品概览、功能对比、SWOT、机会风险和产品建议。
- Quality Agent：检查报告结构、证据支持、逻辑一致性、竞品覆盖和建议可执行性，并输出质检 Issue。
- 质量闭环：支持开启质检反馈，让系统根据问题继续补充或修正报告。
- 报告库：查看历史任务生成的最终报告、分析报告、单品报告和质检报告。
- 问卷模块：生成调研问卷、模拟填写问卷、分析问卷结果。
- 技能知识库：从历史报告中抽取可复用分析经验，并支持基于知识库提问。

## 目录结构

```text
.
├── backend/                 # 标准库 Web 后端，提供 API 和静态页面服务
├── frontend/                # Web 工作台页面
├── report_agent/            # 搜索、分析和报告撰写模块
├── agent/quality_agent/     # 报告质检模块
├── workflows/               # 质量闭环和工作流相关代码
├── questionnaires/          # 问卷生成、模拟和分析结果
├── reports/                 # 运行后生成的报告和质量检查结果
├── skill_wiki_builder/      # 从报告构建技能知识库
├── docs/                    # 使用流程等项目文档
└── design_list.md           # 多 Agent 系统设计说明
```

## 环境准备

建议使用 Python 3.10 或更高版本。

Windows PowerShell 下可以直接运行安装向导：

```powershell
.\install_project_env.ps1
```

安装脚本会创建或复用虚拟环境，并安装运行依赖。需要真实联网搜索、LLM 生成或问卷分析时，请按你使用的服务配置对应环境变量，例如：

```powershell
$env:ARK_API_KEY="你的模型 API Key"
$env:BOCHA_API_KEY="你的搜索 API Key"
$env:GOOGLE_API_KEY="你的 Google API Key"
$env:GOOGLE_CX_ID="你的 Google CX ID"
```

具体可用参数会根据搜索后端和模型服务而变化；没有配置外部服务时，部分联网搜索和 LLM 能力可能不可用。

## 启动 Web 工作台

推荐使用项目菜单启动：

```powershell
.\start_competitor_ai.ps1
```

菜单中选择：

1. 安装/更新 Python 环境。
2. 使用本地 Python 启动 Web 服务器。

默认访问地址：

```text
http://127.0.0.1:8000
```

也可以直接启动后端：

```powershell
python backend\server.py 8000
```

## 基本使用流程

1. 打开 Web 工作台。
2. 在任务输入框填写产品或竞品分析需求，例如“帮我分析 AI IDE 领域的主要竞品”。
3. 可选填写已知竞品、搜索数量、质量闭环开关等参数。
4. 点击开始分析，等待搜索、分析、报告生成和质检完成。
5. 在报告预览区查看最终 Markdown 报告。
6. 在报告库查看历史报告，在 Issue 页面查看质检发现的问题。
7. 如需用户调研，可进入问卷模块生成并分析问卷。
8. 如需复用报告经验，可用知识库模块构建 skill wiki。

更完整的端到端操作说明见 `docs/system_end_to_end_flow.md`。

## 命令行示例

运行 Report Agent 示例：

```powershell
python report_agent\run_example.py "AI IDE 编程助手竞品分析" --competitors "Trae, Cursor"
```

运行 Quality Agent 检查报告：

```powershell
python -m agent.quality_agent.cli path\to\report.json --output-format json --output-dir reports\quality_inspections
```

生成相似产品报告：

```powershell
python run_similar_product_reports_with_new_analyze_quality.py
```

## 相关文档

- `design_list.md`：多 Agent 架构、反馈闭环和设计目标。
- `docs/system_end_to_end_flow.md`：系统端到端使用流程。
- `agent/quality_agent/README.md`：Quality Agent 架构、输入输出和检查维度。
- `CORE_TECH_STACK.md`：核心技术栈说明。
- `SYSTEM_ARCHITECTURE_DIAGRAM.md`：系统架构图。

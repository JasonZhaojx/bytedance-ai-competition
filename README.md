# Competitor AI 竞品分析工作流

Competitor AI 是一个面向产品经理、市场分析和研发决策场景的本地竞品分析工作流。项目通过 Web 控制台把“需求输入 -> 竞品发现 -> 单品资料抓取与分析 -> 综合报告生成 -> 报告质检 -> 问卷与知识库沉淀”串成一条可操作的流程，最终输出 Markdown、JSON、CSV 等本地文件。

## 功能概览

- Web 工作台：在浏览器中创建分析任务、查看运行日志、选择竞品、预览 Markdown 报告。
- 竞品发现与资料抓取：支持搜索相关产品、抓取网页正文，并可用 Playwright / Crawl4AI 增强动态网页解析。
- Report Agent：把多个单品分析结果整合为结构化竞品报告、证据卡、对比表和最终综合报告。
- Quality Agent：对报告结构、证据、逻辑、建议等维度做质量检查，并生成质检报告。
- 问卷中心：生成竞品调研问卷、模拟问卷填写、分析问卷结果。
- Skill Wiki：从已生成报告中沉淀可复用的知识文件、表格、玩法指南和参考材料。

## 依赖环境

推荐环境：

- Windows 10/11
- Python 3.10 或更高版本
- pip、venv
- 可访问大模型和搜索服务的网络环境

核心 Python 包由安装脚本自动安装，主要包括：

```text
requests
openai
duckduckgo-search
trafilatura
beautifulsoup4
lxml
playwright
crawl4ai
python-dotenv
tqdm
pydantic
python-dateutil
```

可选开发依赖：

```text
pytest
pytest-asyncio
black
flake8
mypy
langchain-openai
```

常用环境变量：

```powershell
# 大模型配置，0 = 豆包/火山 Ark，1 = SiliconFlow，2 = 小米 MiMo
$env:LLM_PROVIDER="0"
$env:LLM0_API_KEY="your-ark-api-key"
$env:LLM0_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
$env:LLM0_MODEL="your-model"

# 搜索配置，按实际使用的搜索源填写
$env:BOCHA_API_KEY="your-bocha-api-key"
$env:GOOGLE_API_KEY="your-google-api-key"
$env:GOOGLE_CX_ID="your-google-cx-id"
```

也可以在仓库根目录创建 `.env` 文件保存本机配置。`.env`、`.local_env.bat`、`.local_python_path.txt`、`.venv/` 等本地环境文件默认不提交到仓库。

当然也可以运行项目后在设置里填写

## 安装步骤

进入项目根目录：

```powershell
cd E:\deep-learning\zhengce\bytedance-ai-competition-workflow_v4
```

推荐使用启动菜单安装环境：

```bat
start_competitor_ai.bat
```

菜单中选择：

```text
[1] 安装/更新 Python 环境
```

安装向导会自动搜索本机 Python 解释器。推荐安装流程：

1. 在解释器列表里优先选择 conda / Anaconda / Miniconda 的 `python.exe`，例如 `E:\anaconda\python.exe`。
2. 询问是否创建或复用独立虚拟环境时，选择 `Y`，建议让脚本创建项目自己的 `.venv`。
3. 后续安装依赖、初始化 Playwright、初始化 Crawl4AI 等确认项，直接一路按回车或输入 `Y` 即可。

安装成功后会写入：
```text
.local_env.bat
.local_python_path.txt
```

也可以直接运行安装脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_project_env.ps1
```

如果已经有装好依赖的 Python 环境，可以运行 `start_competitor_ai.bat` 后选择：

```text
[3] 使用我已经装好环境的 Python
```

然后填写 `python.exe` 完整路径，或填写系统命令名 `python`、`python3`、`py`。

## 启动步骤

推荐启动方式：

```bat
start_competitor_ai.bat
```

菜单中选择：

```text
[2] 使用本地 Python 启动 Web 服务器
```

默认端口为 `8000`，启动后访问：

```text
http://127.0.0.1:8000
```

直接启动后端也可以：

```powershell
python backend\server.py 8000
```

如果你已经通过安装脚本保存了本地 Python 路径，也可以使用 `.local_python_path.txt` 中记录的解释器运行：

```powershell
E:\anaconda\python.exe backend\server.py 8000
```

Web 控制台主要页面包括：

- 工作台：创建竞品分析任务，配置搜索、模型、质检和已有材料。
- 报告库：查看和预览 `reports/` 下的 Markdown 报告。
- 问卷中心：生成问卷、模拟回答、分析问卷数据。
- 报告 Skill：构建和查看由报告沉淀出的 Skill Wiki。
- 质检 Issue：查看 Quality Agent 发现的问题。
- 配置：填写模型、搜索和流程参数。

## 常用命令（我们还是推荐使用gui版本）

从命令行直接运行完整竞品分析流程：

```powershell
python run_similar_product_reports_with_new_analyze_quality.py "AI IDE 的国产替代品竞品分析"
```

从已有报告目录重新运行 Report Agent：

```powershell
python run_similar_product_reports_with_new_analyze_quality.py --run-mode 1 --report-agent-from-dir reports\20260605_184039 --report-agent-product-description "AI IDE 的国产替代品竞品分析"
```

生成并分析问卷：

```powershell
python generate_competitor_questionnaire.py
```

分析已有问卷和回答文件：

```powershell
python analyze_questionnaire_results.py questionnaires\xxx.jsonl questionnaires\xxx_responses.jsonl "产品或竞品方向"
```

运行单个报告质检：

```powershell
python -m agent.quality_agent.cli reports\your_report.md --save
```

## 目录结构

| 路径 | 说明打*号的是有独立子项目readme的|
| --- | --- |
| [backend/](backend/) | *Web 后端，提供任务、报告、问卷、Skill Wiki 和质检接口。 |
| [frontend/](frontend/) | Web 前端页面、样式和交互逻辑。 |
| [extracted_core/](extracted_core/) | *搜索、抓取、LLM 客户端和产品定位分析核心能力。 |
| [report_agent/](report_agent/) | *综合报告生成 Agent、证据结构化、表格补全和策略建议。 |
| [agent/quality_agent/](agent/quality_agent/) | *报告质量检查 Agent、检查器、评分、反馈和导出逻辑。 |
| [workflows/](workflows/) | 质量闭环等流程编排代码。 |
| [skill_wiki_builder/](skill_wiki_builder/README.md) | *从报告构建 Skill Wiki，并支持基于 Wiki 问答。 |
| [questionnaires/](questionnaires/) | 问卷 JSONL、模拟回答 CSV/JSONL、问卷分析报告。 |
| [reports/](reports/) | 运行生成的单品报告、综合报告、质检结果和 Skill Wiki。 |
| [logs/](logs/) | 运行日志和 Quality Agent 追踪记录。 |
| [install_project_env.ps1](install_project_env.ps1) | Python 环境安装向导。 |
| [start_competitor_ai.bat](start_competitor_ai.bat) | Windows 启动菜单入口。 |
| [start_competitor_ai.ps1](start_competitor_ai.ps1) | 启动菜单的 PowerShell 实现。 |
| [run_similar_product_reports.py](run_similar_product_reports.py) | 早期竞品报告主流程。 |
| [run_similar_product_reports_with_new_analyze.py](run_similar_product_reports_with_new_analyze.py) | 新版分析流程。 |
| [run_similar_product_reports_with_new_analyze_quality.py](run_similar_product_reports_with_new_analyze_quality.py) | 带 Report Agent 和 Quality Agent 的主流程。 |
| [generate_competitor_questionnaire.py](generate_competitor_questionnaire.py) | 竞品调研问卷生成、模拟和分析。 |
| [analyze_questionnaire_results.py](analyze_questionnaire_results.py) | 已有问卷结果分析入口。 |

## 输出文件

主要输出位于 `reports/`：

- `*_FINAL_COMPARISON.md`：最终综合竞品对比报告。
- `*_REPORT_AGENT_ANALYSIS.md`：Report Agent 生成的结构化分析。
- `*_REPORT_AGENT_EVIDENCE_CARDS.md`：证据卡。
- `*_REPORT_AGENT_PACKAGE.json`：结构化报告包。
- `quality_workflow/`：质检报告、反馈载荷和迭代结果。
- `report_agent_tables/`：报告生成过程中导出的对比表 CSV/JSONL。
- `skill_wikis/`：由报告沉淀的 Skill Wiki 文件夹。

问卷相关输出位于 `questionnaires/`，包括问卷题目、模拟回答和问卷分析报告。

## 注意事项

- 首次使用 Playwright 或 Crawl4AI 时需要初始化浏览器依赖，安装脚本会询问是否执行。
- 如果抓取动态网页失败，可以在 Web 控制台或环境变量中切换抓取后端。
- 运行完整竞品分析会调用大模型和搜索服务，请确认 API Key、额度和网络可用。
- 报告、日志、问卷结果属于运行产物，默认不会提交到 Git。

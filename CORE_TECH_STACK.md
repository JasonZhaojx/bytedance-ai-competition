# 核心技术栈

| 层级 | 技术选型 |
| --- | --- |
| 前端 | 原生 HTML + CSS + JavaScript，基于浏览器 Fetch 调用后端接口，支持任务创建、竞品选择、报告预览、问卷中心和知识库问答 |
| 后端 | Python 标准库 HTTP 服务（ThreadingHTTPServer）+ 多线程任务管理 + 子进程启动主分析流程 |
| Agent 编排 | 自研 Python 编排流程，使用 subprocess、ThreadPoolExecutor、结构化反馈消息实现竞品发现、单品并行分析、报告生成、质检打回和循环修正 |
| 大模型 | 火山方舟 / 豆包兼容接口为主，兼容 SiliconFlow、小米 MiMo；统一通过自定义 LLM Client 调用，配合结构化 Prompt 模板 |
| 搜索与抓取 | 博查搜索、Google 自定义搜索、DuckDuckGo；网页抓取支持 requests、Playwright、trafilatura、Crawl4AI |
| 数据存储 | 本地文件系统存储，报告使用 Markdown / JSON，问卷使用 JSONL / CSV，质检和反馈记录使用 JSON / Markdown |
| 知识库 | 基于报告数据集自动生成 Skill Wiki，沉淀为 SKILL.md、references、tables、notes、playbooks 等可复用知识文件 |
| 部署（本地） | 本地 Python 环境运行，提供 PowerShell / BAT 启动脚本；通过本地 Web 服务访问前端页面 |
| 部署（云端） | 通过服务器版本部署在云服务器上，配置好Playwright和 |
| 可观测 | 后端任务日志、运行阶段状态、单品分析产物、Report Agent 生成轨迹、Quality Agent 质检报告和反馈记录可追溯 |


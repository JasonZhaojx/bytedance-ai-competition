# Backend API README

本文档说明 `backend/server.py` 提供的本地 Web 后端 API。后端使用 Python 标准库 `ThreadingHTTPServer` 实现，不依赖额外 Web 框架，默认只监听本机 `127.0.0.1`。

## 启动方式

在仓库根目录运行：

```powershell
python backend\server.py 8000
```

或使用根目录启动菜单：

```bat
start_competitor_ai.bat
```

启动后访问：

```text
http://127.0.0.1:8000
```

不传端口时默认读取环境变量 `WEB_PORT`，没有配置则使用 `8000`。

## 通用约定

- API 基础地址：`http://127.0.0.1:8000`
- JSON 接口响应头：`Content-Type: application/json; charset=utf-8`
- 文件下载接口返回真实文件流。
- 报告路径只能访问 `reports/` 内部的 Markdown 文件。
- 问卷路径只能访问 `questionnaires/` 内部的 `.jsonl`、`.csv`、`.md` 文件。
- 失败时一般返回：

```json
{
  "error": "错误原因"
}
```

常见状态码：

```text
200 OK
201 Created
400 Bad Request
404 Not Found
409 Conflict
```

## 任务 API

### 创建竞品分析任务

```http
POST /api/jobs
```

用途：启动完整竞品分析工作流。后端会创建后台线程，并调用 `run_similar_product_reports_with_new_analyze_quality.py`。

请求示例：

```json
{
  "product_description": "AI IDE 的国产替代品竞品分析",
  "llm_provider": "0",
  "top_n": 3,
  "query_count": 3,
  "search_count": 3,
  "search_backend": 2,
  "max_iterations": 3,
  "analyze_timeout": 1200,
  "final_summary_timeout": 900,
  "evidence_mode": 2,
  "feedback_queries": 2,
  "quality_feedback_search_backend": 0,
  "retry_on_minor": false,
  "enable_quality_loop": true,
  "ark_api_key": "your-api-key",
  "llm_base_url": "https://ark.cn-beijing.volces.com/api/v3",
  "llm_model": "your-model",
  "bocha_api_key": "your-bocha-key",
  "google_api_key": "",
  "google_cx_id": "",
  "known_param_text": "",
  "questionnaire_analysis_text": "",
  "manual_product_selection": ""
}
```

主要字段：

- `product_description`：必填，产品需求或竞品方向。
- `top_n`：候选竞品数量，范围 `1-20`。
- `query_count`：搜索词改写数量，范围 `1-10`。
- `search_count`：每个搜索词返回数量，范围 `1-10`。
- `search_backend`：抓取后端，`0` 传统爬虫，`1` Playwright，`2` Crawl4AI。
- `enable_quality_loop`：是否启用报告质检闭环。
- `max_iterations`：质检最大轮数，范围 `1-10`。
- `evidence_mode`：证据结构化模式，`0-2`。
- `manual_product_selection`：可选，提前指定竞品名称，多个名称可用逗号、顿号或换行分隔。

响应：返回 Job 快照，状态码 `201`。

```json
{
  "job_id": "a1b2c3d4e5f6",
  "product_description": "AI IDE 的国产替代品竞品分析",
  "status": "queued",
  "stage": "prepare",
  "logs": [],
  "runtime_logs": [],
  "report_path": "",
  "report_name": "",
  "waiting_for_selection": false
}
```

### 获取任务列表

```http
GET /api/jobs
```

响应：

```json
{
  "jobs": [
    {
      "job_id": "a1b2c3d4e5f6",
      "status": "running",
      "stage": "analyze",
      "logs": [],
      "runtime_logs": []
    }
  ]
}
```

### 获取任务详情

```http
GET /api/jobs/{job_id}
```

响应字段同 Job 快照，常用字段包括：

- `status`：`queued`、`running`、`completed`、`failed`、`terminating`、`terminated`。
- `stage`：当前流程阶段。
- `logs`：主流程日志，最多返回最近 500 行。
- `runtime_logs`：后端运行日志，最多返回最近 200 行。
- `search_queries`：搜索词。
- `candidate_products`：候选竞品。
- `subtasks`：单品分析子任务状态。
- `report_name`：已生成报告的相对名称。
- `waiting_for_selection`：是否等待用户提交竞品选择。

### 提交竞品选择

```http
POST /api/jobs/{job_id}/selection
```

请求：

```json
{
  "selection": "Trae, 通义灵码, CodeGeeX"
}
```

用途：当主流程等待人工选择竞品时，把选择结果写入子进程 stdin。

### 终止任务

```http
POST /api/jobs/{job_id}/terminate
```

用途：请求终止正在运行的任务。成功后返回最新 Job 快照。

## 报告 API

### 获取报告列表

```http
GET /api/reports
```

扫描 `reports/` 下最近 200 个 Markdown 报告，排除 `reports/web_inputs/`、`reports/skill_wikis/`、`reports/skill_wiki/`。

响应：

```json
{
  "reports": [
    {
      "name": "20260605_184039/20260605_184039_FINAL_COMPARISON.md",
      "path": "E:\\...\\reports\\20260605_184039\\20260605_184039_FINAL_COMPARISON.md",
      "modified_at": 1780000000.0,
      "size": 12345,
      "summary": {
        "title": "报告标题",
        "task_id": "20260605_184039",
        "type": "final",
        "issue_count": 0
      }
    }
  ]
}
```

### 获取报告内容

```http
GET /api/reports/{report_name}
```

`report_name` 需要 URL 编码，值为报告列表中的 `name`。

响应：

```json
{
  "name": "20260605_184039/20260605_184039_FINAL_COMPARISON.md",
  "path": "E:\\...\\reports\\...",
  "modified_at": 1780000000.0,
  "size": 12345,
  "content": "# Markdown 内容",
  "summary": {}
}
```

### 下载报告

```http
GET /download/reports/{report_name}
```

返回 Markdown 文件下载流。

## 问卷 API

### 获取问卷文件列表

```http
GET /api/questionnaires
```

响应：

```json
{
  "files": [
    {
      "name": "20260604_113312_xxx.jsonl",
      "path": "E:\\...\\questionnaires\\20260604_113312_xxx.jsonl",
      "title": "xxx",
      "kind": "questionnaire",
      "kind_label": "问卷",
      "modified_at": 1780000000.0,
      "size": 1234,
      "record_count": 20
    }
  ]
}
```

`kind` 可能为：

```text
questionnaire
response_jsonl
response_csv
analysis
file
```

### 获取问卷文件内容

```http
GET /api/questionnaires/file/{file_name}
```

响应：

```json
{
  "file": {},
  "content": "文件文本内容"
}
```

### 下载问卷文件

```http
GET /download/questionnaires/{file_name}
```

返回 `.jsonl`、`.csv` 或 `.md` 文件下载流。

### 生成问卷

```http
POST /api/questionnaires/generate
```

请求示例：

```json
{
  "product_description": "高端羽毛球拍竞品调研",
  "own_param_text": "",
  "competitor_names": "尤尼克斯天斧100zz, 李宁雷霆80",
  "question_count": 20,
  "questionnaire_search_source": "bocha",
  "skip_search": false,
  "llm_provider": "0",
  "ark_api_key": "your-api-key",
  "llm_base_url": "https://ark.cn-beijing.volces.com/api/v3",
  "llm_model": "your-model",
  "bocha_api_key": "your-bocha-key"
}
```

响应：

```json
{
  "questionnaire": {},
  "items": [],
  "competitors": [],
  "queries": [],
  "warning": "",
  "files": []
}
```

### 生成模拟回答

```http
POST /api/questionnaires/simulate
```

请求：

```json
{
  "questionnaire_name": "20260604_113312_xxx.jsonl",
  "product_description": "高端羽毛球拍竞品调研",
  "own_param_text": "",
  "competitor_names": "尤尼克斯天斧100zz, 李宁雷霆80",
  "simulated_count": 25,
  "llm_provider": "0",
  "ark_api_key": "your-api-key"
}
```

响应：

```json
{
  "questionnaire": {},
  "response_jsonl": {},
  "response_csv": {},
  "response_count": 25,
  "responses_preview": [],
  "warning": "",
  "files": []
}
```

### 分析问卷

```http
POST /api/questionnaires/analyze
```

请求：

```json
{
  "questionnaire_name": "20260604_113312_xxx.jsonl",
  "responses_name": "20260604_113312_xxx_responses.jsonl",
  "product_description": "高端羽毛球拍竞品调研",
  "llm_provider": "0",
  "ark_api_key": "your-api-key"
}
```

响应：

```json
{
  "questionnaire": {},
  "responses": {},
  "analysis": {},
  "analysis_markdown": "# 分析报告",
  "code_analysis": {},
  "warning": "",
  "files": []
}
```

## Skill Wiki API

### 获取 Skill Wiki 列表

```http
GET /api/skill-wikis
```

响应：

```json
{
  "skills": [
    {
      "id": "xxx_Skill",
      "name": "xxx",
      "path": "E:\\...\\reports\\skill_wikis\\xxx_Skill",
      "relative_path": "skill_wikis/xxx_Skill",
      "source_report": "20260605_184039 · 标题 · 最终报告+分析总报告",
      "domain": "AI IDE",
      "modified_at": 1780000000.0,
      "file_count": 12,
      "summary": "",
      "files": []
    }
  ]
}
```

### 获取 Skill Wiki 详情

```http
GET /api/skill-wikis/{skill_id}
```

响应：

```json
{
  "skill": {
    "id": "xxx_Skill",
    "docs": [
      {
        "path": "SKILL.md",
        "content": "# 文档内容",
        "chars": 1234
      }
    ]
  }
}
```

### 从报告构建 Skill Wiki

```http
POST /api/skill-wikis/build
```

请求：

```json
{
  "task_id": "20260605_184039",
  "report_name": "20260605_184039/20260605_184039_REPORT_AGENT_ANALYSIS.md",
  "skill_name": "AI IDE 国产替代品竞品分析 Skill",
  "domain": "AI IDE",
  "llm_provider": "0",
  "ark_api_key": "your-api-key",
  "llm_base_url": "https://ark.cn-beijing.volces.com/api/v3",
  "llm_model": "your-model"
}
```

要求：同一 `task_id` 目录下必须同时存在最终报告和 Report Agent 分析总报告。

响应：

```json
{
  "skill": {}
}
```

### Skill Wiki 问答

```http
POST /api/skill-wikis/chat
```

请求：

```json
{
  "skill_id": "xxx_Skill",
  "question": "这个市场的主要机会点是什么？",
  "domain_hints": "AI IDE",
  "llm_provider": "0",
  "ark_api_key": "your-api-key",
  "llm_base_url": "https://ark.cn-beijing.volces.com/api/v3",
  "llm_model": "your-model"
}
```

响应：

```json
{
  "answer": "回答内容",
  "skill_id": "xxx_Skill",
  "docs_loaded": 12
}
```

## 质检 Issue API

### 获取 Issue 分组

```http
GET /api/issues
```

响应：

```json
{
  "groups": [
    {
      "taskId": "20260605_184039",
      "displayTitle": "报告标题",
      "modifiedAt": 1780000000.0,
      "issueCount": 3,
      "reportCount": 1,
      "typeCounts": {
        "质检报告": 3
      }
    }
  ]
}
```

### 获取指定任务的 Issue

```http
GET /api/issues?task={task_id}
```

响应：

```json
{
  "issues": [
    {
      "taskId": "20260605_184039",
      "report": "20260605_184039/xxx.md",
      "reportTitle": "报告标题",
      "reportType": "质检报告",
      "modifiedAt": 1780000000.0,
      "sourceExists": true,
      "title": "问题标题",
      "detail": "问题详情",
      "reason": "原因",
      "evidence": "证据",
      "suggestion": "建议",
      "severity": "medium",
      "lineNumber": 0,
      "section": "",
      "context": ""
    }
  ]
}
```

## 静态资源

非 `/api/` 和 `/download/` 路径会回退到 `frontend/` 静态文件：

```text
GET /              -> frontend/index.html
GET /styles.css    -> frontend/styles.css
GET /app.js        -> frontend/app.js
```

## 运行相关环境变量

后端和主流程会读取以下常用环境变量：

```text
WEB_PORT
LLM_PROVIDER
LLM0_API_KEY / ARK_API_KEY / LLM_API_KEY
LLM0_BASE_URL / LLM_BASE_URL
LLM0_MODEL / LLM_MODEL
BOCHA_API_KEY
GOOGLE_API_KEY
GOOGLE_CX_ID
TOP_N
QUERY_COUNT
SEARCH_COUNT
SEARCH_BACKEND
ANALYZE_TIMEOUT
FINAL_SUMMARY_TIMEOUT
REPORT_AGENT_EVIDENCE_MODE
REPORT_AGENT_QUALITY_ENABLED
REPORT_AGENT_QUALITY_MAX_ROUNDS
REPORT_AGENT_QUALITY_MAX_FEEDBACK_QUERIES
QUALITY_FEEDBACK_SEARCH_BACKEND
USE_NETWORK_PROXY
```

`USE_NETWORK_PROXY` 未设置为 `1/true/yes/on` 时，后端启动主流程前会移除常见代理环境变量，避免本地无效代理影响 API 请求。

## 文件安全边界

- `safe_report_path()` 限制报告读取和下载只能发生在 `reports/` 内。
- `safe_questionnaire_path()` 限制问卷读取和下载只能发生在 `questionnaires/` 内。
- `safe_skill_wiki_write_path()` 限制 Skill Wiki 写入只能发生在 `reports/skill_wikis/` 内。
- 后端不会提供任意文件读取接口。

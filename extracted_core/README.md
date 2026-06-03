# extracted_core

这是从原项目里拆出来的核心功能包，只保留三类能力：

- `crawler.py`: 网页抓取和正文提取，基于 `requests` + `trafilatura`，支持代理。
- `search.py`: Bocha、Google Custom Search、DuckDuckGo 三种搜索源，并自动抓取搜索结果正文。
- `llm_agent.py`: OpenAI 兼容接口的多步搜索 Agent，模型每轮输出 JSON，决定继续搜索或生成最终答案。

原来的 Streamlit 页面、截图、示例问题和硬编码 API Key 没有复制进来。所有密钥都通过参数或环境变量传入。

## 安装依赖

```bash
pip install -r extracted_core/requirements.txt
```

## 最小用法

```python
from extracted_core import AgentConfig, SearchConfig, SearchSource, run_agent

search_config = SearchConfig(
    source=SearchSource.DUCKDUCKGO,
    proxy="http://127.0.0.1:7890",
    count=3,
    # target_language="zh",  # 如只想保留中文网页正文，可打开这一项
)

agent_config = AgentConfig(
    api_key="your-llm-api-key",
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    model="Doubao-Seed-2.0-lite",
    search=search_config,
    max_steps=8,
)

answer = run_agent("搜索一下美元兑人民币汇率并分析原因", agent_config)
print(answer)
```

## 使用 Bocha 或 Google

```python
SearchConfig(source=SearchSource.BOCHA, bocha_api_key="your-bocha-key")
SearchConfig(
    source=SearchSource.GOOGLE,
    google_api_key="your-google-key",
    google_cx_id="your-cx-id",
)
```

## 命令行示例

PowerShell:

```powershell
$env:LLM_API_KEY="your-llm-api-key"
$env:SEARCH_SOURCE="duckduckgo"
$env:HTTP_PROXY="http://127.0.0.1:7890"
$env:QUESTION="搜索一下美元兑人民币汇率并分析原因"
python -m extracted_core.example
```

## 商品参数采集工作流

`product_workflow.py` 可以根据商品名称搜索京东、淘宝/天猫候选页，尝试抓取页面参数，再让 LLM 输出参数对比总结。

```python
from extracted_core.product_workflow import ProductWorkflowConfig, run_product_workflow
from extracted_core.search import SearchConfig, SearchSource

search_config = SearchConfig(
    source=SearchSource.DUCKDUCKGO,
    proxy="http://127.0.0.1:7890",
    count=5,
    max_search_results=20,
    target_language="zh",
)

config = ProductWorkflowConfig(
    llm_api_key="your-llm-api-key",
    llm_base_url="https://ark.cn-beijing.volces.com/api/v3",
    llm_model="Doubao-Seed-2.0-lite",
    search_config=search_config,
)

result = run_product_workflow("iPhone 16 Pro 256G", config)
print(result.summary)
```

命令行：

```powershell
$env:LLM_API_KEY="your-llm-api-key"
$env:PRODUCT_NAME="iPhone 16 Pro 256G"
$env:SEARCH_SOURCE="duckduckgo"
$env:HTTP_PROXY="http://127.0.0.1:7890"
python -m extracted_core.product_example
```

注意：京东、淘宝、天猫经常使用登录、动态渲染和反爬策略。这个工作流会优先直接抓取页面正文和结构化字段，失败时用搜索摘要兜底，并在总结里标记不确定性。

也可以直接运行脚本：

```powershell
python extracted_core/product_example.py
```

## Product workflow: Bocha-only mode

`product_example.py` is now simplified to use Bocha search only. Fill these
values at the top of the file:

```python
PRODUCT_NAME = "iPhone 16 Pro 256G"
LLM_API_KEY = "your-llm-api-key"
BOCHA_API_KEY = "your-bocha-key"
```

Then run:

```powershell
python extracted_core/product_example.py
```

The workflow now uses Bocha for both shopping-page search and internet
review/blog/community search. Product search keeps only real JD/Taobao/Tmall
domains, then crawls reachable product pages, extracts fields from JSON-LD, meta
tags, page scripts, and visible text, then asks the LLM to summarize the product
parameters in Chinese.

Before searching, the workflow asks the LLM to rewrite the raw product name into
Bocha-friendly query groups:

- `jd_queries`
- `taobao_tmall_queries`
- `review_queries`

Set this to `False` in `product_example.py` if you want to skip query rewriting:

```python
use_llm_query_rewrite=False
```

## Recursive Bocha search

`product_example.py` now runs a generic tree-shaped heuristic recursive search workflow:

1. Search the original question with Bocha.
2. Treat the original query as the root node.
3. Summarize evidence for that node.
4. The LLM generates child queries for that node.
5. Each child query becomes its own node, searches independently, summarizes its
   own evidence, and may create its own children.
6. The final answer is generated from the whole search tree.

Tune it at the top of `product_example.py`:

```python
QUESTION = "小米17 pro max"
LLM_PROVIDER = 0  # 0 = Doubao/Ark, 1 = second OpenAI-compatible provider
MAX_ROUNDS = 4
NEXT_QUERY_COUNT = 2
RESULTS_PER_QUERY = 5
MAX_EVIDENCE_ITEMS = 45
EVIDENCE_TEXT_CHARS = 0
NODE_SUMMARY_CHARS = 0
PLANNING_TEMPERATURE = 0.65
MAX_TOKENS = 10000
MAX_PARALLEL_NODES = 4
```

Set `EVIDENCE_TEXT_CHARS = 0` and `NODE_SUMMARY_CHARS = 0` to preserve full reference text and full node summaries for the final report.
Increase `MAX_EVIDENCE_ITEMS` and `MAX_TOKENS` when single-product `FINAL SUMMARY` needs more detail from search results.
Increase `PLANNING_TEMPERATURE` to make child-query generation more exploratory.
Set `MAX_PARALLEL_NODES` to control same-level parallel node execution.

Switch LLM providers without changing the parallel search flow:

```powershell
$env:LLM_PROVIDER="0"
$env:LLM0_API_KEY="your-ark-key"
$env:LLM0_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
$env:LLM0_MODEL="Doubao-Seed-2.0-lite"
python extracted_core/product_example.py

$env:LLM_PROVIDER="1"
$env:LLM1_API_KEY="your-provider-key"
$env:LLM1_BASE_URL="https://api.openai.com/v1"
$env:LLM1_MODEL="gpt-4o-mini"
python extracted_core/product_example.py
```

It also performs review-oriented searches through Bocha, including general
reviews, blogs, SMZDM, Zhihu, Bilibili, and Xiaohongshu-style queries. You can
control the number of review evidence items in `product_example.py`:

```python
MAX_REVIEW_ITEMS = 6
```

# 搜索Agent & 分析Agent 测试指南

## 快速测试

### 1. 搜索Agent测试

```bash
# 测试搜索功能
python -m agents.test_agents
```

### 2. 完整工作流测试

```bash
# 测试完整产品分析
python run_similar_product_reports.py "iPhone 15"
```

## 工作原理

### 搜索Agent (`search_agent/search.py`)

```
输入: 搜索关键词
  ↓
执行搜索 (DuckDuckGo/Google/Bocha)
  ↓
过滤黑名单域名
  ↓
爬取页面内容
  ↓
输出: SearchResult列表
```

**主要功能:**
- 多搜索引擎支持
- 黑名单过滤
- 页面爬取 (requests / Playwright)
- 内容截取

### 分析Agent (`analysis_agent/product_workflow.py`)

```
输入: 产品名称
  ↓
搜索产品
  ↓
爬取商品页
  ↓
提取参数 (品牌/型号/价格/规格等)
  ↓
质检验证
  ↓
LLM总结
  ↓
输出: 分析报告
```

**主要功能:**
- 多平台分析 (JD/Taobao/Tmall)
- 参数智能提取
- 质检集成
- 多轮迭代优化

## 单独测试各组件

### 测试搜索Agent

```python
from agents.search_agent.search import SearchConfig, search, SearchSource

config = SearchConfig(
    source=SearchSource.DUCKDUCKGO,
    count=3,
    timeout=10,
)

results = search("iPhone 15", config)
for result in results:
    print(f"标题: {result.title}")
    print(f"URL: {result.url}")
```

### 测试分析Agent

```python
from agents.analysis_agent.product_workflow import (
    ProductWorkflowConfig,
    run_product_workflow,
)
from agents.search_agent.search import SearchConfig, SearchSource

search_config = SearchConfig(
    source=SearchSource.DUCKDUCKGO,
    count=3,
)

config = ProductWorkflowConfig(
    llm_api_key="your-api-key",
    llm_base_url="https://api.example.com",
    llm_model="your-model",
    search_config=search_config,
)

result = run_product_workflow("iPhone 15", config)
print(result.summary)
```

### 测试质检Agent

```python
from agents.quality_agent.quality_agent import (
    QualityConfig,
    inspect_quality,
)
from agents.analysis_agent.product_workflow import ProductWorkflowResult

config = QualityConfig(
    llm_api_key="your-api-key",
    llm_base_url="https://api.example.com",
    llm_model="your-model",
)

result = ProductWorkflowResult(...)
report = inspect_quality(result, config)
print(report.passed, report.score)
```

## 配置说明

### 搜索配置

```python
SearchConfig(
    source=SearchSource.DUCKDUCKGO,  # 搜索源
    count=3,                          # 返回数量
    timeout=15,                       # 超时(秒)
    crawl_max_chars=5000,            # 爬取最大字符
    blacklist=[...],                 # 黑名单
)
```

### 分析配置

```python
ProductWorkflowConfig(
    llm_api_key="...",
    llm_base_url="...",
    llm_model="...",
    max_items_per_platform=3,        # 每平台产品数
    max_review_items=6,             # 评论数量
    use_quality_inspection=True,    # 启用质检
    max_iterations=3,               # 最大迭代次数
)
```

## 常见问题

### Q: 搜索被拦截

**解决方案:**
- 使用Playwright爬取 (配置 `crawl_backend=1`)
- 增加超时时间
- 配置代理

### Q: LLM调用失败

**解决方案:**
- 检查API Key和Base URL
- 确认模型名称正确
- 查看日志中的错误信息

### Q: 质检总是不通过

**解决方案:**
- 调整 `quality_threshold` (默认0.6)
- 增加搜索数量
- 检查证据质量

## 运行示例

```bash
# 测试1: 手机产品分析
python run_similar_product_reports.py "iPhone 15 Pro"

# 测试2: 家电产品分析
python run_similar_product_reports.py "小米扫地机器人"

# 测试3: 软件产品分析
python tools/find_similar_products.py "微信 小程序开发工具"
```

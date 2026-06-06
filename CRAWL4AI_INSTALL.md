# Crawl4AI 安装与启用说明

本文档给项目使用者参考，用于启用 `SEARCH_BACKEND = 2`，也就是：

```text
博查搜索 API 返回 URL -> Crawl4AI 抓取网页正文 -> 失败时回退传统爬虫/博查摘要
```

## 1. 安装依赖

建议使用运行项目时同一个 Python 环境安装，例如本项目常用：

```powershell
E:\anaconda\python.exe -m pip install crawl4ai
```

如果要升级：

```powershell
E:\anaconda\python.exe -m pip install --upgrade crawl4ai
```

如果项目依赖统一从 `requirements.txt` 安装：

```powershell
E:\anaconda\python.exe -m pip install -r E:\deep-learning\zhengce\extracted_core\requirements.txt
```

## 2. 初始化浏览器环境

Crawl4AI 底层会使用浏览器能力。安装 Python 包后，还需要初始化相关浏览器依赖。

优先运行：

```powershell
E:\anaconda\Scripts\crawl4ai-setup.exe
```

如果你的环境里没有这个命令，可以用 Playwright 兜底安装 Chromium：

```powershell
E:\anaconda\python.exe -m playwright install chromium
```

注意：不要使用下面这个命令：

```powershell
E:\anaconda\python.exe -m crawl4ai.setup
```

部分版本没有 `crawl4ai.setup` 这个模块，会报：

```text
No module named crawl4ai.setup
```

## 3. 验证安装

验证 Crawl4AI 是否能被当前 Python 导入：

```powershell
E:\anaconda\python.exe -c "from crawl4ai.__version__ import __version__; print(__version__)"
```

如果存在诊断命令，可以运行：

```powershell
E:\anaconda\Scripts\crawl4ai-doctor.exe
```

## 4. 在项目中启用

打开：

```text
E:\deep-learning\zhengce\run_similar_product_reports.py
```

设置：

```python
SEARCH_BACKEND = 2
```

含义如下：

```python
# 0 = 博查 URL + 传统爬虫
# 1 = 博查 URL + Playwright 动态渲染抓正文
# 2 = 博查 URL + Crawl4AI 抓正文
```

搜索 API 仍然固定是博查。`SEARCH_BACKEND` 只决定拿到博查 URL 后，使用哪种方式抓网页正文。

## 5. 运行主流程

```powershell
E:\anaconda\python.exe E:\deep-learning\zhengce\run_similar_product_reports.py
```

启动时会打印当前配置，例如：

```text
search_backend: 2 (博查搜索 + Crawl4AI 抓正文)
```

如果 Crawl4AI 没抓到足够正文，程序会自动回退：

```text
[crawler] Crawl4AI未获取到足够正文，改用传统爬虫: https://example.com
```

如果 Crawl4AI 运行报错，也会回退：

```text
[crawl4ai] crawl failed: https://example.com (...)
[crawler] Crawl4AI失败，改用传统爬虫: https://example.com
```

## 6. 常见问题

### 6.1 `No module named crawl4ai.setup`

这是因为当前 Crawl4AI 版本没有 `python -m crawl4ai.setup` 入口。

使用：

```powershell
E:\anaconda\Scripts\crawl4ai-setup.exe
```

或：

```powershell
E:\anaconda\python.exe -m playwright install chromium
```

### 6.2 `crawl4ai-setup.exe` 找不到

先确认是否装在当前 Python 环境：

```powershell
E:\anaconda\python.exe -m pip show crawl4ai
```

再查看脚本目录：

```powershell
Get-ChildItem E:\anaconda\Scripts\crawl4ai*
```

如果仍然没有，直接用 Playwright 兜底：

```powershell
E:\anaconda\python.exe -m playwright install chromium
```

### 6.3 抓取速度变慢

Crawl4AI 会启动浏览器环境，通常比传统 HTTP 爬虫更重。并行多个产品分析时，内存和 CPU 压力会明显增加。

可以考虑：

```python
SEARCH_BACKEND = 0
```

或减少并发产品数量、减少每个节点的搜索数量。

### 6.4 某些网页仍然抓不到正文

正常。部分网站有反爬、登录墙、动态跳转或内容加载限制。

当前项目逻辑是：

```text
Crawl4AI -> 传统爬虫 -> 博查摘要
```

所以即使 Crawl4AI 失败，流程仍会继续。

## 7. 是否免费

Crawl4AI 本身是本地 Python 包，不是按次收费的云 API。  
但它可能会调用本机浏览器能力，消耗本机 CPU、内存和网络资源。

博查搜索 API 是否收费，取决于你的博查账号和套餐。

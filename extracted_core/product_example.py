"""Bocha recursive search example."""

from __future__ import annotations

import os
import sys
from pathlib import Path


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extracted_core.recursive_search_workflow import (
    RecursiveSearchConfig,
    run_tree_search,
    tree_final_summarize,
)
from extracted_core.search import SearchConfig, SearchSource


# ===== Direct configuration =====
QUESTION = "claude code"

# 0 = 豆包/火山 Ark, 1 = SiliconFlow, 2 = 小米 MiMo
LLM_PROVIDER = 0

LLM0_API_KEY = ""
LLM0_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
LLM0_MODEL = "ep-20260514111325-xjmj7"

LLM1_API_KEY = ""
LLM1_BASE_URL = "https://api.siliconflow.cn/v1/chat/completions"
LLM1_MODEL = "deepseek-ai/DeepSeek-V4-Flash"

LLM2_API_KEY = ""
LLM2_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
LLM2_MODEL = "Xiaomi MiMo-V2.5-Pro"

BOCHA_API_KEY = ""

HTTP_PROXY = ""

MAX_ROUNDS = 3
NEXT_QUERY_COUNT = 3
RESULTS_PER_QUERY = 9
MAX_EVIDENCE_ITEMS = 45
EVIDENCE_TEXT_CHARS = 0
NODE_SUMMARY_CHARS = 0
PLANNING_TEMPERATURE = 0.65
MAX_TOKENS = 10000
MAX_PARALLEL_NODES = 4
LLM_TIMEOUT = 120
FINAL_LLM_TIMEOUT = 900
NODE_TIMEOUT = 240
FILTER_IRRELEVANT_EVIDENCE = True
COMPARISON_KEYWORD_LIBRARY = ""

# 搜索 API 固定用博查；0 = 传统爬虫, 1 = Playwright, 2 = Crawl4AI
SEARCH_BACKEND = 0


def value_or_env(value: str, env_name: str, default: str = "") -> str:
    return os.getenv(env_name) or value or default


def get_llm_provider_config() -> tuple[str, str, str]:
    provider = int(os.getenv("LLM_PROVIDER", str(LLM_PROVIDER)))
    if provider == 0:
        return (
            os.getenv("LLM0_API_KEY") or os.getenv("ARK_API_KEY") or os.getenv("LLM_API_KEY") or LLM0_API_KEY,
            os.getenv("LLM0_BASE_URL") or os.getenv("LLM_BASE_URL") or LLM0_BASE_URL,
            os.getenv("LLM0_MODEL") or os.getenv("LLM_MODEL") or LLM0_MODEL,
        )
    if provider == 1:
        return (
            os.getenv("LLM1_API_KEY") or os.getenv("OPENAI_API_KEY") or LLM1_API_KEY,
            os.getenv("LLM1_BASE_URL") or LLM1_BASE_URL,
            os.getenv("LLM1_MODEL") or LLM1_MODEL,
        )
    if provider == 2:
        return (
            os.getenv("LLM2_API_KEY") or os.getenv("MIMO_API_KEY") or LLM2_API_KEY,
            os.getenv("LLM2_BASE_URL") or LLM2_BASE_URL,
            os.getenv("LLM2_MODEL") or LLM2_MODEL,
        )
    raise ValueError("LLM_PROVIDER must be 0, 1, or 2")


def count_nodes(node) -> int:
    return 1 + sum(count_nodes(child) for child in node.children)


def print_final_chunk(chunk: str) -> None:
    print(chunk, end="", flush=True)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "否", "关闭"}


def main() -> None:
    cli_question = " ".join(sys.argv[1:]).strip()
    question = cli_question or value_or_env(QUESTION, "QUESTION", "小米17 pro max")
    comparison_keyword_library = value_or_env(
        COMPARISON_KEYWORD_LIBRARY,
        "COMPARISON_KEYWORD_LIBRARY",
    )
    llm_api_key, llm_base_url, llm_model = get_llm_provider_config()
    bocha_api_key = value_or_env(BOCHA_API_KEY, "BOCHA_API_KEY")
    search_backend = int(os.getenv("SEARCH_BACKEND", str(SEARCH_BACKEND)))

    if not llm_api_key:
        raise RuntimeError("Please set an active API key for LLM_PROVIDER 0, 1, or 2.")
    if search_backend not in {0, 1, 2}:
        raise RuntimeError("SEARCH_BACKEND must be 0, 1, or 2.")
    if not bocha_api_key:
        raise RuntimeError("Please fill BOCHA_API_KEY at the top of product_example.py")

    search_config = SearchConfig(
        source=SearchSource.BOCHA,
        bocha_api_key=bocha_api_key,
        proxy=value_or_env(HTTP_PROXY, "HTTP_PROXY") or None,
        count=RESULTS_PER_QUERY,
        max_search_results=RESULTS_PER_QUERY,
        crawl_max_chars=0,
        crawl_backend=search_backend,
        target_language="zh",
    )

    config = RecursiveSearchConfig(
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        search_config=search_config,
        max_rounds=int(os.getenv("MAX_ROUNDS", str(MAX_ROUNDS))),
        next_query_count=int(os.getenv("NEXT_QUERY_COUNT", str(NEXT_QUERY_COUNT))),
        results_per_query=int(os.getenv("RESULTS_PER_QUERY", str(RESULTS_PER_QUERY))),
        max_evidence_items=int(os.getenv("MAX_EVIDENCE_ITEMS", str(MAX_EVIDENCE_ITEMS))),
        evidence_text_chars=int(os.getenv("EVIDENCE_TEXT_CHARS", str(EVIDENCE_TEXT_CHARS))),
        node_summary_chars=int(os.getenv("NODE_SUMMARY_CHARS", str(NODE_SUMMARY_CHARS))),
        planning_temperature=float(os.getenv("PLANNING_TEMPERATURE", str(PLANNING_TEMPERATURE))),
        max_tokens=int(os.getenv("MAX_TOKENS", str(MAX_TOKENS))),
        max_parallel_nodes=int(os.getenv("MAX_PARALLEL_NODES", str(MAX_PARALLEL_NODES))),
        llm_timeout=int(os.getenv("LLM_TIMEOUT", str(LLM_TIMEOUT))),
        final_llm_timeout=int(os.getenv("FINAL_LLM_TIMEOUT", str(FINAL_LLM_TIMEOUT))),
        node_timeout=int(os.getenv("NODE_TIMEOUT", str(NODE_TIMEOUT))),
        verbose=True,
        skip_final_summary=True,
        filter_irrelevant_evidence=env_bool(
            "FILTER_IRRELEVANT_EVIDENCE",
            FILTER_IRRELEVANT_EVIDENCE,
        ),
        comparison_keyword_library=comparison_keyword_library,
    )

    if comparison_keyword_library:
        print("\n===== 我方产品参数关键词库 =====\n")
        print(comparison_keyword_library)

    result = run_tree_search(question, config)
    print(
        f"\n===== 参考点统计 =====\n"
        f"搜索树节点数: {count_nodes(result.root)}\n"
        f"参考点数量: {len(result.evidence)}"
    )
    print("\n===== REFERENCE EVIDENCE =====\n")
    for index, item in enumerate(result.evidence, 1):
        text = item.content or item.snippet
        print(f"[参考点{index}]")
        print(f"正文来源: {item.content_source or '未知'}")
        print(f"标题: {item.title}")
        print(f"链接: {item.url}")
        print(f"正文: {text}")
        print()
    print("\n===== FINAL SUMMARY =====\n")
    config.final_stream_printer = print_final_chunk
    result.final_answer = tree_final_summarize(question, result.root, result.evidence, config)
    print()


if __name__ == "__main__":
    main()

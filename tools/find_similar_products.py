"""Find similar products: LLM rewrites search queries, then extracts names."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from extracted_core.positioning_product_workflow import (  # noqa: E402
    PositioningProductConfig,
    run_positioning_product_search,
)
from extracted_core.search import SearchConfig, SearchSource  # noqa: E402


LLM0_API_KEY = os.getenv("LLM0_API_KEY") or os.getenv("ARK_API_KEY") or os.getenv("LLM_API_KEY") or ""
LLM0_BASE_URL = os.getenv("LLM0_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
LLM0_MODEL = os.getenv("LLM0_MODEL", "ep-20260514111325-xjmj7")

LLM1_API_KEY = os.getenv("LLM1_API_KEY") or os.getenv("LLM_API_KEY") or ""
LLM1_BASE_URL = os.getenv("LLM1_BASE_URL", "https://api.siliconflow.cn/v1/chat/completions")
LLM1_MODEL = os.getenv("LLM1_MODEL", "deepseek-ai/DeepSeek-V4-Flash")

LLM2_API_KEY = os.getenv("LLM2_API_KEY") or os.getenv("MIMO_API_KEY") or ""
LLM2_BASE_URL = os.getenv("LLM2_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
LLM2_MODEL = os.getenv("LLM2_MODEL", "Xiaomi MiMo-V2.5-Pro")

# 0 = 豆包/火山 Ark, 1 = SiliconFlow, 2 = 小米 MiMo
LLM_PROVIDER = 0
LLM_PROVIDER = int(os.getenv("LLM_PROVIDER", str(LLM_PROVIDER)))

SEARCH_SOURCE = os.getenv("SEARCH_SOURCE", "bocha")  # bocha, google, duckduckgo
BOCHA_API_KEY = os.getenv("BOCHA_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CX_ID = os.getenv("GOOGLE_CX_ID", "")
HTTP_PROXY = os.getenv("HTTP_PROXY", "")

QUERY_COUNT = int(os.getenv("QUERY_COUNT", "3"))
SEARCH_COUNT = int(os.getenv("SEARCH_COUNT", "5"))


def active_llm_config() -> tuple[str, str, str]:
    if LLM_PROVIDER == 0:
        return LLM0_API_KEY, LLM0_BASE_URL, LLM0_MODEL
    if LLM_PROVIDER == 1:
        return LLM1_API_KEY, LLM1_BASE_URL, LLM1_MODEL
    if LLM_PROVIDER == 2:
        return LLM2_API_KEY, LLM2_BASE_URL, LLM2_MODEL
    raise ValueError("LLM_PROVIDER 必须是 0、1 或 2。")


def read_product_description() -> str:
    description = " ".join(sys.argv[1:]).strip()
    if description:
        return description
    return input("请输入产品需求: ").strip()


def main() -> None:
    product_description = read_product_description()
    if not product_description:
        raise RuntimeError("产品需求不能为空。")
    llm_api_key, llm_base_url, llm_model = active_llm_config()
    if not llm_api_key:
        raise RuntimeError("请先填写当前 LLM_PROVIDER 对应的 API key，例如 LLM0_API_KEY/ARK_API_KEY、LLM1_API_KEY 或 LLM2_API_KEY。")

    source = SearchSource(SEARCH_SOURCE)
    if source == SearchSource.BOCHA and not BOCHA_API_KEY:
        raise RuntimeError("当前 SEARCH_SOURCE=bocha，请先填写 BOCHA_API_KEY。")
    if source == SearchSource.GOOGLE and (not GOOGLE_API_KEY or not GOOGLE_CX_ID):
        raise RuntimeError("当前 SEARCH_SOURCE=google，请先填写 GOOGLE_API_KEY 和 GOOGLE_CX_ID。")

    search_config = SearchConfig(
        source=source,
        bocha_api_key=BOCHA_API_KEY,
        google_api_key=GOOGLE_API_KEY,
        google_cx_id=GOOGLE_CX_ID,
        proxy=HTTP_PROXY or None,
        count=SEARCH_COUNT,
        max_search_results=SEARCH_COUNT,
        crawl_max_chars=2500,
        crawl_min_chars=120,
        timeout=20,
    )
    config = PositioningProductConfig(
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        search_config=search_config,
        query_count=QUERY_COUNT,
        results_per_query=SEARCH_COUNT,
    )

    result = run_positioning_product_search(product_description, config)

    print("\n===== LLM 改写后的搜索词 =====")
    for query in result.queries:
        print(f"- {query}")

    print("\n===== 产品名 =====")
    if not result.product_names:
        print("未提取到产品名")
    for name in result.product_names:
        print(name)


if __name__ == "__main__":
    main()

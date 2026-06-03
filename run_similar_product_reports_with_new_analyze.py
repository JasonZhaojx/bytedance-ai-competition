"""Find similar products, analyze selected products in parallel, and save reports."""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
ANALYZE_WORKER = ROOT / "analyze_product_worker.py"

sys.path.insert(0, str(ROOT))

from extracted_core.llm_client import chat_content, stream_chat_content  # noqa: E402
from extracted_core.positioning_product_workflow import (  # noqa: E402
    PositioningProductConfig,
    run_positioning_product_search,
)
from extracted_core.search import SearchConfig, SearchSource  # noqa: E402
from report_agent.core import run_writing_agent  # noqa: E402
from report_agent.models import WritingAgentConfig  # noqa: E402

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


# 0 = 豆包/火山 Ark, 1 = SiliconFlow, 2 = 小米 MiMo
LLM_PROVIDER = 0
LLM_PROVIDER = int(os.getenv("LLM_PROVIDER", str(LLM_PROVIDER)))

LLM0_API_KEY = (
    os.getenv("LLM0_API_KEY")
    or os.getenv("ARK_API_KEY")
    or ""
)
LLM0_BASE_URL = os.getenv("LLM0_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
LLM0_MODEL = os.getenv("LLM0_MODEL", "ep-20260514111325-xjmj7")

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_KEYS = os.getenv("LLM_API_KEYS", "")
LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL", "https://api.siliconflow.cn/v1/chat/completions"
)
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")

LLM2_API_KEY = os.getenv("LLM2_API_KEY") or os.getenv("MIMO_API_KEY") or ""
LLM2_BASE_URL = os.getenv("LLM2_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
LLM2_MODEL = os.getenv("LLM2_MODEL", "mimo-v2.5-pro")

SEARCH_SOURCE = os.getenv("SEARCH_SOURCE", "bocha")
BOCHA_API_KEY = os.getenv("BOCHA_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CX_ID = os.getenv("GOOGLE_CX_ID", "")
HTTP_PROXY = os.getenv("HTTP_PROXY", "")

# 搜索 API 固定用博查；0 = 传统爬虫, 1 = Playwright, 2 = Crawl4AI
# 使用Crawl4AI请确保设备有足够的内存
SEARCH_BACKEND = 1
SEARCH_BACKEND = int(os.getenv("SEARCH_BACKEND", str(SEARCH_BACKEND)))

QUERY_COUNT = int(os.getenv("QUERY_COUNT", "3"))
SEARCH_COUNT = int(os.getenv("SEARCH_COUNT", "3"))
TOP_N = int(os.getenv("TOP_N", "5"))
ANALYZE_TIMEOUT = int(os.getenv("ANALYZE_TIMEOUT", "1200"))
FINAL_SUMMARY_TIMEOUT = int(os.getenv("FINAL_SUMMARY_TIMEOUT", "900"))

# 运行模式：
# 0 = 从头开始：找竞品 -> 单品分析 -> 总结 -> Report Agent 标准链路
# 1 = 跳过前面步骤：直接读取 REPORT_AGENT_FROM_DIR 文件夹，进入 Report Agent 标准链路
RUN_MODE = 0
RUN_MODE = int(os.getenv("RUN_MODE", str(RUN_MODE)))
REPORT_AGENT_FROM_DIR = os.getenv("REPORT_AGENT_FROM_DIR", "reports").strip()
REPORT_AGENT_FROM_DIR_PATTERN = os.getenv("REPORT_AGENT_FROM_DIR_PATTERN", "*.md").strip() or "*.md"
REPORT_AGENT_PRODUCT_DESCRIPTION = os.getenv("REPORT_AGENT_PRODUCT_DESCRIPTION", "").strip()

FINAL_SUMMARY_MARKER = "===== FINAL SUMMARY ====="
REFERENCE_EVIDENCE_MARKER = "===== REFERENCE EVIDENCE ====="
REFERENCE_POINT_RE = re.compile(r"(?<!\])\[参考点(\d+)\]")
KNOWN_PRODUCT_PARAM_MAX_CHARS = int(os.getenv("KNOWN_PRODUCT_PARAM_MAX_CHARS", "0"))
QUESTIONNAIRE_ANALYSIS_MAX_CHARS = int(
    os.getenv("QUESTIONNAIRE_ANALYSIS_MAX_CHARS", "0")
)
QUESTIONNAIRE_CODE_SUMMARY_MARKER = "===== CODE SUMMARY JSON ====="
REPORT_AGENT_ENABLED = os.getenv("REPORT_AGENT_ENABLED", "1").strip() != "0"
REPORT_AGENT_SOURCE_MAX_CHARS = int(
    os.getenv("REPORT_AGENT_SOURCE_MAX_CHARS", "0")
)
REPORT_AGENT_MAX_PROMPT_SOURCES = int(
    os.getenv("REPORT_AGENT_MAX_PROMPT_SOURCES", "0")
)
REPORT_AGENT_MAX_EVIDENCE_CARDS = int(
    os.getenv("REPORT_AGENT_MAX_EVIDENCE_CARDS", "0")
)
REPORT_AGENT_MAX_TOKENS = int(os.getenv("REPORT_AGENT_MAX_TOKENS", "0"))
REPORT_AGENT_LLM_TIMEOUT = int(os.getenv("REPORT_AGENT_LLM_TIMEOUT", "300"))
REPORT_AGENT_BATCH_WORKERS = 8
REPORT_AGENT_TABLE_GAP_SEARCH = os.getenv("REPORT_AGENT_TABLE_GAP_SEARCH", "1").strip() != "0"
REPORT_AGENT_TABLE_GAP_SEARCH_MAX_QUERIES = int(
    os.getenv("REPORT_AGENT_TABLE_GAP_SEARCH_MAX_QUERIES", "6")
)
REPORT_AGENT_TABLE_GAP_SEARCH_ALL_PENDING = (
    os.getenv("REPORT_AGENT_TABLE_GAP_SEARCH_ALL_PENDING", "1").strip() != "0"
)
REPORT_AGENT_TABLE_GAP_SEARCH_RESULTS = int(
    os.getenv("REPORT_AGENT_TABLE_GAP_SEARCH_RESULTS", "6")
)
REPORT_AGENT_TABLE_GAP_SEARCH_MAX_ROUNDS = int(
    os.getenv("REPORT_AGENT_TABLE_GAP_SEARCH_MAX_ROUNDS", "3")#表格缺口搜索循环轮数。
)
REPORT_AGENT_TABLE_GAP_SEARCH_WORKERS = int(
    os.getenv("REPORT_AGENT_TABLE_GAP_SEARCH_WORKERS", "5")
)
REPORT_AGENT_PRINT_TABLES = os.getenv("REPORT_AGENT_PRINT_TABLES", "1").strip() != "0"
REPORT_AGENT_EXPORT_TABLES = os.getenv("REPORT_AGENT_EXPORT_TABLES", "1").strip() != "0"
REPORT_AGENT_TABLE_EXPORT_DIR = os.getenv(
    "REPORT_AGENT_TABLE_EXPORT_DIR", str(REPORT_DIR / "report_agent_tables")
)
# 0 = 纯规则切片, 1 = 规则切片 + LLM 字段归一化, 2 = 整包 LLM 优先 + 规则兜底
REPORT_AGENT_EVIDENCE_MODE = int(os.getenv("REPORT_AGENT_EVIDENCE_MODE", "2"))


@dataclass
class ReportInput:
    product_name: str
    final_summary: str
    reference_points: str
    path: Path


@dataclass
class RuntimeArgs:
    description_parts: list[str]
    run_mode: int = 0
    report_agent_from_dir: str = ""
    report_agent_pattern: str = "*.md"
    report_agent_product_description: str = ""


def split_pool(value: str) -> list[str]:
    parts = re.split(r"[,;\n]+", value)
    return [part.strip() for part in parts if part.strip()]


def llm_key_pool() -> list[str]:
    keys = split_pool(LLM_API_KEYS)
    if LLM_API_KEY:
        keys.append(LLM_API_KEY)

    deduped = []
    seen = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def mask_key(key: str) -> str:
    if len(key) <= 10:
        return "*" * len(key)
    return f"{key[:6]}...{key[-4:]}"


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def parse_runtime_args() -> RuntimeArgs:
    parser = argparse.ArgumentParser(
        description="Find similar products, analyze them, or rerun Report Agent from an existing report folder.",
        add_help=True,
    )
    parser.add_argument(
        "--run-mode",
        type=int,
        choices=[0, 1],
        default=RUN_MODE,
        help="运行模式：0=从头开始；1=读取 reports 直接运行 Report Agent 标准链路。",
    )
    parser.add_argument(
        "--report-agent-from-dir",
        default="",
        help="跳过前置搜索/单品分析，直接读取该文件夹下的单品报告并运行 Report Agent 标准链路。",
    )
    parser.add_argument(
        "--report-agent-pattern",
        default=REPORT_AGENT_FROM_DIR_PATTERN,
        help="配合 --report-agent-from-dir 使用的报告文件匹配模式，默认 *.md。",
    )
    parser.add_argument(
        "--report-agent-product-description",
        default=REPORT_AGENT_PRODUCT_DESCRIPTION,
        help="配合 --report-agent-from-dir 使用的原始需求/目标领域。不传则使用位置参数或文件夹名。",
    )
    parser.add_argument(
        "description",
        nargs="*",
        help="产品需求；原有用法保持不变。",
    )
    args = parser.parse_args()
    report_agent_from_dir = str(args.report_agent_from_dir or "").strip()
    if int(args.run_mode) == 1 and not report_agent_from_dir:
        report_agent_from_dir = REPORT_AGENT_FROM_DIR or "reports"
    return RuntimeArgs(
        description_parts=list(args.description or []),
        run_mode=int(args.run_mode),
        report_agent_from_dir=report_agent_from_dir,
        report_agent_pattern=str(args.report_agent_pattern or "*.md").strip() or "*.md",
        report_agent_product_description=str(
            args.report_agent_product_description or ""
        ).strip(),
    )


def provider_name(provider: int) -> str:
    names = {
        0: "豆包/火山 Ark",
        1: "SiliconFlow",
        2: "小米 MiMo",
    }
    return names.get(provider, "未知 provider")


def print_active_provider() -> None:
    provider = active_provider()
    try:
        api_key, base_url, model = provider_llm_config()
    except ValueError:
        api_key, base_url, model = "", "", ""
    print("\n===== LLM API 提供商 =====")
    print(f"provider: {provider} ({provider_name(provider)})")
    print(f"base_url: {base_url or '未配置'}")
    print(f"model: {model or '未配置'}")
    print(f"api_key: {mask_key(api_key) if api_key else '未配置'}")


def search_backend_name() -> str:
    if SEARCH_BACKEND == 0:
        return "博查搜索 + 传统爬虫抓正文"
    if SEARCH_BACKEND == 1:
        return "博查搜索 + Playwright 抓正文"
    if SEARCH_BACKEND == 2:
        return "博查搜索 + Crawl4AI 抓正文"
    return "未知搜索后端"


def print_search_backend() -> None:
    print("\n===== 搜索后端 =====")
    print(f"search_backend: {SEARCH_BACKEND} ({search_backend_name()})")
    print(f"search_api: {SEARCH_SOURCE}")


def active_provider() -> int:
    return LLM_PROVIDER


def provider_llm_config() -> tuple[str, str, str]:
    provider = active_provider()
    if provider == 0:
        return LLM0_API_KEY, LLM0_BASE_URL, LLM0_MODEL
    if provider == 1:
        return (
            os.getenv("LLM1_API_KEY") or LLM_API_KEY,
            os.getenv("LLM1_BASE_URL") or LLM_BASE_URL,
            os.getenv("LLM1_MODEL") or LLM_MODEL,
        )
    if provider == 2:
        return LLM2_API_KEY, LLM2_BASE_URL, LLM2_MODEL
    raise ValueError("LLM_PROVIDER must be 0, 1, or 2")


def read_product_description(description_parts: list[str] | None = None) -> str:
    description = " ".join(description_parts or []).strip()
    if description:
        return description
    return input("请输入产品需求: ").strip()


def read_known_product_param_text() -> tuple[str, str]:
    path_text = os.getenv("KNOWN_PRODUCT_PARAM_TXT", "").strip()
    if not path_text:
        path_text = (
            input("请输入我方产品参数 txt 路径（可直接回车跳过）: ").strip().strip('"')
        )
    if not path_text:
        return "", ""

    path = Path(path_text)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        print(f"[warn] 我方产品参数 txt 不存在，已跳过: {path}")
        return "", ""

    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        print(f"[warn] 我方产品参数 txt 为空，已跳过: {path}")
        return "", ""
    if KNOWN_PRODUCT_PARAM_MAX_CHARS > 0 and len(text) > KNOWN_PRODUCT_PARAM_MAX_CHARS:
        text = text[:KNOWN_PRODUCT_PARAM_MAX_CHARS]
        print(
            f"[warn] 我方产品参数 txt 较长，已截取前 {KNOWN_PRODUCT_PARAM_MAX_CHARS} 字符。"
        )
    return str(path), text


def read_questionnaire_analysis_text() -> tuple[str, str]:
    path_text = os.getenv("QUESTIONNAIRE_ANALYSIS_MD", "").strip()
    if not path_text:
        path_text = (
            input("请输入问卷分析报告 md 路径（可直接回车跳过）: ").strip().strip('"')
        )
    if not path_text:
        return "", ""

    path = Path(path_text)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        print(f"[warn] 问卷分析报告不存在，已跳过: {path}")
        return "", ""

    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if QUESTIONNAIRE_CODE_SUMMARY_MARKER in text:
        text = text.split(QUESTIONNAIRE_CODE_SUMMARY_MARKER, 1)[0].strip()
    if (
        QUESTIONNAIRE_ANALYSIS_MAX_CHARS > 0
        and len(text) > QUESTIONNAIRE_ANALYSIS_MAX_CHARS
    ):
        text = text[:QUESTIONNAIRE_ANALYSIS_MAX_CHARS]
        print(
            f"[warn] 问卷分析正文较长，已截取前 {QUESTIONNAIRE_ANALYSIS_MAX_CHARS} 字符。"
        )
    return str(path), text


def read_optional_known_product_param_text() -> tuple[str, str]:
    path_text = os.getenv("KNOWN_PRODUCT_PARAM_TXT", "").strip()
    if not path_text:
        return "", ""
    path = Path(path_text)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        print(f"[warn] 我方产品参数 txt 不存在，已跳过: {path}")
        return "", ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if KNOWN_PRODUCT_PARAM_MAX_CHARS > 0 and len(text) > KNOWN_PRODUCT_PARAM_MAX_CHARS:
        text = text[:KNOWN_PRODUCT_PARAM_MAX_CHARS]
        print(
            f"[warn] 我方产品参数 txt 较长，已截取前 {KNOWN_PRODUCT_PARAM_MAX_CHARS} 字符。"
        )
    return str(path), text


def read_optional_questionnaire_analysis_text() -> tuple[str, str]:
    path_text = os.getenv("QUESTIONNAIRE_ANALYSIS_MD", "").strip()
    if not path_text:
        return "", ""
    path = Path(path_text)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        print(f"[warn] 问卷分析报告不存在，已跳过: {path}")
        return "", ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if QUESTIONNAIRE_CODE_SUMMARY_MARKER in text:
        text = text.split(QUESTIONNAIRE_CODE_SUMMARY_MARKER, 1)[0].strip()
    if (
        QUESTIONNAIRE_ANALYSIS_MAX_CHARS > 0
        and len(text) > QUESTIONNAIRE_ANALYSIS_MAX_CHARS
    ):
        text = text[:QUESTIONNAIRE_ANALYSIS_MAX_CHARS]
        print(
            f"[warn] 问卷分析正文较长，已截取前 {QUESTIONNAIRE_ANALYSIS_MAX_CHARS} 字符。"
        )
    return str(path), text


def build_comparison_keyword_library(
    product_description: str, known_param_text: str
) -> str:
    if not known_param_text:
        return ""

    api_key, base_url, model = provider_llm_config()
    prompt = f"""
你是竞品调研搜索关键词规划助手。

用户想找的产品/竞品方向:
{product_description}

我方产品参数 txt（注意: 这是用户自己的产品/我方产品参数，不是竞品参数）:
{known_param_text}

任务:
从我方产品参数中提炼“后续竞品调研必须共同对比的参数点”，并为每个参数点生成可用于搜索竞品资料的关键词。

要求:
- 用中文输出。
- 必须把 txt 理解为“我方产品基准参数”，不能当成竞品事实。
- 只提炼和产品定位、价格、套餐、功能、技术能力、部署方式、平台支持、目标用户、限制、合规、安全、集成、售后、生态、使用场景等相关的参数点。
- 如果 txt 里出现定价，就必须生成定价/套餐/收费/免费额度相关关键词。
- 每个参数点给出 2-5 个搜索关键词，关键词要适合拼接到竞品名称后搜索。
- 不要编造 txt 没有暗示的参数点；可以把同义项合并。
- 输出尽量短，后续会作为搜索提示词库使用。

输出格式:
参数点: xxx
搜索关键词: 关键词1, 关键词2, 关键词3
说明: 为什么这个参数点需要对齐竞品比较
""".strip()

    print("\n===== 根据我方产品参数生成搜索关键词库 =====")
    library = chat_content(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            {
                "role": "system",
                "content": "你把我方产品参数提炼成竞品调研的共同对标搜索关键词库。",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1800,
        timeout=FINAL_SUMMARY_TIMEOUT,
    )
    print(library)
    return library.strip()


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\r\n\t]+', "_", name).strip(" ._")
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:80] or "product"


def build_search_config() -> SearchConfig:
    return SearchConfig(
        source=SearchSource(SEARCH_SOURCE),
        bocha_api_key=BOCHA_API_KEY,
        google_api_key=GOOGLE_API_KEY,
        google_cx_id=GOOGLE_CX_ID,
        proxy=HTTP_PROXY or None,
        count=SEARCH_COUNT,
        max_search_results=SEARCH_COUNT,
        crawl_max_chars=2500,
        crawl_min_chars=120,
        crawl_backend=SEARCH_BACKEND,
        timeout=20,
    )


def final_llm_config() -> tuple[str, str, str]:
    provider = active_provider()
    if provider == 0:
        return LLM0_API_KEY, LLM0_BASE_URL, LLM0_MODEL
    if provider == 2:
        return LLM2_API_KEY, LLM2_BASE_URL, LLM2_MODEL
    keys = llm_key_pool()
    return (
        keys[0] if keys else LLM_API_KEY,
        os.getenv("LLM1_BASE_URL") or LLM_BASE_URL,
        os.getenv("LLM1_MODEL") or LLM_MODEL,
    )


def find_product_names(product_description: str) -> tuple[list[str], list[str]]:
    llm_api_key, llm_base_url, llm_model = provider_llm_config()
    config = PositioningProductConfig(
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        search_config=build_search_config(),
        query_count=QUERY_COUNT,
        results_per_query=SEARCH_COUNT,
    )
    result = run_positioning_product_search(product_description, config)
    return result.queries, result.product_names


def parse_selection(selection: str, product_names: list[str]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    if re.search(r"[,，、;\n]", selection):
        parts = re.split(r"[,，、;\n]+", selection.strip())
    else:
        whitespace_parts = selection.strip().split()
        if whitespace_parts and all(part.isdigit() for part in whitespace_parts):
            parts = whitespace_parts
        else:
            parts = [selection.strip()]
    for part in parts:
        if not part:
            continue
        part = part.strip()
        name = ""
        if part.isdigit():
            index = int(part)
            if 1 <= index <= len(product_names):
                name = product_names[index - 1]
            else:
                print(f"[warn] 序号超出范围，已忽略: {part}")
                continue
        else:
            name = part
        if name and name not in seen:
            seen.add(name)
            selected.append(name)
    return selected


def select_product_names(product_names: list[str]) -> list[str]:
    print("\n===== 搜索到的产品 =====")
    if not product_names:
        print("未提取到产品名，可以直接手动输入产品名。")
    for index, name in enumerate(product_names, 1):
        print(f"{index}. {name}")

    if product_names:
        print("\n请输入要分析的产品序号，或直接输入新的产品名。")
        print("多个产品建议用逗号分隔，例如: 1, 3, Cursor, 豆包 MarsCode")
        print(f"直接回车默认选择前 {min(TOP_N, len(product_names))} 个。")
    else:
        print("\n请输入要分析的产品名，多个产品用逗号分隔。")
    while True:
        selection = input("请选择: ").strip()
        if not selection and product_names:
            return product_names[:TOP_N]
        if not selection:
            print("没有输入产品名，请重新输入。")
            continue
        selected = parse_selection(selection, product_names)
        if selected:
            return selected
        print("没有识别到有效选择，请重新输入。")


def report_path_for(product_name: str, index: int, timestamp: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return REPORT_DIR / f"{timestamp}_{index}_{safe_filename(product_name)}.md"


def done_path_for(product_name: str, index: int, timestamp: str) -> Path:
    return report_path_for(product_name, index, timestamp).with_suffix(".done")


def analyze_product(
    product_name: str,
    index: int,
    timestamp: str,
    llm_key: str | None,
    comparison_keyword_library: str,
) -> Path:
    report_path = report_path_for(product_name, index, timestamp)
    done_path = done_path_for(product_name, index, timestamp)
    if done_path.exists():
        done_path.unlink()
    env = os.environ.copy()
    provider = active_provider()
    env.update(
        {
            "QUESTION": product_name,
            "LLM_PROVIDER": str(provider),
            "LLM0_API_KEY": env.get("LLM0_API_KEY") or LLM0_API_KEY,
            "LLM0_BASE_URL": env.get("LLM0_BASE_URL") or LLM0_BASE_URL,
            "LLM0_MODEL": env.get("LLM0_MODEL") or LLM0_MODEL,
            "LLM1_BASE_URL": env.get("LLM1_BASE_URL") or LLM_BASE_URL,
            "LLM1_MODEL": env.get("LLM1_MODEL") or LLM_MODEL,
            "LLM2_API_KEY": env.get("LLM2_API_KEY") or LLM2_API_KEY,
            "LLM2_BASE_URL": env.get("LLM2_BASE_URL") or LLM2_BASE_URL,
            "LLM2_MODEL": env.get("LLM2_MODEL") or LLM2_MODEL,
            "BOCHA_API_KEY": env.get("BOCHA_API_KEY") or BOCHA_API_KEY,
            "SEARCH_BACKEND": str(SEARCH_BACKEND),
            "HTTP_PROXY": env.get("HTTP_PROXY") or HTTP_PROXY,
            "PYTHONUNBUFFERED": "1",
        }
    )
    if comparison_keyword_library:
        env["COMPARISON_KEYWORD_LIBRARY"] = comparison_keyword_library
    if provider == 1 and llm_key:
        env["LLM1_API_KEY"] = llm_key
        env["LLM_API_KEY"] = llm_key

    creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    subprocess.Popen(
        [
            sys.executable,
            "-u",
            str(ANALYZE_WORKER),
            "--product",
            product_name,
            "--report",
            str(report_path),
            "--done",
            str(done_path),
        ],
        cwd=str(ROOT),
        env=env,
        creationflags=creationflags,
    )
    return report_path


def wait_for_reports(targets: list[str], timestamp: str) -> list[Path]:
    expected = [
        (
            name,
            report_path_for(name, index, timestamp),
            done_path_for(name, index, timestamp),
        )
        for index, name in enumerate(targets, 1)
    ]
    deadline = time.time() + ANALYZE_TIMEOUT
    pending = set(name for name, _, _ in expected)
    progress = (
        tqdm(
            total=len(expected),
            desc="等待产品报告",
            unit="个",
            dynamic_ncols=True,
            file=sys.stdout,
        )
        if tqdm
        else None
    )
    try:
        while pending and time.time() < deadline:
            for name, report_path, done_path in expected:
                if name in pending and done_path.exists() and report_path.exists():
                    pending.remove(name)
                    if progress:
                        progress.update(1)
                        progress.set_postfix_str(name[:24])
                        progress.write(f"[finished] {name} -> {report_path}")
                    else:
                        print(f"[finished] {name} -> {report_path}")
            if pending:
                if progress:
                    progress.set_postfix_str(f"剩余 {len(pending)} 个")
                time.sleep(2)
    finally:
        if progress:
            progress.close()
    if pending:
        print(f"[warn] 等待超时，未完成: {', '.join(sorted(pending))}")
    return [
        report_path for name, report_path, done_path in expected if report_path.exists()
    ]


def add_product_prefix(text: str, product_name: str) -> str:
    return REFERENCE_POINT_RE.sub(
        lambda match: f"[{product_name}][参考点{match.group(1)}]",
        text,
    )


def split_report_sections(report_text: str) -> tuple[str, str]:
    if FINAL_SUMMARY_MARKER not in report_text:
        return report_text, ""
    before, after = report_text.split(FINAL_SUMMARY_MARKER, 1)
    return before.strip(), after.strip()


def extract_reference_points(before_final_summary: str) -> str:
    if REFERENCE_EVIDENCE_MARKER in before_final_summary:
        return before_final_summary.split(REFERENCE_EVIDENCE_MARKER, 1)[1].strip()
    match = re.search(r"\[参考点\d+\]", before_final_summary)
    if match:
        return before_final_summary[match.start() :].strip()
    return before_final_summary.strip()


def read_report_for_summary(path: Path) -> ReportInput:
    text = path.read_text(encoding="utf-8", errors="replace")
    first_line = text.splitlines()[0] if text.splitlines() else ""
    product_name = first_line[2:].strip() if first_line.startswith("# ") else path.stem
    before_final_summary, final_summary = split_report_sections(text)
    reference_points = extract_reference_points(before_final_summary)
    return ReportInput(
        product_name=product_name,
        final_summary=add_product_prefix(final_summary, product_name),
        reference_points=add_product_prefix(reference_points, product_name),
        path=path,
    )


def should_skip_report_agent_source(path: Path) -> bool:
    name = path.name.upper()
    skip_markers = [
        "REPORT_AGENT",
        "FINAL_COMPARISON",
        "STRUCTURED_ANALYSIS",
        "PACKAGE",
    ]
    return any(marker in name for marker in skip_markers)


def read_report_inputs_from_dir(folder: Path, pattern: str = "*.md") -> list[ReportInput]:
    if not folder.exists():
        raise FileNotFoundError(f"报告文件夹不存在: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"不是文件夹: {folder}")

    paths = [
        path
        for path in sorted(folder.glob(pattern))
        if path.is_file() and not should_skip_report_agent_source(path)
    ]
    if not paths:
        raise RuntimeError(f"文件夹中没有匹配的单品报告: {folder} pattern={pattern}")

    items: list[ReportInput] = []
    skipped: list[Path] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        if FINAL_SUMMARY_MARKER not in text and REFERENCE_EVIDENCE_MARKER not in text:
            skipped.append(path)
            continue
        items.append(read_report_for_summary(path))

    if not items:
        skipped_names = ", ".join(path.name for path in skipped[:8])
        raise RuntimeError(
            "没有可用于 Report Agent 的单品报告；需要包含 "
            f"{FINAL_SUMMARY_MARKER} 或 {REFERENCE_EVIDENCE_MARKER}。已跳过: {skipped_names}"
        )
    if skipped:
        print(
            "[report-agent] 已跳过非单品报告: "
            + ", ".join(path.name for path in skipped[:8])
            + (" ..." if len(skipped) > 8 else "")
        )
    return items


def build_report_agent_config() -> WritingAgentConfig:
    api_key, base_url, model = final_llm_config()
    return WritingAgentConfig(
        llm_api_key=api_key,
        llm_base_url=base_url,
        llm_model=model,
        use_llm=bool(api_key and base_url and model),
        temperature=0.2,
        max_tokens=REPORT_AGENT_MAX_TOKENS,
        llm_timeout=REPORT_AGENT_LLM_TIMEOUT,
        llm_batch_workers=REPORT_AGENT_BATCH_WORKERS,
        table_gap_search_enabled=REPORT_AGENT_TABLE_GAP_SEARCH,
        table_gap_search_max_queries=REPORT_AGENT_TABLE_GAP_SEARCH_MAX_QUERIES,
        table_gap_search_all_pending=REPORT_AGENT_TABLE_GAP_SEARCH_ALL_PENDING,
        table_gap_search_results_per_query=REPORT_AGENT_TABLE_GAP_SEARCH_RESULTS,
        table_gap_search_crawl_max_chars=2500,
        table_gap_search_max_rounds=REPORT_AGENT_TABLE_GAP_SEARCH_MAX_ROUNDS,
        table_gap_search_workers=REPORT_AGENT_TABLE_GAP_SEARCH_WORKERS,
        search_source=SEARCH_SOURCE,
        search_bocha_api_key=BOCHA_API_KEY,
        search_google_api_key=GOOGLE_API_KEY,
        search_google_cx_id=GOOGLE_CX_ID,
        search_proxy=HTTP_PROXY,
        search_backend=SEARCH_BACKEND,
        max_source_chars=REPORT_AGENT_SOURCE_MAX_CHARS,
        max_prompt_sources=REPORT_AGENT_MAX_PROMPT_SOURCES,
        max_evidence_cards=REPORT_AGENT_MAX_EVIDENCE_CARDS,
        evidence_structurer_mode=REPORT_AGENT_EVIDENCE_MODE,
        print_comparison_tables=REPORT_AGENT_PRINT_TABLES,
        export_comparison_tables=REPORT_AGENT_EXPORT_TABLES,
        table_export_dir=REPORT_AGENT_TABLE_EXPORT_DIR,
        verbose=True,
        progress_printer=print,
    )


def build_report_agent_sources(
    items: list[ReportInput],
    product_description: str,
    comparison_keyword_library: str,
    questionnaire_analysis_text: str,
    questionnaire_analysis_path: str,
) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for item in items:
        content = "\n\n".join(
            [
                f"产品名称: {item.product_name}",
                "===== 单品 FINAL SUMMARY =====",
                item.final_summary.strip() or "无",
                "===== 单品参考点 =====",
                item.reference_points.strip() or "无",
            ]
        )
        sources.append(
            {
                "title": f"{item.product_name} 单品调研报告",
                "url": str(item.path),
                "snippet": item.final_summary,
                "content": content,
                "source": "single_product_report",
                "content_source": "run_similar_product_reports_with_new_analyze",
            }
        )

    context_parts = [
        f"用户原始需求: {product_description}",
        "===== 我方产品参数关键词库 =====",
        "用途: 这是用户自己的产品/我方产品参数提炼出的对标维度，不是竞品参数，也不是竞品事实。后续报告需要围绕这些参数检查各竞品是否有证据支撑，缺失时明确写未找到明确证据。",
        comparison_keyword_library.strip() or "无",
        "===== 问卷分析补充背景 =====",
        f"来源: {questionnaire_analysis_path}" if questionnaire_analysis_path else "来源: 无",
        "用途: 这是需求侧、用户侧、采购侧和风险侧的补充背景。可用于校准用户画像、场景优先级、价格敏感度、替换意愿、采购顾虑和功能偏好，但不能当作某个竞品的官方事实。",
        questionnaire_analysis_text.strip() or "无",
    ]
    sources.append(
        {
            "title": "用户需求、参数词库与问卷补充背景",
            "url": questionnaire_analysis_path or "",
            "snippet": product_description,
            "content": "\n\n".join(context_parts),
            "source": "workflow_context",
            "content_source": "known_params_and_questionnaire",
        }
    )
    return sources


def generate_report_agent_analysis(
    items: list[ReportInput],
    product_description: str,
    timestamp: str,
    comparison_keyword_library: str,
    questionnaire_analysis_text: str,
    questionnaire_analysis_path: str,
) -> tuple[Path, Path]:
    config = build_report_agent_config()
    product_names = [item.product_name for item in items]
    analysis_goal = (
        "基于上游单品调研报告、参考点、我方产品参数词库和问卷分析，"
        "生成面向产品经理的竞品横向分析报告，覆盖证据卡、PM洞察、竞品画像、"
        "能力对比、SWOT 和产品策略建议。我方产品参数词库来自用户自己的产品，"
        "不是竞品事实；必须优先围绕这些我方参数做共同维度对齐，"
        "并使用问卷分析校准目标用户、使用场景、价格敏感度、替换意愿、采购顾虑和风险判断。"
    )
    target_domain = f"{product_description} 竞品横向分析"
    sources = build_report_agent_sources(
        items,
        product_description,
        comparison_keyword_library,
        questionnaire_analysis_text,
        questionnaire_analysis_path,
    )

    print("\n===== Report Agent 标准分析链路 =====")
    print(
        "将调用: evidence_structurer -> insight_extractor -> comparison_builder "
        "-> swot_generator -> strategy_recommender -> report_composer"
    )
    package = run_writing_agent(
        sources,
        config=config,
        task_id=f"{timestamp}_report_agent_analysis",
        analysis_goal=analysis_goal,
        target_domain=target_domain,
        competitors=product_names,
    )

    md_path = REPORT_DIR / f"{timestamp}_REPORT_AGENT_ANALYSIS.md"
    json_path = REPORT_DIR / f"{timestamp}_REPORT_AGENT_PACKAGE.json"
    md_output = "\n\n".join(
        [
            "# Report Agent 标准竞品分析报告",
            "",
            f"原始需求: {product_description}",
            f"参与产品: {'、'.join(product_names)}",
            "",
            package.report_markdown,
            "",
            "===== STRUCTURED ANALYSIS JSON =====",
            package.to_json(),
            "",
        ]
    )
    md_path.write_text(md_output, encoding="utf-8")
    json_path.write_text(package.to_json(), encoding="utf-8")
    return md_path, json_path


def run_report_agent_from_dir(runtime_args: RuntimeArgs) -> tuple[Path, Path]:
    folder = Path(runtime_args.report_agent_from_dir)
    if not folder.is_absolute():
        folder = ROOT / folder
    items = read_report_inputs_from_dir(folder, runtime_args.report_agent_pattern)
    product_description = (
        runtime_args.report_agent_product_description
        or " ".join(runtime_args.description_parts).strip()
        or folder.name
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("\n===== 跳过前置步骤，直接读取文件夹运行 Report Agent =====")
    print(f"source_dir: {folder}")
    print(f"pattern: {runtime_args.report_agent_pattern}")
    print(f"原始需求/目标领域: {product_description}")
    print("读取到的单品报告:")
    for index, item in enumerate(items, 1):
        print(f"{index}. {item.product_name} -> {item.path}")

    known_param_path, known_param_text = read_optional_known_product_param_text()
    comparison_keyword_library = ""
    if known_param_text:
        comparison_keyword_library = build_comparison_keyword_library(
            product_description,
            known_param_text,
        )
        print(f"\n已读取我方产品参数: {known_param_path}")

    questionnaire_analysis_path, questionnaire_analysis_text = (
        read_optional_questionnaire_analysis_text()
    )
    if questionnaire_analysis_path:
        print(f"\n已读取问卷分析报告: {questionnaire_analysis_path}")

    md_path, json_path = generate_report_agent_analysis(
        items,
        product_description,
        timestamp,
        comparison_keyword_library,
        questionnaire_analysis_text,
        questionnaire_analysis_path,
    )
    print(f"[report-agent] Markdown 已保存: {md_path}")
    print(f"[report-agent] Package JSON 已保存: {json_path}")
    return md_path, json_path


def summarize_all_reports(
    report_paths: list[Path],
    product_description: str,
    timestamp: str,
    comparison_keyword_library: str = "",
    questionnaire_analysis_text: str = "",
    questionnaire_analysis_path: str = "",
) -> Path:
    items = [read_report_for_summary(path) for path in report_paths]
    report_agent_md_path: Path | None = None
    report_agent_json_path: Path | None = None
    report_agent_markdown = ""
    if REPORT_AGENT_ENABLED:
        try:
            report_agent_md_path, report_agent_json_path = generate_report_agent_analysis(
                items,
                product_description,
                timestamp,
                comparison_keyword_library,
                questionnaire_analysis_text,
                questionnaire_analysis_path,
            )
            report_agent_markdown = report_agent_md_path.read_text(
                encoding="utf-8", errors="replace"
            )
            print(f"[report-agent] Markdown 已保存: {report_agent_md_path}")
            print(f"[report-agent] Package JSON 已保存: {report_agent_json_path}")
        except Exception as exc:
            print(f"[warn] Report Agent 标准分析链路失败，继续生成原大总结: {exc}")

    summaries = "\n\n".join(
        f"## {item.product_name}\n{item.final_summary}" for item in items
    )
    references = "\n\n".join(
        f"## {item.product_name}\n{item.reference_points}" for item in items
    )
    product_names = "、".join(item.product_name for item in items)
    prompt = f"""
你是产品策略分析师。请根据单品报告的 FINAL SUMMARY 正文，并结合可选的问卷分析补充背景，写一份中文横向对比总结。

用户原始需求:
{product_description}

我方产品参数关键词库（来自用户自己的产品，不是竞品参数）:
{comparison_keyword_library.strip() or "无"}

参与对比的产品:
{product_names}

问卷分析补充背景:
{questionnaire_analysis_text.strip() or "无"}

单品 FINAL SUMMARY:
{summaries}

输出要求:
- 用中文输出。
- 分析每个产品的定位、核心能力、优势、短板、适合用户和不适合场景。
- 尽量保留后续报告分析需要的信息：目标用户、核心场景、产品形态/入口、商业模式/定价、关键能力、限制或风险、用户反馈和证据引用。
- 如果“我方产品参数关键词库”不为空，请优先按这些共同参数点做横向对比；这些参数来自我方产品，不是竞品事实，缺失证据的竞品参数点要说明未找到明确证据。
- 如果“问卷分析补充背景”不为空，请结合其中的用户画像、场景、价格敏感度、替换意愿、采购决策、风险顾虑，生成更多维度、更丰富的横向分析。
- 给出横向对比和选择建议。
- 单品事实和引用必须来自单品 FINAL SUMMARY；问卷分析只能作为需求侧、用户侧、决策侧补充，不要把问卷结论当成某个产品的官方事实。
- 保留原文里已有的引用标记，例如 [产品名][参考点15]。
- 不要编造单品 FINAL SUMMARY 里没有的信息。
""".strip()

    print("\n===== 生成所选产品大总结 =====")
    api_key, base_url, model = final_llm_config()
    messages = [
        {
            "role": "system",
            "content": "你把多份产品调研总结合并成一份有引用标记的中文横向对比报告。",
        },
        {"role": "user", "content": prompt},
    ]
    chunks = []
    try:
        for chunk in stream_chat_content(
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=4000,
            timeout=FINAL_SUMMARY_TIMEOUT,
        ):
            chunks.append(chunk)
            print(chunk, end="", flush=True)
        print()
        final_summary = "".join(chunks)
    except Exception as exc:
        print(f"[warn] 流式大总结失败，改用普通请求: {exc}")
        final_summary = chat_content(
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=4000,
            timeout=FINAL_SUMMARY_TIMEOUT,
        )

    output_path = REPORT_DIR / f"{timestamp}_FINAL_COMPARISON.md"
    output = "\n\n".join(
        [
            "# 所选产品横向对比报告",
            "",
            f"原始需求: {product_description}",
            "",
            "===== 我方产品参数关键词库 =====",
            comparison_keyword_library.strip() or "无",
            "",
            "===== 问卷分析补充背景 =====",
            f"来源: {questionnaire_analysis_path}"
            if questionnaire_analysis_path
            else "来源: 无",
            questionnaire_analysis_text.strip() or "无",
            "",
            "===== FINAL COMPARISON SUMMARY =====",
            final_summary,
            "",
            "===== REPORT AGENT STANDARD ANALYSIS =====",
            (
                f"Markdown: {report_agent_md_path}\n"
                f"Package JSON: {report_agent_json_path}\n\n"
                f"{report_agent_markdown}"
            )
            if report_agent_markdown
            else "未生成或已禁用。设置 REPORT_AGENT_ENABLED=1 可启用。",
            "",
            "===== 带产品名前缀的参考点 =====",
            references,
            "",
            "===== SOURCE FINAL SUMMARIES =====",
            summaries,
            "",
        ]
    )
    output_path.write_text(output, encoding="utf-8")
    return output_path


def main() -> None:
    runtime_args = parse_runtime_args()
    print("\n===== 运行模式 =====")
    print(
        "run_mode: "
        f"{runtime_args.run_mode} "
        f"({'从头开始' if runtime_args.run_mode == 0 else '读取 reports 进入 Report Agent 标准链路'})"
    )
    print_active_provider()
    print_search_backend()
    provider = active_provider()
    keys = llm_key_pool() if provider == 1 else []
    if provider == 1 and not keys:
        raise RuntimeError(
            "Please set LLM_API_KEYS, LLM_API_KEY, or ARK_API_KEY for provider 1."
        )
    if provider in {0, 2} and not provider_llm_config()[0]:
        raise RuntimeError(f"Please set an active API key for LLM_PROVIDER={provider}.")
    if provider not in {0, 1, 2}:
        raise RuntimeError("LLM_PROVIDER must be 0, 1, or 2.")

    if runtime_args.report_agent_from_dir:
        if SEARCH_BACKEND not in {0, 1, 2}:
            raise RuntimeError("SEARCH_BACKEND must be 0, 1, or 2.")
        if (
            REPORT_AGENT_TABLE_GAP_SEARCH
            and SearchSource(SEARCH_SOURCE) == SearchSource.BOCHA
            and not BOCHA_API_KEY
        ):
            print(
                "[warn] 未配置 BOCHA_API_KEY，Report Agent 可运行，但表格待搜索回填可能失败。"
            )
        run_report_agent_from_dir(runtime_args)
        return

    if SEARCH_BACKEND not in {0, 1, 2}:
        raise RuntimeError("SEARCH_BACKEND must be 0, 1, or 2.")
    if SearchSource(SEARCH_SOURCE) != SearchSource.BOCHA:
        raise RuntimeError(
            "当前 SEARCH_BACKEND 仅支持博查搜索 API，请设置 SEARCH_SOURCE=bocha。"
        )
    if SearchSource(SEARCH_SOURCE) == SearchSource.BOCHA and not BOCHA_API_KEY:
        raise RuntimeError("当前 SEARCH_SOURCE=bocha，请先填写 BOCHA_API_KEY。")

    product_description = read_product_description(runtime_args.description_parts)
    if not product_description:
        raise RuntimeError("产品需求不能为空。")

    known_param_path, known_param_text = read_known_product_param_text()
    comparison_keyword_library = build_comparison_keyword_library(
        product_description,
        known_param_text,
    )
    if known_param_path:
        print(f"\n已读取我方产品参数: {known_param_path}")

    questionnaire_analysis_path, questionnaire_analysis_text = (
        read_questionnaire_analysis_text()
    )
    if questionnaire_analysis_path:
        print(f"\n已读取问卷分析报告: {questionnaire_analysis_path}")

    queries, product_names = find_product_names(product_description)

    print("\n===== LLM 改写后的搜索词 =====")
    for query in queries:
        print(f"- {query}")

    targets = select_product_names(product_names)
    if not targets:
        return

    print("\n===== 将要分析的产品 =====")
    for index, name in enumerate(targets, 1):
        print(f"{index}. {name}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print("\n===== 启动独立命令行窗口分析 =====")
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(targets)) as executor:
        future_to_name = {
            executor.submit(
                analyze_product,
                name,
                index,
                timestamp,
                keys[(index - 1) % len(keys)] if provider == 1 else None,
                comparison_keyword_library,
            ): name
            for index, name in enumerate(targets, 1)
        }
        for future in concurrent.futures.as_completed(future_to_name):
            name = future_to_name[future]
            try:
                path = future.result()
                if provider == 1:
                    index = targets.index(name) + 1
                    key = keys[(index - 1) % len(keys)]
                    print(
                        f"[started] {name} provider=1 api_key={mask_key(key)} -> {path}"
                    )
                elif provider == 2:
                    print(
                        f"[started] {name} provider=2 Xiaomi MiMo shared config -> {path}"
                    )
                else:
                    print(f"[started] {name} provider=0 doubao shared config -> {path}")
            except Exception as exc:
                print(f"[failed] {name}: {exc}")

    print(
        f"\n{len(targets)} 个分析窗口已经启动。每个窗口会独立显示进度，并把报告写入 reports 目录。"
    )
    print("\n===== 等待所选产品分析报告完成 =====")
    report_paths = wait_for_reports(targets, timestamp)
    if len(report_paths) < len(targets):
        print("[warn] 报告数量不足，跳过总总结。")
        return
    final_path = summarize_all_reports(
        report_paths,
        product_description,
        timestamp,
        comparison_keyword_library,
        questionnaire_analysis_text,
        questionnaire_analysis_path,
    )
    print(f"\n总总结已保存: {final_path}")


if __name__ == "__main__":
    main()

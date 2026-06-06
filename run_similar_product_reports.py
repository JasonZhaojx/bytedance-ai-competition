"""Find similar products, analyze selected products in parallel, and save reports."""

from __future__ import annotations

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

from extracted_core.positioning_product_workflow import (  # noqa: E402
    PositioningProductConfig,
    run_positioning_product_search,
)
from extracted_core.search import SearchConfig, SearchSource  # noqa: E402
from extracted_core.llm_client import chat_content, stream_chat_content  # noqa: E402

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


# 0 = 豆包/火山 Ark, 1 = SiliconFlow, 2 = 小米 MiMo
LLM_PROVIDER = 0
LLM_PROVIDER = int(os.getenv("LLM_PROVIDER", str(LLM_PROVIDER)))

LLM0_API_KEY = os.getenv("LLM0_API_KEY") or os.getenv("ARK_API_KEY") or ""
LLM0_BASE_URL = os.getenv("LLM0_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
LLM0_MODEL = os.getenv("LLM0_MODEL", "ep-20260514111325-xjmj7")

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_KEYS = os.getenv("LLM_API_KEYS", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1/chat/completions")
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
SEARCH_BACKEND = 2
SEARCH_BACKEND = int(os.getenv("SEARCH_BACKEND", str(SEARCH_BACKEND)))

QUERY_COUNT = int(os.getenv("QUERY_COUNT", "3"))
SEARCH_COUNT = int(os.getenv("SEARCH_COUNT", "3"))
TOP_N = int(os.getenv("TOP_N", "5"))
ANALYZE_TIMEOUT = int(os.getenv("ANALYZE_TIMEOUT", "1200"))
FINAL_SUMMARY_TIMEOUT = int(os.getenv("FINAL_SUMMARY_TIMEOUT", "900"))

FINAL_SUMMARY_MARKER = "===== FINAL SUMMARY ====="
REFERENCE_EVIDENCE_MARKER = "===== REFERENCE EVIDENCE ====="
REFERENCE_POINT_RE = re.compile(r"(?<!\])\[参考点(\d+)\]")
KNOWN_PRODUCT_PARAM_MAX_CHARS = int(os.getenv("KNOWN_PRODUCT_PARAM_MAX_CHARS", "12000"))
QUESTIONNAIRE_ANALYSIS_MAX_CHARS = int(os.getenv("QUESTIONNAIRE_ANALYSIS_MAX_CHARS", "16000"))
QUESTIONNAIRE_CODE_SUMMARY_MARKER = "===== CODE SUMMARY JSON ====="


@dataclass
class ReportInput:
    product_name: str
    final_summary: str
    reference_points: str
    path: Path


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


def read_product_description() -> str:
    description = " ".join(sys.argv[1:]).strip()
    if description:
        return description
    return input("请输入产品需求: ").strip()


def read_known_product_param_text() -> tuple[str, str]:
    path_text = os.getenv("KNOWN_PRODUCT_PARAM_TXT", "").strip()
    if not path_text:
        path_text = input("请输入已知产品参数 txt 路径（可直接回车跳过）: ").strip().strip('"')
    if not path_text:
        return "", ""

    path = Path(path_text)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        print(f"[warn] 已知产品参数 txt 不存在，已跳过: {path}")
        return "", ""

    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        print(f"[warn] 已知产品参数 txt 为空，已跳过: {path}")
        return "", ""
    if len(text) > KNOWN_PRODUCT_PARAM_MAX_CHARS:
        text = text[:KNOWN_PRODUCT_PARAM_MAX_CHARS]
        print(f"[warn] 已知产品参数 txt 较长，已截取前 {KNOWN_PRODUCT_PARAM_MAX_CHARS} 字符。")
    return str(path), text


def read_questionnaire_analysis_text() -> tuple[str, str]:
    path_text = os.getenv("QUESTIONNAIRE_ANALYSIS_MD", "").strip()
    if not path_text:
        path_text = input("请输入问卷分析报告 md 路径（可直接回车跳过）: ").strip().strip('"')
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
    if len(text) > QUESTIONNAIRE_ANALYSIS_MAX_CHARS:
        text = text[:QUESTIONNAIRE_ANALYSIS_MAX_CHARS]
        print(f"[warn] 问卷分析正文较长，已截取前 {QUESTIONNAIRE_ANALYSIS_MAX_CHARS} 字符。")
    return str(path), text


def build_comparison_keyword_library(product_description: str, known_param_text: str) -> str:
    if not known_param_text:
        return ""

    api_key, base_url, model = provider_llm_config()
    prompt = f"""
你是竞品调研搜索关键词规划助手。

用户想找的产品/竞品方向:
{product_description}

已知产品参数 txt:
{known_param_text}

任务:
从已知产品参数中提炼“后续竞品调研必须共同对比的参数点”，并为每个参数点生成可用于搜索竞品资料的关键词。

要求:
- 用中文输出。
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

    print("\n===== 根据已知产品参数生成搜索关键词库 =====")
    library = chat_content(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            {"role": "system", "content": "你把已知产品参数提炼成竞品调研的共同搜索关键词库。"},
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


def report_subject_from_description(product_description: str) -> str:
    text = re.sub(r"\s+", " ", str(product_description or "")).strip()
    text = text.splitlines()[0].strip() if text else ""
    text = re.sub(r"^(?:请|帮我|请帮我|麻烦|需要|生成|做一份|做|分析|关于)+", "", text).strip()
    text = re.sub(
        r"(?:的)?(?:竞品分析报告|竞品对比报告|竞品分析|竞品对比|类似产品横向对比报告|横向对比报告|横向对比|类似产品|对比报告|分析报告|报告|推荐)$",
        "",
        text,
    ).strip(" ，,。；;：:")
    return text[:42].strip() or "所选产品"


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
        (name, report_path_for(name, index, timestamp), done_path_for(name, index, timestamp))
        for index, name in enumerate(targets, 1)
    ]
    deadline = time.time() + ANALYZE_TIMEOUT
    pending = set(name for name, _, _ in expected)
    progress = tqdm(
        total=len(expected),
        desc="等待产品报告",
        unit="个",
        dynamic_ncols=True,
        file=sys.stdout,
    ) if tqdm else None
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
    return [report_path for name, report_path, done_path in expected if report_path.exists()]


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
        return before_final_summary[match.start():].strip()
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


def summarize_all_reports(
    report_paths: list[Path],
    product_description: str,
    timestamp: str,
    comparison_keyword_library: str = "",
    questionnaire_analysis_text: str = "",
    questionnaire_analysis_path: str = "",
) -> Path:
    items = [read_report_for_summary(path) for path in report_paths]
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

已知产品参数关键词库:
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
- 如果“已知产品参数关键词库”不为空，请优先按这些共同参数点做横向对比；缺失证据的参数点要说明未找到明确证据。
- 如果“问卷分析补充背景”不为空，请结合其中的用户画像、场景、价格敏感度、替换意愿、采购决策、风险顾虑，生成更多维度、更丰富的横向分析。
- 必须输出一个“详细 Issue 清单”章节，学习单品报告前面分块阅读和参考点的写法，把每个问题拆成：Issue、影响对象、证据/来源参考点、风险等级、为什么重要、建议修正或运营动作。
- Issue 不要只写笼统短句；如果来自资料缺失，请明确写“缺少哪类证据”和“下一步应该补爬/补访谈什么”。
- 必须输出一个“业务闭环指标”章节，至少覆盖效率（节省人工阅读/搜索时间的估计口径）、覆盖度（参考点/来源/产品维度）、一致性（结构化字段和质检问题）、人工修正率（哪些结论需要人工确认）。
- 给出横向对比和选择建议。
- 单品事实和引用必须来自单品 FINAL SUMMARY；问卷分析只能作为需求侧、用户侧、决策侧补充，不要把问卷结论当成某个产品的官方事实。
- 保留原文里已有的引用标记，例如 [产品名][参考点15]。
- 不要编造单品 FINAL SUMMARY 里没有的信息。
""".strip()

    print("\n===== 生成所选产品大总结 =====")
    api_key, base_url, model = final_llm_config()
    messages = [
        {"role": "system", "content": "你把多份产品调研总结合并成一份有引用标记的中文横向对比报告。"},
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
    report_subject = report_subject_from_description(product_description)
    output = "\n\n".join(
        [
            f"# {report_subject}类似产品横向对比报告",
            "",
            f"原始需求: {product_description}",
            "",
            "===== 已知产品参数关键词库 =====",
            comparison_keyword_library.strip() or "无",
            "",
            "===== 问卷分析补充背景 =====",
            f"来源: {questionnaire_analysis_path}" if questionnaire_analysis_path else "来源: 无",
            questionnaire_analysis_text.strip() or "无",
            "",
            "===== FINAL COMPARISON SUMMARY =====",
            final_summary,
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
    print_active_provider()
    print_search_backend()
    provider = active_provider()
    keys = llm_key_pool() if provider == 1 else []
    if provider == 1 and not keys:
        raise RuntimeError("Please set LLM_API_KEYS, LLM_API_KEY, or ARK_API_KEY for provider 1.")
    if provider in {0, 2} and not provider_llm_config()[0]:
        raise RuntimeError(f"Please set an active API key for LLM_PROVIDER={provider}.")
    if provider not in {0, 1, 2}:
        raise RuntimeError("LLM_PROVIDER must be 0, 1, or 2.")
    if SEARCH_BACKEND not in {0, 1, 2}:
        raise RuntimeError("SEARCH_BACKEND must be 0, 1, or 2.")
    if SearchSource(SEARCH_SOURCE) != SearchSource.BOCHA:
        raise RuntimeError("当前 SEARCH_BACKEND 仅支持博查搜索 API，请设置 SEARCH_SOURCE=bocha。")
    if SearchSource(SEARCH_SOURCE) == SearchSource.BOCHA and not BOCHA_API_KEY:
        raise RuntimeError("当前 SEARCH_SOURCE=bocha，请先填写 BOCHA_API_KEY。")

    product_description = read_product_description()
    if not product_description:
        raise RuntimeError("产品需求不能为空。")

    known_param_path, known_param_text = read_known_product_param_text()
    comparison_keyword_library = build_comparison_keyword_library(
        product_description,
        known_param_text,
    )
    if known_param_path:
        print(f"\n已读取已知产品参数: {known_param_path}")

    questionnaire_analysis_path, questionnaire_analysis_text = read_questionnaire_analysis_text()
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
                    print(f"[started] {name} provider=1 api_key={mask_key(key)} -> {path}")
                elif provider == 2:
                    print(f"[started] {name} provider=2 Xiaomi MiMo shared config -> {path}")
                else:
                    print(f"[started] {name} provider=0 doubao shared config -> {path}")
            except Exception as exc:
                print(f"[failed] {name}: {exc}")

    print(f"\n{len(targets)} 个分析窗口已经启动。每个窗口会独立显示进度，并把报告写入 reports 目录。")
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

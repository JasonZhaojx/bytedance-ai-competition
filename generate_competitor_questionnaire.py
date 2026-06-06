"""Generate a JSONL survey questionnaire from competitor search results."""

from __future__ import annotations

import json
import os
import re
import csv
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "questionnaires"

sys.path.insert(0, str(ROOT))

from extracted_core.llm_client import chat_content  # noqa: E402
from extracted_core.positioning_product_workflow import (  # noqa: E402
    PositioningProductConfig,
    PositioningProductResult,
    run_positioning_product_search,
)
from extracted_core.search import SearchConfig, SearchResult, SearchSource  # noqa: E402


# 0 = 豆包/火山 Ark, 1 = SiliconFlow, 2 = 小米 MiMo
LLM_PROVIDER = 0
LLM_PROVIDER = int(os.getenv("LLM_PROVIDER", str(LLM_PROVIDER)))

LLM0_API_KEY = os.getenv("LLM0_API_KEY") or os.getenv("ARK_API_KEY") or os.getenv("LLM_API_KEY") or ""
LLM0_BASE_URL = os.getenv("LLM0_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
LLM0_MODEL = os.getenv("LLM0_MODEL", "ep-20260514111325-xjmj7")

LLM1_API_KEY = os.getenv("LLM1_API_KEY") or os.getenv("LLM_API_KEY") or ""
LLM1_BASE_URL = os.getenv("LLM1_BASE_URL", "https://api.siliconflow.cn/v1/chat/completions")
LLM1_MODEL = os.getenv("LLM1_MODEL", "deepseek-ai/DeepSeek-V4-Flash")

LLM2_API_KEY = os.getenv("LLM2_API_KEY") or os.getenv("MIMO_API_KEY") or ""
LLM2_BASE_URL = os.getenv("LLM2_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
LLM2_MODEL = os.getenv("LLM2_MODEL", "Xiaomi MiMo-V2.5-Pro")

SEARCH_SOURCE = os.getenv("SEARCH_SOURCE", "bocha")
BOCHA_API_KEY = os.getenv("BOCHA_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CX_ID = os.getenv("GOOGLE_CX_ID", "")
HTTP_PROXY = os.getenv("HTTP_PROXY", "")

QUERY_COUNT = int(os.getenv("QUERY_COUNT", "3"))
SEARCH_COUNT = int(os.getenv("SEARCH_COUNT", "5"))
COMPETITOR_LIMIT = int(os.getenv("COMPETITOR_LIMIT", "10"))
QUESTION_COUNT = int(os.getenv("QUESTION_COUNT", "20"))
SIMULATED_RESPONSE_COUNT = int(os.getenv("SIMULATED_RESPONSE_COUNT", "25"))
SIMULATION_BATCH_SIZE = int(os.getenv("SIMULATION_BATCH_SIZE", "5"))
MAX_SEARCH_EVIDENCE_CHARS = int(os.getenv("MAX_SEARCH_EVIDENCE_CHARS", "14000"))
OWN_PRODUCT_PARAM_MAX_CHARS = int(os.getenv("OWN_PRODUCT_PARAM_MAX_CHARS", "12000"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "180"))
QUESTIONNAIRE_ANALYSIS_BATCH_SIZE = max(1, int(os.getenv("QUESTIONNAIRE_ANALYSIS_BATCH_SIZE", "50")))
QUESTIONNAIRE_ANALYSIS_MAX_WORKERS = max(1, int(os.getenv("QUESTIONNAIRE_ANALYSIS_MAX_WORKERS", "4")))
QUESTIONNAIRE_ANALYSIS_REDUCE_FAN_IN = max(2, int(os.getenv("QUESTIONNAIRE_ANALYSIS_REDUCE_FAN_IN", "8")))
QUESTIONNAIRE_ANALYSIS_TEXT_MAX_CHARS = max(80, int(os.getenv("QUESTIONNAIRE_ANALYSIS_TEXT_MAX_CHARS", "600")))
QUESTIONNAIRE_ANALYSIS_JSON_MAX_CHARS = max(2000, int(os.getenv("QUESTIONNAIRE_ANALYSIS_JSON_MAX_CHARS", "45000")))
ANALYZE_ONLY = os.getenv("ANALYZE_ONLY", "").strip()


def active_llm_config() -> tuple[str, str, str]:
    if LLM_PROVIDER == 0:
        return LLM0_API_KEY, LLM0_BASE_URL, LLM0_MODEL
    if LLM_PROVIDER == 1:
        return LLM1_API_KEY, LLM1_BASE_URL, LLM1_MODEL
    if LLM_PROVIDER == 2:
        return LLM2_API_KEY, LLM2_BASE_URL, LLM2_MODEL
    raise ValueError("LLM_PROVIDER must be 0, 1, or 2")


def read_product_description() -> str:
    description = " ".join(sys.argv[1:]).strip()
    if description:
        return description
    return input("请输入产品/竞品方向: ").strip()


def read_optional_text_file() -> tuple[str, str]:
    path_text = os.getenv("OWN_PRODUCT_PARAM_TXT", "").strip()
    if not path_text:
        path_text = input("请输入自己产品参数 txt 路径（可直接回车跳过）: ").strip().strip('"')
    if not path_text:
        return "", ""

    path = Path(path_text)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        print(f"[warn] txt 不存在，已跳过: {path}")
        return "", ""

    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) > OWN_PRODUCT_PARAM_MAX_CHARS:
        text = text[:OWN_PRODUCT_PARAM_MAX_CHARS]
        print(f"[warn] txt 较长，已截取前 {OWN_PRODUCT_PARAM_MAX_CHARS} 字符。")
    return str(path), text


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
        timeout=20,
    )


def find_competitors(product_description: str) -> PositioningProductResult:
    api_key, base_url, model = active_llm_config()
    config = PositioningProductConfig(
        llm_api_key=api_key,
        llm_base_url=base_url,
        llm_model=model,
        search_config=build_search_config(),
        query_count=QUERY_COUNT,
        results_per_query=SEARCH_COUNT,
    )
    return run_positioning_product_search(product_description, config)


def format_search_evidence(results: list[SearchResult], max_chars: int) -> str:
    sections = []
    used_chars = 0
    for index, item in enumerate(results, 1):
        text = item.content or item.snippet
        section = "\n".join(
            [
                f"[搜索结果{index}]",
                f"标题: {item.title}",
                f"链接: {item.url}",
                f"正文来源: {item.content_source or '未知'}",
                f"正文: {text}",
            ]
        )
        if max_chars and used_chars + len(section) > max_chars:
            section = section[: max(0, max_chars - used_chars)]
        if not section:
            break
        sections.append(section)
        used_chars += len(section)
        if max_chars and used_chars >= max_chars:
            break
    return "\n\n".join(sections)


def parse_json_array(text: str) -> list[dict[str, Any]]:
    cleaned = text.replace("```json", "").replace("```", "").strip()
    candidates = [cleaned]
    match = re.search(r"\[.*\]", cleaned, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))

    for candidate in list(candidates):
        fixed = re.sub(r",(\s*[\]}])", r"\1", candidate)
        if fixed != candidate:
            candidates.append(fixed)

    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            break
        except json.JSONDecodeError as exc:
            last_error = exc
    else:
        raise last_error or ValueError("LLM did not return valid JSON")

    if not isinstance(data, list):
        raise ValueError("LLM did not return a JSON array")
    return [item for item in data if isinstance(item, dict)]


def normalize_questionnaire_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for index, item in enumerate(items, 1):
        value = dict(item)
        value["id"] = str(value.get("id") or f"Q{index:03d}")
        value["dimension"] = str(value.get("dimension") or "未分类")
        value["question_type"] = str(value.get("question_type") or "text")
        value["question"] = str(value.get("question") or "").strip()
        options = value.get("options")
        value["options"] = options if isinstance(options, list) else []
        value["target_insight"] = str(value.get("target_insight") or "")
        related = value.get("related_competitor_points")
        value["related_competitor_points"] = related if isinstance(related, list) else []
        value["source_basis"] = str(value.get("source_basis") or "")
        if value["question"]:
            normalized.append(value)
    return normalized


def compact_questionnaire(items: list[dict[str, Any]]) -> str:
    compact = []
    for item in items:
        compact.append(
            {
                "id": item["id"],
                "dimension": item["dimension"],
                "question_type": item["question_type"],
                "question": item["question"],
                "options": item.get("options", []),
            }
        )
    return json.dumps(compact, ensure_ascii=False)


def normalize_simulated_responses(items: list[dict[str, Any]], start_index: int) -> list[dict[str, Any]]:
    normalized = []
    for offset, item in enumerate(items):
        value = dict(item)
        respondent_id = str(value.get("respondent_id") or f"R{start_index + offset:03d}")
        profile = value.get("profile")
        if not isinstance(profile, dict):
            profile = {}
        answers = value.get("answers")
        if not isinstance(answers, list):
            answers = []
        clean_answers = []
        for answer in answers:
            if not isinstance(answer, dict):
                continue
            question_id = str(answer.get("question_id") or "")
            if not question_id:
                continue
            clean_answers.append(
                {
                    "question_id": question_id,
                    "answer": answer.get("answer", ""),
                    "reason": str(answer.get("reason") or ""),
                }
            )
        if clean_answers:
            normalized.append(
                {
                    "respondent_id": respondent_id,
                    "profile": profile,
                    "answers": clean_answers,
                }
            )
    return normalized


def generate_questionnaire(
    product_description: str,
    own_param_text: str,
    competitor_names: list[str],
    search_results: list[SearchResult],
) -> list[dict[str, Any]]:
    api_key, base_url, model = active_llm_config()
    competitor_text = "、".join(competitor_names[:COMPETITOR_LIMIT]) or "未抽取到明确竞品名"
    evidence_text = format_search_evidence(search_results, MAX_SEARCH_EVIDENCE_CHARS)
    own_params = own_param_text.strip() or "无"

    prompt = f"""
你是用户研究和产品策略专家。请根据“竞品搜索结果”和“自己产品参数”生成一份调查问卷。

产品/竞品方向:
{product_description}

抽取到的相关产品:
{competitor_text}

自己产品参数:
{own_params}

竞品搜索结果:
{evidence_text}

任务:
生成 {QUESTION_COUNT} 个调查问卷题目，用于验证目标用户对这些相关产品/竞品的认知、使用、购买、替换意愿和关键决策因素。

设计要求:
- 问题必须围绕搜索结果中体现的竞品特点，以及自己产品参数中需要验证的对比点。
- 如果自己产品参数里有定价/套餐/免费额度，必须设计价格敏感度、付费意愿或套餐偏好相关问题。
- 覆盖维度应尽量包括：用户画像、当前使用工具、核心场景、功能重要性、竞品认知、竞品使用体验、痛点、替换门槛、价格/套餐、部署/安全/隐私、购买决策、NPS/推荐意愿。
- 每个题目要能落地给真实用户填写，不要写成研究员内部分析问题。
- 不要编造具体竞品事实；可基于搜索结果总结出的方向来设计问题。
- 输出严格 JSON 数组，不要 Markdown，不要解释。

每个题目对象必须包含这些字段:
- id: 例如 Q001
- dimension: 调研维度
- question_type: single_choice / multiple_choice / scale_1_5 / ranking / text
- question: 问题正文
- options: 选项数组；开放题填 []
- target_insight: 这个问题想验证什么
- related_competitor_points: 这个题目对应的竞品特点或自己产品参数点数组
- source_basis: 这个题目设计依据，简短说明来自哪些搜索发现或参数点

示例:
[
  {{
    "id": "Q001",
    "dimension": "当前工具使用",
    "question_type": "multiple_choice",
    "question": "你目前主要使用哪些同类产品或工具？",
    "options": ["产品A", "产品B", "产品C", "暂未使用", "其他，请注明"],
    "target_insight": "了解目标用户当前竞品使用情况",
    "related_competitor_points": ["竞品使用现状"],
    "source_basis": "来自抽取到的相关产品列表"
  }}
]
""".strip()

    content = chat_content(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            {"role": "system", "content": "你只输出严格 JSON 数组，用于后续保存为 JSONL。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.25,
        max_tokens=5000,
        timeout=LLM_TIMEOUT,
    )
    return normalize_questionnaire_items(parse_json_array(content))


def simulate_response_batch(
    product_description: str,
    own_param_text: str,
    competitor_names: list[str],
    questionnaire_items: list[dict[str, Any]],
    batch_start: int,
    batch_size: int,
) -> list[dict[str, Any]]:
    api_key, base_url, model = active_llm_config()
    competitor_text = "、".join(competitor_names[:COMPETITOR_LIMIT]) or "未抽取到明确竞品名"
    own_params = own_param_text.strip() or "无"
    questionnaire_json = compact_questionnaire(questionnaire_items)
    batch_end = batch_start + batch_size - 1

    prompt = f"""
你是用户研究模拟器。请基于下面的问卷，模拟 {batch_size} 位不同受访者完整填写。

产品/竞品方向:
{product_description}

相关产品/竞品:
{competitor_text}

自己产品参数:
{own_params}

问卷 JSON:
{questionnaire_json}

受访者编号范围:
R{batch_start:03d} 到 R{batch_end:03d}

模拟要求:
- 每个受访者必须有不同画像，覆盖不同经验、预算、行业、岗位、使用频率、当前工具和购买决策角色。
- 每个受访者必须回答问卷中的每一个题目。
- single_choice 只能选择一个选项；multiple_choice 可以选择多个选项；scale_1_5 必须给 1-5 的整数；ranking 给排序数组；text 给自然语言短答。
- 回答要自洽：画像、当前工具、预算、痛点和付费意愿要互相匹配。
- 这是模拟数据，不能写“无法判断”“作为 AI”等措辞。
- 输出严格 JSON 数组，不要 Markdown，不要解释。

每个受访者对象格式:
{{
  "respondent_id": "R001",
  "profile": {{
    "role": "岗位/身份",
    "industry": "行业",
    "company_size": "公司规模",
    "experience_level": "经验水平",
    "budget_sensitivity": "预算敏感度",
    "current_tools": ["当前使用工具"]
  }},
  "answers": [
    {{
      "question_id": "Q001",
      "answer": "作答内容；多选/排序用数组，评分用数字",
      "reason": "简短说明为什么这样回答"
    }}
  ]
}}
""".strip()

    content = chat_content(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            {"role": "system", "content": "你只输出严格 JSON 数组，模拟真实用户填写问卷。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.75,
        max_tokens=8000,
        timeout=LLM_TIMEOUT,
    )
    return normalize_simulated_responses(parse_json_array(content), batch_start)


def simulate_responses(
    product_description: str,
    own_param_text: str,
    competitor_names: list[str],
    questionnaire_items: list[dict[str, Any]],
    total_count: int,
) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    while len(responses) < total_count:
        batch_start = len(responses) + 1
        batch_size = min(SIMULATION_BATCH_SIZE, total_count - len(responses))
        print(f"[simulate] 生成 R{batch_start:03d}-R{batch_start + batch_size - 1:03d}")
        batch = simulate_response_batch(
            product_description=product_description,
            own_param_text=own_param_text,
            competitor_names=competitor_names,
            questionnaire_items=questionnaire_items,
            batch_start=batch_start,
            batch_size=batch_size,
        )
        if not batch:
            raise RuntimeError("模型没有生成有效模拟回答。")
        responses.extend(batch)
    return responses[:total_count]


def write_jsonl(items: list[dict[str, Any]], product_description: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r'[<>:"/\\|?*\r\n\t]+', "_", product_description).strip(" ._")
    safe_name = re.sub(r"\s+", "_", safe_name)[:50] or "questionnaire"
    path = OUTPUT_DIR / f"{timestamp}_{safe_name}.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for item in items:
            file.write(json.dumps(item, ensure_ascii=False) + "\n")
    return path


def output_base_path(product_description: str, suffix: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r'[<>:"/\\|?*\r\n\t]+', "_", product_description).strip(" ._")
    safe_name = re.sub(r"\s+", "_", safe_name)[:50] or "questionnaire"
    return OUTPUT_DIR / f"{timestamp}_{safe_name}_{suffix}"


def write_response_jsonl(responses: list[dict[str, Any]], product_description: str) -> Path:
    path = output_base_path(product_description, "responses.jsonl")
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for item in responses:
            file.write(json.dumps(item, ensure_ascii=False) + "\n")
    return path


def write_response_csv(
    responses: list[dict[str, Any]],
    questionnaire_items: list[dict[str, Any]],
    product_description: str,
) -> Path:
    path = output_base_path(product_description, "responses.csv")
    question_ids = [item["id"] for item in questionnaire_items]
    fieldnames = [
        "respondent_id",
        "role",
        "industry",
        "company_size",
        "experience_level",
        "budget_sensitivity",
        "current_tools",
    ] + question_ids

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for response in responses:
            profile = response.get("profile") if isinstance(response.get("profile"), dict) else {}
            row = {
                "respondent_id": response.get("respondent_id", ""),
                "role": profile.get("role", ""),
                "industry": profile.get("industry", ""),
                "company_size": profile.get("company_size", ""),
                "experience_level": profile.get("experience_level", ""),
                "budget_sensitivity": profile.get("budget_sensitivity", ""),
                "current_tools": "、".join(profile.get("current_tools", []))
                if isinstance(profile.get("current_tools"), list)
                else str(profile.get("current_tools", "")),
            }
            answers = response.get("answers") if isinstance(response.get("answers"), list) else []
            answer_map = {}
            for answer in answers:
                if not isinstance(answer, dict):
                    continue
                value = answer.get("answer", "")
                if isinstance(value, list):
                    value = "、".join(str(item) for item in value)
                answer_map[str(answer.get("question_id") or "")] = value
            for question_id in question_ids:
                row[question_id] = answer_map.get(question_id, "")
            writer.writerow(row)
    return path


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    items = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                items.append(value)
    return items


def answer_to_text(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(item) for item in value)
    return str(value)


def count_values(values: list[str], limit: int = 20) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for value in values:
        value = value.strip()
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return [
        {"value": value, "count": count}
        for value, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


PROFILE_FIELDS = [
    "role",
    "industry",
    "company_size",
    "experience_level",
    "budget_sensitivity",
]


def response_chunks(values: list[Any], batch_size: int) -> list[list[Any]]:
    return [values[index : index + batch_size] for index in range(0, len(values), batch_size)]


def add_count(counts: dict[str, int], value: str) -> None:
    value = value.strip()
    if not value:
        return
    counts[value] = counts.get(value, 0) + 1


def merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for value, count in source.items():
        target[value] = target.get(value, 0) + count


def top_count_values(counts: dict[str, int], limit: int = 20) -> list[dict[str, Any]]:
    return [
        {"value": value, "count": count}
        for value, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def new_question_stat() -> dict[str, Any]:
    return {
        "answer_count": 0,
        "answer_counts": {},
        "sample_reasons": [],
        "numeric_count": 0,
        "numeric_sum": 0.0,
        "numeric_min": None,
        "numeric_max": None,
    }


def add_numeric_value(stat: dict[str, Any], raw_answer: Any) -> None:
    numeric_value = None
    if isinstance(raw_answer, (int, float)):
        numeric_value = float(raw_answer)
    elif isinstance(raw_answer, str) and raw_answer.strip().isdigit():
        numeric_value = float(raw_answer.strip())
    if numeric_value is None:
        return

    stat["numeric_count"] += 1
    stat["numeric_sum"] += numeric_value
    stat["numeric_min"] = numeric_value if stat["numeric_min"] is None else min(stat["numeric_min"], numeric_value)
    stat["numeric_max"] = numeric_value if stat["numeric_max"] is None else max(stat["numeric_max"], numeric_value)


def build_code_analysis_partial(
    question_ids: list[str],
    responses: list[dict[str, Any]],
) -> dict[str, Any]:
    profile_counts: dict[str, dict[str, int]] = {field: {} for field in PROFILE_FIELDS}
    profile_counts["current_tools"] = {}
    question_stats = {question_id: new_question_stat() for question_id in question_ids}

    for response in responses:
        profile = response.get("profile") if isinstance(response.get("profile"), dict) else None
        if profile is not None:
            for field in PROFILE_FIELDS:
                add_count(profile_counts[field], str(profile.get(field, "")))
            current_tools = profile.get("current_tools", [])
            tools = current_tools if isinstance(current_tools, list) else [current_tools]
            for tool in tools:
                add_count(profile_counts["current_tools"], str(tool))

        response_answers = response.get("answers") if isinstance(response.get("answers"), list) else []
        for answer in response_answers:
            if not isinstance(answer, dict):
                continue
            question_id = str(answer.get("question_id"))
            stat = question_stats.get(question_id)
            if stat is None:
                continue

            reason = str(answer.get("reason") or "")
            if reason and len(stat["sample_reasons"]) < 5:
                stat["sample_reasons"].append(reason)

            raw_answer = answer.get("answer", "")
            if isinstance(raw_answer, list):
                stat["answer_count"] += len(raw_answer)
                for item in raw_answer:
                    add_count(stat["answer_counts"], str(item))
            else:
                stat["answer_count"] += 1
                add_count(stat["answer_counts"], str(raw_answer))
                add_numeric_value(stat, raw_answer)

    return {
        "respondent_count": len(responses),
        "profile_counts": profile_counts,
        "question_stats": question_stats,
    }


def merge_question_stat(target: dict[str, Any], source: dict[str, Any]) -> None:
    target["answer_count"] += source["answer_count"]
    merge_counts(target["answer_counts"], source["answer_counts"])
    for reason in source["sample_reasons"]:
        if len(target["sample_reasons"]) >= 5:
            break
        target["sample_reasons"].append(reason)

    if source["numeric_count"]:
        target["numeric_count"] += source["numeric_count"]
        target["numeric_sum"] += source["numeric_sum"]
        target["numeric_min"] = (
            source["numeric_min"]
            if target["numeric_min"] is None
            else min(target["numeric_min"], source["numeric_min"])
        )
        target["numeric_max"] = (
            source["numeric_max"]
            if target["numeric_max"] is None
            else max(target["numeric_max"], source["numeric_max"])
        )


def merge_code_analysis_partials(
    questionnaire_items: list[dict[str, Any]],
    question_map: dict[str, dict[str, Any]],
    partials: list[dict[str, Any]],
) -> dict[str, Any]:
    profile_counts: dict[str, dict[str, int]] = {field: {} for field in PROFILE_FIELDS}
    profile_counts["current_tools"] = {}
    question_stats = {question_id: new_question_stat() for question_id in question_map}
    respondent_count = 0

    for partial in partials:
        respondent_count += partial["respondent_count"]
        for field, counts in partial["profile_counts"].items():
            merge_counts(profile_counts[field], counts)
        for question_id, stat in partial["question_stats"].items():
            merge_question_stat(question_stats[question_id], stat)

    question_summaries = []
    for question_id, question in question_map.items():
        stat = question_stats[question_id]
        summary: dict[str, Any] = {
            "id": question_id,
            "dimension": question.get("dimension", ""),
            "question_type": question.get("question_type", ""),
            "question": question.get("question", ""),
            "answer_count": stat["answer_count"],
            "top_answers": top_count_values(stat["answer_counts"]),
            "sample_reasons": stat["sample_reasons"],
        }
        if stat["numeric_count"]:
            summary["numeric_avg"] = round(stat["numeric_sum"] / stat["numeric_count"], 2)
            summary["numeric_min"] = stat["numeric_min"]
            summary["numeric_max"] = stat["numeric_max"]
        question_summaries.append(summary)

    return {
        "respondent_count": respondent_count,
        "question_count": len(questionnaire_items),
        "profile_summary": {
            field: top_count_values(counts)
            for field, counts in profile_counts.items()
        },
        "question_summaries": question_summaries,
    }


def build_code_analysis(
    questionnaire_items: list[dict[str, Any]],
    responses: list[dict[str, Any]],
) -> dict[str, Any]:
    question_map = {item["id"]: item for item in questionnaire_items}
    question_ids = list(question_map)
    chunks = response_chunks(responses, QUESTIONNAIRE_ANALYSIS_BATCH_SIZE)
    if len(chunks) <= 1:
        partials = [build_code_analysis_partial(question_ids, responses)]
        return merge_code_analysis_partials(questionnaire_items, question_map, partials)

    partials: list[dict[str, Any] | None] = [None] * len(chunks)
    worker_count = min(QUESTIONNAIRE_ANALYSIS_MAX_WORKERS, len(chunks))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(build_code_analysis_partial, question_ids, chunk): index
            for index, chunk in enumerate(chunks)
        }
        for future in as_completed(futures):
            partials[futures[future]] = future.result()

    return merge_code_analysis_partials(
        questionnaire_items,
        question_map,
        [partial for partial in partials if partial is not None],
    )


def truncate_for_llm(text: str, max_chars: int = QUESTIONNAIRE_ANALYSIS_TEXT_MAX_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + f"...[已截断{len(text) - max_chars}字]"


def compact_value_for_llm(value: Any) -> Any:
    if isinstance(value, str):
        return truncate_for_llm(value)
    if isinstance(value, list):
        return [compact_value_for_llm(item) for item in value]
    if isinstance(value, dict):
        return {key: compact_value_for_llm(item) for key, item in value.items()}
    return value


def json_for_llm(value: Any, max_chars: int = QUESTIONNAIRE_ANALYSIS_JSON_MAX_CHARS) -> str:
    text = json.dumps(compact_value_for_llm(value), ensure_ascii=False)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n...[统计 JSON 过长，已截断]"


def questionnaire_for_llm(questionnaire_items: list[dict[str, Any]]) -> str:
    compact = []
    for item in questionnaire_items:
        compact.append(
            {
                "id": item["id"],
                "dimension": truncate_for_llm(str(item.get("dimension", "")), 160),
                "question_type": item.get("question_type", ""),
                "question": truncate_for_llm(str(item.get("question", "")), 300),
                "options": compact_value_for_llm(item.get("options", [])),
            }
        )
    return json_for_llm(compact, max_chars=max(2000, QUESTIONNAIRE_ANALYSIS_JSON_MAX_CHARS // 2))


def build_direct_analysis_prompt(
    product_description: str,
    questionnaire_items: list[dict[str, Any]],
    code_analysis: dict[str, Any],
) -> str:
    compact_questions = questionnaire_for_llm(questionnaire_items)
    analysis_json = json_for_llm(code_analysis)

    return f"""
你是用户研究数据分析师。请根据代码统计结果，写一份中文问卷数据分析报告。

产品/竞品方向:
{product_description}

问卷题目:
{compact_questions}

代码统计结果:
{analysis_json}

报告要求:
- 用中文输出 Markdown。
- 先说明样本规模和模拟数据属性。
- 分析受访者画像分布。
- 分析每个关键维度的结论：工具使用、功能优先级、痛点、价格敏感度、替换意愿、安全/部署/隐私、购买决策。
- 标出最强信号、分歧点、潜在机会点、风险点。
- 给出产品定位、定价/套餐、功能优先级、销售/获客、后续真实调研的建议。
- 不要夸大样本；如果样本是模拟数据，要明确提示不能直接代表真实市场。
""".strip()


def summarize_response_chunk_with_llm(
    api_key: str,
    base_url: str,
    model: str,
    product_description: str,
    questionnaire_items: list[dict[str, Any]],
    chunk: list[dict[str, Any]],
    chunk_index: int,
    total_chunks: int,
) -> str:
    chunk_analysis = build_code_analysis(questionnaire_items, chunk)
    prompt = f"""
你是用户研究数据分析师。下面是第 {chunk_index + 1}/{total_chunks} 批问卷答卷的代码统计结果，每批最多 {QUESTIONNAIRE_ANALYSIS_BATCH_SIZE} 份。
请输出这一批的中文 Markdown 小结，不要写最终总报告。

产品/竞品方向:
{product_description}

问卷题目:
{questionnaire_for_llm(questionnaire_items)}

本批代码统计结果:
{json_for_llm(chunk_analysis)}

小结要求:
- 只基于本批统计，不编造数据。
- 说明本批样本数、受访者画像、主要高频答案。
- 特别概括开放题长文本中反复出现的主题，不要逐条复述长答案。
- 标出本批最强信号、分歧点、机会点和风险点。
- 输出尽量精炼，作为上一层汇总的输入。
""".strip()

    return chat_content(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            {"role": "system", "content": "你根据一批问卷统计结果写中文用户研究批次小结。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1800,
        timeout=LLM_TIMEOUT,
    )


def summarize_response_chunks_with_llm(
    api_key: str,
    base_url: str,
    model: str,
    product_description: str,
    questionnaire_items: list[dict[str, Any]],
    responses: list[dict[str, Any]],
) -> list[str]:
    chunks = response_chunks(responses, QUESTIONNAIRE_ANALYSIS_BATCH_SIZE)
    if len(chunks) <= 1:
        return []

    summaries: list[str | None] = [None] * len(chunks)
    worker_count = min(QUESTIONNAIRE_ANALYSIS_MAX_WORKERS, len(chunks))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                summarize_response_chunk_with_llm,
                api_key,
                base_url,
                model,
                product_description,
                questionnaire_items,
                chunk,
                index,
                len(chunks),
            ): index
            for index, chunk in enumerate(chunks)
        }
        for future in as_completed(futures):
            summaries[futures[future]] = future.result().strip()

    return [summary or "" for summary in summaries]


def merge_summary_group_with_llm(
    api_key: str,
    base_url: str,
    model: str,
    product_description: str,
    summaries: list[str],
    level: int,
    group_index: int,
    total_groups: int,
) -> str:
    summary_text = "\n\n".join(summaries)
    prompt = f"""
你是用户研究数据分析师。下面是问卷分块摘要的第 {level} 层输入，当前为第 {group_index + 1}/{total_groups} 组。
请把这些摘要继续合并成更高一层中文 Markdown 摘要，不要写最终总报告。

产品/竞品方向:
{product_description}

待合并摘要:
{summary_text}

合并要求:
- 保留跨批次反复出现的强信号。
- 保留明显分歧、少数但重要的风险和机会。
- 不要编造摘要中没有的数据。
- 输出精炼，适合作为下一层汇总输入。
""".strip()

    return chat_content(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            {"role": "system", "content": "你合并多批问卷小结，产出更高层用户研究摘要。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=2200,
        timeout=LLM_TIMEOUT,
    )


def reduce_summaries_stepwise_with_llm(
    api_key: str,
    base_url: str,
    model: str,
    product_description: str,
    summaries: list[str],
) -> str:
    current = [
        f"### 批次 {index + 1}\n{summary.strip()}"
        for index, summary in enumerate(summaries)
        if summary.strip()
    ]
    level = 1
    while len(current) > QUESTIONNAIRE_ANALYSIS_REDUCE_FAN_IN:
        groups = response_chunks(current, QUESTIONNAIRE_ANALYSIS_REDUCE_FAN_IN)
        merged: list[str | None] = [None] * len(groups)
        worker_count = min(QUESTIONNAIRE_ANALYSIS_MAX_WORKERS, len(groups))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    merge_summary_group_with_llm,
                    api_key,
                    base_url,
                    model,
                    product_description,
                    group,
                    level,
                    index,
                    len(groups),
                ): index
                for index, group in enumerate(groups)
            }
            for future in as_completed(futures):
                merged[futures[future]] = future.result().strip()
        current = [
            f"### 第 {level + 1} 层摘要 {index + 1}\n{summary}"
            for index, summary in enumerate(merged)
            if summary
        ]
        level += 1
    return "\n\n".join(current)


def build_chunked_analysis_prompt(
    product_description: str,
    questionnaire_items: list[dict[str, Any]],
    code_analysis: dict[str, Any],
    rollup_summary: str,
) -> str:
    return f"""
你是用户研究数据分析师。请根据全局代码统计结果和分块上递摘要，写一份中文问卷数据分析报告。

产品/竞品方向:
{product_description}

问卷题目:
{questionnaire_for_llm(questionnaire_items)}

全局代码统计结果（长文本已压缩，主要用于校准样本量、频数和数值结果）:
{json_for_llm(code_analysis)}

分块上递摘要（每 50 份答卷先统计和总结，再逐层合并）:
{rollup_summary}

报告要求:
- 用中文输出 Markdown。
- 先说明样本规模和模拟数据属性。
- 分析受访者画像分布。
- 分析每个关键维度的结论：工具使用、功能优先级、痛点、价格敏感度、替换意愿、安全/部署/隐私、购买决策。
- 标出最强信号、分歧点、潜在机会点、风险点。
- 给出产品定位、定价/套餐、功能优先级、销售/获客、后续真实调研的建议。
- 开放题长文本结论优先依据分块上递摘要归纳，不要逐条复述原始长答案。
- 不要夸大样本；如果样本是模拟数据，要明确提示不能直接代表真实市场。
""".strip()


def analyze_survey_with_llm(
    product_description: str,
    questionnaire_items: list[dict[str, Any]],
    responses: list[dict[str, Any]],
    code_analysis: dict[str, Any] | None = None,
) -> str:
    api_key, base_url, model = active_llm_config()
    if code_analysis is None:
        code_analysis = build_code_analysis(questionnaire_items, responses)

    chunk_summaries = summarize_response_chunks_with_llm(
        api_key,
        base_url,
        model,
        product_description,
        questionnaire_items,
        responses,
    )
    if chunk_summaries:
        rollup_summary = reduce_summaries_stepwise_with_llm(
            api_key,
            base_url,
            model,
            product_description,
            chunk_summaries,
        )
        prompt = build_chunked_analysis_prompt(
            product_description,
            questionnaire_items,
            code_analysis,
            rollup_summary,
        )
    else:
        prompt = build_direct_analysis_prompt(product_description, questionnaire_items, code_analysis)

    return chat_content(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            {"role": "system", "content": "你根据问卷统计结果写中文用户研究分析报告。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=5000,
        timeout=LLM_TIMEOUT,
    )


def write_analysis_markdown(
    analysis_markdown: str,
    product_description: str,
    code_analysis: dict[str, Any],
) -> Path:
    path = output_base_path(product_description, "analysis.md")
    output = "\n\n".join(
        [
            "# 问卷数据分析报告",
            "",
            analysis_markdown,
            "",
            "===== CODE SUMMARY JSON =====",
            "```json",
            json.dumps(code_analysis, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    path.write_text(output, encoding="utf-8")
    return path


def analyze_response_files(
    questionnaire_path: Path,
    responses_path: Path,
    product_description: str,
) -> Path:
    questionnaire_items = normalize_questionnaire_items(read_jsonl(questionnaire_path))
    responses = read_jsonl(responses_path)
    code_analysis = build_code_analysis(questionnaire_items, responses)
    analysis_markdown = analyze_survey_with_llm(product_description, questionnaire_items, responses, code_analysis)
    return write_analysis_markdown(analysis_markdown, product_description, code_analysis)


def main() -> None:
    api_key, _, _ = active_llm_config()
    if not api_key:
        raise RuntimeError("请先设置当前 LLM_PROVIDER 对应的 API key，例如 LLM0_API_KEY/ARK_API_KEY、LLM1_API_KEY 或 LLM2_API_KEY。")

    if ANALYZE_ONLY:
        paths = [part.strip().strip('"') for part in re.split(r"[,;，；]", ANALYZE_ONLY) if part.strip()]
        if len(paths) < 2:
            raise RuntimeError("ANALYZE_ONLY 需要两个路径：问卷jsonl,回答jsonl")
        product_description = read_product_description()
        questionnaire_path = Path(paths[0])
        responses_path = Path(paths[1])
        if not questionnaire_path.is_absolute():
            questionnaire_path = ROOT / questionnaire_path
        if not responses_path.is_absolute():
            responses_path = ROOT / responses_path
        print("\n===== 分析已有问卷数据 =====")
        analysis_path = analyze_response_files(questionnaire_path, responses_path, product_description)
        print(f"已生成问卷分析报告: {analysis_path}")
        return

    if SearchSource(SEARCH_SOURCE) == SearchSource.BOCHA and not BOCHA_API_KEY:
        raise RuntimeError("当前 SEARCH_SOURCE=bocha，请先设置 BOCHA_API_KEY。")
    if SearchSource(SEARCH_SOURCE) == SearchSource.GOOGLE and (not GOOGLE_API_KEY or not GOOGLE_CX_ID):
        raise RuntimeError("当前 SEARCH_SOURCE=google，请先设置 GOOGLE_API_KEY 和 GOOGLE_CX_ID。")

    product_description = read_product_description()
    if not product_description:
        raise RuntimeError("产品/竞品方向不能为空。")

    own_param_path, own_param_text = read_optional_text_file()
    if own_param_path:
        print(f"[params] 已读取自己产品参数: {own_param_path}")

    print("\n===== 搜索相关产品/竞品 =====")
    result = find_competitors(product_description)

    print("\n===== LLM 改写后的搜索词 =====")
    for query in result.queries:
        print(f"- {query}")

    print("\n===== 抽取到的相关产品 =====")
    if result.product_names:
        for index, name in enumerate(result.product_names[:COMPETITOR_LIMIT], 1):
            print(f"{index}. {name}")
    else:
        print("未抽取到明确产品名，将仅根据搜索结果生成问卷。")

    print("\n===== 生成调查问卷 JSONL =====")
    items = generate_questionnaire(
        product_description=product_description,
        own_param_text=own_param_text,
        competitor_names=result.product_names,
        search_results=result.search_results,
    )
    if not items:
        raise RuntimeError("模型没有生成有效问卷题目。")

    output_path = write_jsonl(items, product_description)
    print(f"已生成 {len(items)} 个题目: {output_path}")

    print(f"\n===== 调用豆包模拟填写 {SIMULATED_RESPONSE_COUNT} 份问卷 =====")
    responses = simulate_responses(
        product_description=product_description,
        own_param_text=own_param_text,
        competitor_names=result.product_names,
        questionnaire_items=items,
        total_count=SIMULATED_RESPONSE_COUNT,
    )
    response_jsonl_path = write_response_jsonl(responses, product_description)
    response_csv_path = write_response_csv(responses, items, product_description)
    print(f"已生成 {len(responses)} 份模拟填写 JSONL: {response_jsonl_path}")
    print(f"已生成 {len(responses)} 份模拟填写 CSV: {response_csv_path}")

    print("\n===== 分析问卷数据 =====")
    code_analysis = build_code_analysis(items, responses)
    analysis_markdown = analyze_survey_with_llm(product_description, items, responses, code_analysis)
    analysis_path = write_analysis_markdown(analysis_markdown, product_description, code_analysis)
    print(f"已生成问卷分析报告: {analysis_path}")


if __name__ == "__main__":
    main()

"""Analyze an existing questionnaire file and filled response file."""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "questionnaires"

sys.path.insert(0, str(ROOT))

from extracted_core.llm_client import chat_content, stream_chat_content  # noqa: E402


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

LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "180"))
ANALYSIS_STREAM = os.getenv("ANALYSIS_STREAM", "1").strip() not in {"0", "false", "False", "no", "NO"}
MAX_ANALYSIS_JSON_CHARS = int(os.getenv("MAX_ANALYSIS_JSON_CHARS", "45000"))


def active_llm_config() -> tuple[str, str, str]:
    if LLM_PROVIDER == 0:
        return LLM0_API_KEY, LLM0_BASE_URL, LLM0_MODEL
    if LLM_PROVIDER == 1:
        return LLM1_API_KEY, LLM1_BASE_URL, LLM1_MODEL
    if LLM_PROVIDER == 2:
        return LLM2_API_KEY, LLM2_BASE_URL, LLM2_MODEL
    raise ValueError("LLM_PROVIDER 必须是 0、1 或 2。")


def resolve_path(path_text: str) -> Path:
    path = Path(path_text.strip().strip('"'))
    if not path.is_absolute():
        path = ROOT / path
    return path


def safe_filename(text: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\r\n\t]+', "_", text).strip(" ._")
    value = re.sub(r"\s+", "_", value)
    return value[:50] or "questionnaire"


def output_base_path(product_description: str, suffix: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return OUTPUT_DIR / f"{timestamp}_{safe_filename(product_description)}_{suffix}"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path} 第 {line_number} 行不是有效 JSON。") from exc
            if isinstance(value, dict):
                items.append(value)
    return items


def normalize_questionnaire_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
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


def read_responses_jsonl(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(path)


def split_csv_list(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = re.split(r"[、,，;；|/]+", text)
    return [part.strip() for part in parts if part.strip()]


def read_responses_csv(path: Path, questionnaire_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    question_ids = [item["id"] for item in questionnaire_items]
    responses: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for index, row in enumerate(reader, 1):
            profile = {
                "role": row.get("role", ""),
                "industry": row.get("industry", ""),
                "company_size": row.get("company_size", ""),
                "experience_level": row.get("experience_level", ""),
                "budget_sensitivity": row.get("budget_sensitivity", ""),
                "current_tools": split_csv_list(row.get("current_tools", "")),
            }
            answers = []
            for question_id in question_ids:
                if question_id in row:
                    answers.append(
                        {
                            "question_id": question_id,
                            "answer": row.get(question_id, ""),
                            "reason": "",
                        }
                    )
            responses.append(
                {
                    "respondent_id": row.get("respondent_id") or f"R{index:03d}",
                    "profile": profile,
                    "answers": answers,
                }
            )
    return responses


def read_responses(path: Path, questionnaire_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_responses_csv(path, questionnaire_items)
    return read_responses_jsonl(path)


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


def build_code_analysis(
    questionnaire_items: list[dict[str, Any]],
    responses: list[dict[str, Any]],
) -> dict[str, Any]:
    question_map = {item["id"]: item for item in questionnaire_items}
    profile_fields = [
        "role",
        "industry",
        "company_size",
        "experience_level",
        "budget_sensitivity",
    ]

    profile_summary = {}
    for field in profile_fields:
        profile_summary[field] = count_values(
            [
                str(response.get("profile", {}).get(field, ""))
                for response in responses
                if isinstance(response.get("profile"), dict)
            ]
        )
    profile_summary["current_tools"] = count_values(
        [
            str(tool)
            for response in responses
            if isinstance(response.get("profile"), dict)
            for tool in (
                response.get("profile", {}).get("current_tools", [])
                if isinstance(response.get("profile", {}).get("current_tools", []), list)
                else [response.get("profile", {}).get("current_tools", "")]
            )
        ]
    )

    question_summaries = []
    for question_id, question in question_map.items():
        answers: list[str] = []
        reasons: list[str] = []
        numeric_values: list[float] = []
        for response in responses:
            response_answers = response.get("answers") if isinstance(response.get("answers"), list) else []
            for answer in response_answers:
                if not isinstance(answer, dict) or str(answer.get("question_id")) != question_id:
                    continue
                raw_answer = answer.get("answer", "")
                reasons.append(str(answer.get("reason") or ""))
                if isinstance(raw_answer, list):
                    answers.extend(str(item) for item in raw_answer)
                else:
                    answers.append(str(raw_answer))
                if isinstance(raw_answer, (int, float)):
                    numeric_values.append(float(raw_answer))
                elif isinstance(raw_answer, str) and raw_answer.strip().isdigit():
                    numeric_values.append(float(raw_answer.strip()))

        summary: dict[str, Any] = {
            "id": question_id,
            "dimension": question.get("dimension", ""),
            "question_type": question.get("question_type", ""),
            "question": question.get("question", ""),
            "answer_count": len(answers),
            "top_answers": count_values(answers),
            "sample_reasons": [reason for reason in reasons if reason][:5],
        }
        if numeric_values:
            summary["numeric_avg"] = round(sum(numeric_values) / len(numeric_values), 2)
            summary["numeric_min"] = min(numeric_values)
            summary["numeric_max"] = max(numeric_values)
        question_summaries.append(summary)

    return {
        "respondent_count": len(responses),
        "question_count": len(questionnaire_items),
        "profile_summary": profile_summary,
        "question_summaries": question_summaries,
    }


def build_analysis_prompt(
    product_description: str,
    questionnaire_items: list[dict[str, Any]],
    code_analysis: dict[str, Any],
) -> str:
    compact_questions = compact_questionnaire(questionnaire_items)
    analysis_json = json.dumps(code_analysis, ensure_ascii=False)
    if len(analysis_json) > MAX_ANALYSIS_JSON_CHARS:
        analysis_json = analysis_json[:MAX_ANALYSIS_JSON_CHARS] + "\n...[已截断，保留前半部分统计结果]"

    return f"""
你是用户研究数据分析师。请根据问卷题目和代码统计结果，写一份中文问卷数据分析报告。

产品/竞品方向:
{product_description}

问卷题目:
{compact_questions}

代码统计结果:
{analysis_json}

报告要求:
- 用中文输出 Markdown。
- 先说明样本规模，以及数据来源是模拟填写还是真实填写；如果无法确认，要明确写“无法仅凭文件判断是否为真实样本”。
- 分析受访者画像分布。
- 按关键维度总结结论：当前工具使用、核心场景、功能优先级、痛点、价格敏感度、替换意愿、安全/部署/隐私、购买决策。
- 标出最强信号、明显分歧点、潜在机会点、主要风险点。
- 给出产品定位、定价/套餐、功能优先级、销售/获客、后续真实调研的建议。
- 不要夸大样本，不要编造统计结果中不存在的数据。
""".strip()


def analyze_survey_with_llm(
    product_description: str,
    questionnaire_items: list[dict[str, Any]],
    code_analysis: dict[str, Any],
) -> str:
    api_key, base_url, model = active_llm_config()
    prompt = build_analysis_prompt(product_description, questionnaire_items, code_analysis)
    messages = [
        {"role": "system", "content": "你根据问卷统计结果写中文用户研究分析报告。"},
        {"role": "user", "content": prompt},
    ]

    if ANALYSIS_STREAM:
        chunks = []
        print("\n===== LLM 分析流式输出 =====")
        for chunk in stream_chat_content(
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=5000,
            timeout=LLM_TIMEOUT,
        ):
            print(chunk, end="", flush=True)
            chunks.append(chunk)
        print()
        return "".join(chunks)

    return chat_content(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=5000,
        timeout=LLM_TIMEOUT,
    )


def write_analysis_markdown(
    analysis_markdown: str,
    product_description: str,
    questionnaire_path: Path,
    responses_path: Path,
    code_analysis: dict[str, Any],
) -> Path:
    path = output_base_path(product_description, "analysis.md")
    output = "\n\n".join(
        [
            "# 问卷数据分析报告",
            "",
            f"- 问卷文件: `{questionnaire_path}`",
            f"- 回答文件: `{responses_path}`",
            f"- 产品/竞品方向: {product_description}",
            "",
            analysis_markdown.strip(),
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
    if not questionnaire_items:
        raise RuntimeError("问卷文件中没有读到有效题目。")

    responses = read_responses(responses_path, questionnaire_items)
    if not responses:
        raise RuntimeError("回答文件中没有读到有效回答。")

    print(f"[read] 问卷题目: {len(questionnaire_items)}")
    print(f"[read] 回答样本: {len(responses)}")
    print("[analyze] 正在做代码统计...")
    code_analysis = build_code_analysis(questionnaire_items, responses)
    print("[analyze] 正在调用 LLM 写中文分析报告...")
    analysis_markdown = analyze_survey_with_llm(product_description, questionnaire_items, code_analysis)
    return write_analysis_markdown(
        analysis_markdown=analysis_markdown,
        product_description=product_description,
        questionnaire_path=questionnaire_path,
        responses_path=responses_path,
        code_analysis=code_analysis,
    )


def read_cli_or_prompt() -> tuple[Path, Path, str]:
    args = [arg.strip() for arg in sys.argv[1:] if arg.strip()]
    if len(args) >= 2:
        questionnaire_path = resolve_path(args[0])
        responses_path = resolve_path(args[1])
        product_description = " ".join(args[2:]).strip() if len(args) > 2 else ""
    else:
        questionnaire_path = resolve_path(input("请输入问卷 JSONL 路径: ").strip())
        responses_path = resolve_path(input("请输入回答 JSONL/CSV 路径: ").strip())
        product_description = ""

    if not product_description:
        product_description = input("请输入产品/竞品方向: ").strip()
    if not product_description:
        product_description = questionnaire_path.stem
    return questionnaire_path, responses_path, product_description


def main() -> None:
    api_key, _, _ = active_llm_config()
    if not api_key:
        raise RuntimeError("请先设置当前 LLM_PROVIDER 对应的 API key，例如 LLM0_API_KEY/ARK_API_KEY、LLM1_API_KEY 或 LLM2_API_KEY。")

    questionnaire_path, responses_path, product_description = read_cli_or_prompt()
    if not questionnaire_path.exists():
        raise FileNotFoundError(f"问卷文件不存在: {questionnaire_path}")
    if not responses_path.exists():
        raise FileNotFoundError(f"回答文件不存在: {responses_path}")

    print("\n===== 分析已有问卷数据 =====")
    print(f"[file] 问卷: {questionnaire_path}")
    print(f"[file] 回答: {responses_path}")
    print(f"[topic] {product_description}")

    analysis_path = analyze_response_files(questionnaire_path, responses_path, product_description)
    print(f"\n已生成问卷分析报告: {analysis_path}")


if __name__ == "__main__":
    main()

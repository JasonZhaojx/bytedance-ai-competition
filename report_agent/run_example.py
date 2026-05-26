"""Example: call report_agent.pipeline and print the final result.

Run from project root:
    python report_agent/run_example.py

Or pass custom input:
    python report_agent/run_example.py "AI IDE 编程助手竞品分析" --competitors "Trae, Cursor"
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from report_agent.models import WritingAgentConfig
from report_agent.pipeline import run_search_and_report


DEFAULT_PRODUCT_DESCRIPTION = "AI IDE 编程助手竞品分析"
DEFAULT_COMPETITORS = ["Trae", "Cursor"]
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Call report_agent.pipeline.run_search_and_report"
    )
    parser.add_argument(
        "product_description",
        nargs="?",
        default=DEFAULT_PRODUCT_DESCRIPTION,
        help="产品方向、竞品分析需求或要调研的问题",
    )
    parser.add_argument(
        "--competitors",
        default=", ".join(DEFAULT_COMPETITORS),
        help="可选竞品名，多个竞品用逗号分隔；传空字符串则不指定竞品",
    )
    parser.add_argument(
        "--task-id",
        default="run_example_ai_ide_report",
        help="写入 ReportPackage 的任务 ID",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="输出 Markdown、ReportPackage JSON、搜索结果 JSON 的目录",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="只关闭 report 阶段的云端 LLM；search 仍按默认配置真实执行",
    )
    return parser.parse_args()


def split_competitors(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,，、;\n]+", value) if part.strip()]


def main() -> None:
    args = parse_args()
    writing_config = None
    if args.no_llm:
        writing_config = WritingAgentConfig(use_llm=False, verbose=True)

    result = run_search_and_report(
        product_description=args.product_description,
        competitors=split_competitors(args.competitors),
        task_id=args.task_id,
        output_dir=args.output_dir,
        writing_config=writing_config,
    )

    print("\n===== PIPELINE RESULT SUMMARY =====")
    print(f"task_id: {result.task_id}")
    print(f"product_description: {result.product_description}")
    print(f"competitors: {', '.join(result.competitors) or '未指定'}")
    print(f"queries: {len(result.queries)}")
    for index, query in enumerate(result.queries, 1):
        print(f"  {index}. {query}")
    print(f"search_result_count: {result.search_result_count}")
    print(f"search_errors: {result.search_errors or '无'}")
    print(f"report_chars: {len(result.report_package.report_markdown)}")
    print(f"claim_count: {len(result.report_package.claim_evidence_map)}")

    print("\n===== OUTPUT PATHS =====")
    if result.output_paths:
        for key, value in result.output_paths.items():
            print(f"{key}: {value}")
    else:
        print("未落盘")

    print("\n===== FINAL REPORT MARKDOWN =====")
    print(result.report_package.report_markdown)


if __name__ == "__main__":
    main()

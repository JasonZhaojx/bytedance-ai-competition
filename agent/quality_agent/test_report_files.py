"""Test quality_agent with real report files."""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))
print(f"Project root: {project_root}")

from report_agent.models import ReportPackage
from agent.quality_agent import (
    QualityConfig,
    LLMConfig,
    InspectionMode,
    inspect_report_package,
    print_batch_summary,
)

import json
import re


def load_markdown_report(file_path: str) -> tuple[str, dict]:
    """从 markdown 文件加载报告内容 """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 尝试解析 JSON 元数据（如果文件包含）
    metadata = {}

    # 检查是否有 JSON 前缀
    json_match = re.match(r'```json\n(.*?)\n```', content, re.DOTALL)
    if json_match:
        try:
            metadata = json.loads(json_match.group(1))
            # 移除 JSON 部分，只保留 markdown 内容
            content = content[json_match.end():].strip()
        except:
            pass

    return content, metadata


def create_report_package_from_file(file_path: str, task_id: str = "test") -> ReportPackage:
    """从文件创建 ReportPackage """
    content, metadata = load_markdown_report(file_path)

    # 提取 structured_analysis 如果存在
    structured_analysis = metadata.get("structured_analysis", {})
    claim_evidence_map = metadata.get("claim_evidence_map", [])
    sources = metadata.get("sources", [])
    generation_trace = metadata.get("generation_trace", [])

    # 如果没有 metadata，尝试从 content 中提取
    if not structured_analysis and "## 分析结果" in content:
        # 简单提取第一个 SWOT 部分作为示例
        structured_analysis = {
            "swot": {"strengths": [], "weaknesses": [], "opportunities": [], "threats": []},
            "evidence_cards": [],
        }

    return ReportPackage(
        task_id=task_id,
        report_markdown=content,
        structured_analysis=structured_analysis,
        claim_evidence_map=claim_evidence_map,
        generation_trace=generation_trace,
        sources=sources,
    )


def main():
    print("=" * 70)
    print("Quality Agent Report Testing")
    print("=" * 70)

    # 配置
    config = QualityConfig(
        inspection_mode=InspectionMode.RULE_ONLY,
        llm=LLMConfig(enabled=False),
    )
    config.print_summary()

    # 查找报告文件
    reports_dir = Path(__file__).parent.parent.parent / "reports"
    print(f"Reports dir: {reports_dir}")
    report_files = list(reports_dir.glob("*.md"))

    if not report_files:
        print("\nNo report files found in reports/")
        print("Available files:", list(reports_dir.glob("*.md"))[:5])
        return

    print(f"\nFound {len(report_files)} report files")

    # 测试每个报告
    for i, report_file in enumerate(report_files[:3], 1):  # 最多测试3个
        print(f"\n{'='*70}")
        print(f"Testing Report {i}: {report_file.name}")
        print("=" * 70)

        try:
            # 加载报告
            print("\n[1] Loading report...")
            package = create_report_package_from_file(str(report_file))
            print(f"    Report length: {len(package.report_markdown)} chars")
            print(f"    Evidence cards: {len(package.structured_analysis.get('evidence_cards', []))}")
            print(f"    Sources: {len(package.sources)}")

            # 质检
            print("\n[2] Running quality inspection...")
            result = inspect_report_package(package, config)

            # 打印结果
            print("\n[3] Results:")
            print(f"    Score: {result.score:.2f}")
            print(f"    Passed: {result.passed}")
            print(f"    Confidence: {result.confidence_level.value}")
            print(f"    Issues found: {len(result.issues)}")

            if result.issues:
                print("\n    Issues:")
                for issue in result.issues[:5]:  # 最多显示5个
                    print(f"      - [{issue.severity.value}] {issue.description}")

            print("\n[OK] Report tested successfully!")

        except Exception as e:
            print(f"\n[FAIL] Error testing report: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()

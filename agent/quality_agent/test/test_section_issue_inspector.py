"""Focused tests for section-based Quality Agent issues."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agent.quality_agent.adapters.report_adapter import ReportAnalysis
from agent.quality_agent.inspectors.section_issue_inspector import (
    build_final_body_section_issues,
)


def _analysis(markdown: str) -> ReportAnalysis:
    return ReportAnalysis(
        task_id="section_issue_test",
        product_name="AI IDE",
        evidence_list=[],
        claims=[],
        pm_insights=[],
        swot={},
        recommendations=[],
        report_markdown=markdown,
    )


def test_report_agent_fixed_sections_become_revision_suggestions() -> None:
    markdown = """
# Report Agent 标准竞品分析报告（含 Quality Agent 闭环）

原始需求: AI IDE

# AI IDE 竞品横向分析报告

## 核心结论
这里是核心结论。

## 分析背景与目标
这里是分析背景。

## 横向能力对比
| 竞品 | 企业定价 |
| --- | --- |
| CodeBuddy | 待搜索 |

## 资料来源
- src_001

## 质量闭环摘要
- Issue 数: 0
""".strip()

    issues = build_final_body_section_issues(_analysis(markdown), [])

    assert [issue.description for issue in issues] == [
        "关于核心结论的修改建议",
        "关于分析背景与目标的修改建议",
        "建议人工搜索CodeBuddy 企业定价",
    ]


def test_final_comparison_skips_old_issue_and_metrics_sections() -> None:
    markdown = """
# 所选产品横向对比报告

## 最终横向对比摘要

# Codex类AI IDE国产替代品横向对比报告

## 一、核心参数点横向对比（对齐我方产品参数关键词库）
| 参数点 | CodeGeeX |
| --- | --- |
| 定价 | 未找到明确证据 |

## 二、单产品画像拆解
这里是单产品画像。

## 四、详细Issue清单
| Issue | 建议 |
| --- | --- |
| 旧格式问题 | 旧格式建议 |

## 五、业务闭环指标
这里不应该变成 Quality Agent issue。

## 相关文件
- path
""".strip()

    issues = build_final_body_section_issues(_analysis(markdown), [])

    assert [issue.description for issue in issues] == [
        "建议人工搜索定价 CodeGeeX",
        "关于单产品画像拆解的修改建议",
    ]


def test_table_outputs_every_missing_cell_as_manual_search_issue() -> None:
    markdown = """
# AI IDE 横向分析报告

## 横向能力对比
| 参数点 | 通义灵码 | CodeGeeX | CodeBuddy |
| --- | --- | --- | --- |
| 已暴露体验短板 | 待搜索 | 未找到明确证据 | 完全缺失 |
| 私有化部署 | 未公开 | 已支持 | 待补充 |
""".strip()

    issues = build_final_body_section_issues(_analysis(markdown), [])

    assert [issue.description for issue in issues] == [
        "建议人工搜索已暴露体验短板 通义灵码",
        "建议人工搜索已暴露体验短板 CodeGeeX",
        "建议人工搜索已暴露体验短板 CodeBuddy",
        "建议人工搜索私有化部署 通义灵码",
        "建议人工搜索私有化部署 CodeBuddy",
    ]


def test_table_does_not_treat_normal_shortcoming_text_as_missing_cell() -> None:
    markdown = """
# AI IDE 横向分析报告

## 横向能力对比
| 竞品 | 已暴露体验短板 |
| --- | --- |
| 通义灵码 | 早期VS Code端插件会干扰原生代码提示，缺少一键启停快捷键 |
""".strip()

    issues = build_final_body_section_issues(_analysis(markdown), [])

    assert [issue.description for issue in issues] == [
        "关于横向能力对比的修改建议",
    ]


def test_non_table_section_suggestions_are_section_specific_without_manual_search() -> None:
    markdown = """
# AI IDE 横向分析报告

## 横向能力对比
这里是普通正文，不是表格。CodeBuddy 在部分场景表现更强。

## SWOT 分析
这里列出优势、劣势、机会和威胁，但还没有串到策略。

## 产品策略建议
这里给出若干方向性建议。
""".strip()

    issues = build_final_body_section_issues(_analysis(markdown), [])
    suggestions = [issue.suggestion for issue in issues]

    assert len(set(suggestions)) == 3
    assert all("建议人工搜索" not in suggestion for suggestion in suggestions)
    assert "判定口径" in suggestions[0]
    assert "事实依据-对我方影响-下一步动作" in suggestions[1]
    assert "优先级、投入成本、验证指标" in suggestions[2]

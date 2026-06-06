"""Focused checks for search-backed table gap handling."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from report_agent.table_gap_search import (
    NO_PRODUCT_EVIDENCE,
    PENDING_SEARCH,
    _collect_gaps,
    _gap_query_budget,
    _merge_filled_outputs,
    _mark_table_gaps,
    _rewrite_repeated_gap_queries,
    _strip_internal_fields,
    TableGap,
)
from report_agent.models import WritingAgentConfig


def test_generic_table_fill_merges_by_row_index() -> None:
    profiles = [
        {
            "competitor": "OpenCode",
            "target_user": "终端重度开发者",
            "evidence_ids": ["ev_001"],
            "pending_search_query": "OpenCode target user",
        }
    ]
    tables = [
        {
            "table_name": "产品形态与入口对比",
            "columns": ["竞品", "主要入口", "证据ID"],
            "rows": [
                {
                    "竞品": "OpenCode",
                    "主要入口": PENDING_SEARCH,
                    "evidence_ids": [],
                    "pending_search_query": "OpenCode product entry",
                }
            ],
        }
    ]
    filled_tables = [
        {
            "table_name": "产品形态与入口对比",
            "columns": ["竞品", "主要入口", "证据ID"],
            "rows": [
                {
                    "竞品": "OpenCode",
                    "主要入口": "终端 TUI、桌面应用与 IDE 扩展",
                    "evidence_ids": ["gap_src_001"],
                }
            ],
        }
    ]

    merged_profiles, merged_tables = _merge_filled_outputs(
        profiles=profiles,
        tables=tables,
        filled_profiles=[],
        filled_tables=filled_tables,
        competitors=["OpenCode"],
    )
    cleaned_profiles, cleaned_tables = _strip_internal_fields(
        merged_profiles, merged_tables
    )

    row = cleaned_tables[0]["rows"][0]
    assert row["主要入口"] == "终端 TUI、桌面应用与 IDE 扩展"
    assert row["evidence_ids"] == ["gap_src_001"]
    assert "pending_search_query" not in row
    assert "pending_search_query" not in cleaned_profiles[0]


def test_empty_generic_table_gets_pending_rows() -> None:
    tables = [
        {
            "table_name": "竞品基础定位与用户场景对比",
            "columns": ["竞品", "目标用户", "核心场景", "证据ID"],
            "rows": [],
        }
    ]

    marked = _mark_table_gaps(tables, ["OpenCode", "Qoder"])
    rows = marked[0]["rows"]

    assert len(rows) == 2
    assert rows[0]["竞品"] == "OpenCode"
    assert rows[0]["目标用户"].startswith(PENDING_SEARCH)
    assert rows[1]["竞品"] == "Qoder"
    assert rows[1]["核心场景"].startswith(PENDING_SEARCH)


def test_partial_generic_table_gets_missing_competitors_and_finalizes_pending() -> None:
    tables = [
        {
            "table_name": "商业化与定价策略对比",
            "columns": ["竞品名称", "公开套餐档位", "企业版公开定价", "证据ID"],
            "rows": [
                {
                    "竞品名称": "OpenCode",
                    "公开套餐档位": "开源免费",
                    "企业版公开定价": PENDING_SEARCH,
                    "evidence_ids": [],
                }
            ],
        }
    ]

    marked = _mark_table_gaps(tables, ["OpenCode", "CodeBuddy", "Qoder"])
    rows = marked[0]["rows"]
    names = [row["竞品名称"] for row in rows]

    assert names == ["OpenCode", "CodeBuddy", "Qoder"]
    assert rows[1]["公开套餐档位"].startswith(PENDING_SEARCH)

    _, cleaned_tables = _strip_internal_fields([], marked)
    cleaned_rows = cleaned_tables[0]["rows"]
    assert cleaned_rows[0]["企业版公开定价"] == NO_PRODUCT_EVIDENCE
    assert cleaned_rows[1]["公开套餐档位"] == NO_PRODUCT_EVIDENCE


def test_public_missing_phrases_are_search_gaps() -> None:
    tables = [
        {
            "table_name": "用户体验与市场反馈对比",
            "columns": ["竞品名称", "核心交互特性", "公开正面用户反馈", "公开负面用户反馈", "关联证据ID"],
            "rows": [
                {
                    "竞品名称": "CodeBuddy",
                    "核心交互特性": "未找到明确公开信息",
                    "公开正面用户反馈": "暂未公开明确披露相关信息",
                    "公开负面用户反馈": "未公开SSO单点登录、SOC2认证等特性",
                    "evidence_ids": [],
                }
            ],
        }
    ]

    marked = _mark_table_gaps(tables, ["CodeBuddy"])
    gaps = _collect_gaps([], marked, ["CodeBuddy"])

    assert len(gaps) >= 3
    assert {gap.field for gap in gaps} >= {"核心交互特性", "公开正面用户反馈", "公开负面用户反馈"}


def test_all_pending_mode_uses_every_gap_as_query_budget() -> None:
    config = WritingAgentConfig(
        use_llm=False,
        table_gap_search_max_queries=1,
        table_gap_search_all_pending=True,
    )

    assert _gap_query_budget(config, 5) == 5


def test_repeated_gap_query_is_rewritten_for_retry() -> None:
    config = WritingAgentConfig(use_llm=False)
    gap = TableGap(
        gap_id="gap_001",
        table_name="pricing",
        competitor="OpenCode",
        field="pricing",
    )
    old_query = "OpenCode pricing official"

    rewritten = _rewrite_repeated_gap_queries(
        [gap],
        "AI coding agent",
        {"gap_001": old_query},
        {old_query},
        config,
    )

    assert rewritten["gap_001"] != old_query
    assert "OpenCode pricing official" in rewritten["gap_001"]


def test_strip_internal_fields_fills_missing_generic_columns() -> None:
    tables = [
        {
            "table_name": "pricing",
            "columns": ["竞品", "企业版定价档位", "计费单位", "支撑证据ID"],
            "rows": [{"竞品": "qoder", "企业版定价档位": PENDING_SEARCH}],
        }
    ]

    _, cleaned_tables = _strip_internal_fields([], tables, finalize_pending=True)
    row = cleaned_tables[0]["rows"][0]

    assert row["企业版定价档位"] == NO_PRODUCT_EVIDENCE
    assert row["计费单位"] == NO_PRODUCT_EVIDENCE
    assert "支撑证据ID" not in row


if __name__ == "__main__":
    test_generic_table_fill_merges_by_row_index()
    test_empty_generic_table_gets_pending_rows()
    test_partial_generic_table_gets_missing_competitors_and_finalizes_pending()
    test_public_missing_phrases_are_search_gaps()
    test_all_pending_mode_uses_every_gap_as_query_budget()
    test_repeated_gap_query_is_rewritten_for_retry()
    test_strip_internal_fields_fills_missing_generic_columns()
    print("table gap search focused test passed")

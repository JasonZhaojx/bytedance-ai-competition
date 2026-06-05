"""Focused checks for structured comparison-table workspaces."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from report_agent.models import WritingAgentConfig
from report_agent.table_workspace import (
    apply_cell_updates,
    export_comparison_table_workspace,
    flatten_comparison_tables,
    pending_cell_payload,
)


def sample_tables() -> list[dict]:
    return [
        {
            "table_name": "商业化定价",
            "columns": ["竞品", "企业版定价", "计费单位", "证据ID"],
            "rows": [
                {"竞品": "CodeBuddy", "企业版定价": "198元/月", "计费单位": "按席位"},
                {"竞品": "qoder", "企业版定价": "待搜索"},
            ],
        }
    ]


def test_workspace_flattens_and_updates_by_cell_id() -> None:
    tables = sample_tables()
    pending = pending_cell_payload(tables)
    target = next(cell for cell in pending if cell["column"] == "企业版定价")

    apply_cell_updates(
        tables,
        [
            {
                "cell_id": target["cell_id"],
                "value": "未公开企业版价格",
                "evidence_ids": ["gap_src_001"],
            }
        ],
    )

    assert tables[0]["rows"][1]["企业版定价"] == "未公开企业版价格"
    assert tables[0]["rows"][1]["evidence_ids"] == ["gap_src_001"]


def test_workspace_exports_csv_and_jsonl(tmp_path: Path) -> None:
    config = WritingAgentConfig(
        use_llm=False,
        export_comparison_tables=True,
        table_export_dir=str(tmp_path),
        verbose=False,
    )

    export_comparison_table_workspace(config, "unit test tables", sample_tables())

    assert list(tmp_path.glob("*unit_test_tables.csv"))
    assert list(tmp_path.glob("*unit_test_tables.jsonl"))
    assert flatten_comparison_tables(sample_tables())


if __name__ == "__main__":
    test_workspace_flattens_and_updates_by_cell_id()
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        test_workspace_exports_csv_and_jsonl(Path(tmp))
    print("table workspace focused test passed")

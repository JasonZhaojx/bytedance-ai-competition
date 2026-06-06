"""Debug helpers for printing comparison tables during generation."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Sequence

try:
    from .llm_utils import clean_text
    from .models import WritingAgentConfig
    from .table_workspace import export_comparison_table_workspace
except ImportError:
    from report_agent.llm_utils import clean_text
    from report_agent.models import WritingAgentConfig
    from report_agent.table_workspace import export_comparison_table_workspace


def log_comparison_tables(
    config: WritingAgentConfig,
    label: str,
    tables: Sequence[Dict[str, Any]],
) -> None:
    """Print comparison tables when table debug output is enabled."""

    export_comparison_table_workspace(config, label, tables)
    if not getattr(config, "print_comparison_tables", True):
        return
    if not config.verbose or not config.progress_printer:
        return
    rendered = _render_tables(tables)
    if not rendered:
        return
    config.progress_printer(f"\n===== {label} =====\n{rendered}\n")


def _render_tables(tables: Sequence[Dict[str, Any]]) -> str:
    sections: List[str] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        name = clean_text(table.get("table_name") or "横向对比表", 80)
        rows = table.get("rows") if isinstance(table.get("rows"), list) else table.get("dimensions")
        if not isinstance(rows, list):
            rows = []
        columns = table.get("columns")
        if not isinstance(columns, list):
            columns = _columns_for_rows(rows)
        columns = [
            str(column)
            for column in columns
            if str(column) not in {"pending_search_query"}
        ]
        sections.append(f"### {name}")
        sections.append(_simple_table(columns, rows))
    return "\n\n".join(section for section in sections if section).strip()


def _columns_for_rows(rows: Iterable[Any]) -> List[str]:
    columns: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row:
            text = str(key)
            if text == "pending_search_query":
                continue
            if text not in columns:
                columns.append(text)
    return columns


def _simple_table(columns: List[str], rows: Sequence[Any]) -> str:
    if not columns:
        return "暂无表头。"
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    if not rows:
        lines.append("| " + " | ".join([""] * len(columns)) + " |")
        return "\n".join(lines)
    for row in rows:
        if not isinstance(row, dict):
            continue
        lines.append("| " + " | ".join(_cell(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = clean_text(value, 220)
    return text.replace("|", "\\|")

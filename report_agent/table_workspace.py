"""Structured table workspace helpers for comparison-table auditing."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

try:
    from .llm_utils import clean_text
    from .models import WritingAgentConfig
except ImportError:
    from report_agent.llm_utils import clean_text
    from report_agent.models import WritingAgentConfig


@dataclass
class TableCell:
    cell_id: str
    table_name: str
    row_index: int
    column: str
    competitor: str
    value: str
    evidence_ids: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "table_name": self.table_name,
            "row_index": self.row_index,
            "column": self.column,
            "competitor": self.competitor,
            "value": self.value,
            "evidence_ids": self.evidence_ids,
        }


def flatten_comparison_tables(tables: Sequence[Dict[str, Any]]) -> List[TableCell]:
    cells: List[TableCell] = []
    for table_index, table in enumerate(tables):
        if not isinstance(table, dict):
            continue
        table_name = clean_text(table.get("table_name") or f"table_{table_index + 1}", 120)
        rows = table.get("rows") if isinstance(table.get("rows"), list) else table.get("dimensions")
        if not isinstance(rows, list):
            continue
        columns = _columns(table, rows)
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            competitor = _competitor(row)
            evidence_ids = _evidence_ids(row)
            for column in columns:
                if _internal_column(column):
                    continue
                value = _cell_text(row.get(column))
                cells.append(
                    TableCell(
                        cell_id=_cell_id(table_name, row_index, column),
                        table_name=table_name,
                        row_index=row_index,
                        column=column,
                        competitor=competitor,
                        value=value,
                        evidence_ids=evidence_ids,
                    )
                )
    return cells


def pending_cell_payload(tables: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    for cell in flatten_comparison_tables(tables):
        if _pending_or_blank(cell.value):
            payload.append(cell.to_dict())
    return payload


def apply_cell_updates(
    tables: Sequence[Dict[str, Any]],
    updates: Sequence[Dict[str, Any]],
) -> None:
    if not updates:
        return
    cell_index: Dict[str, tuple[Dict[str, Any], str]] = {}
    for table in tables:
        if not isinstance(table, dict):
            continue
        table_name = clean_text(table.get("table_name") or "", 120)
        rows = table.get("rows") if isinstance(table.get("rows"), list) else table.get("dimensions")
        if not isinstance(rows, list):
            continue
        columns = _columns(table, rows)
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            for column in columns:
                if _internal_column(column):
                    continue
                cell_index[_cell_id(table_name, row_index, column)] = (row, column)
    for update in updates:
        if not isinstance(update, dict):
            continue
        cell_id = clean_text(update.get("cell_id"), 160)
        value = clean_text(update.get("value"), 500)
        if not cell_id or not value or cell_id not in cell_index:
            continue
        row, column = cell_index[cell_id]
        row[column] = value
        evidence_ids = update.get("evidence_ids")
        if isinstance(evidence_ids, list):
            current = row.setdefault("evidence_ids", [])
            if not isinstance(current, list):
                current = []
                row["evidence_ids"] = current
            for item in evidence_ids:
                evidence_id = clean_text(item, 80)
                if evidence_id and evidence_id not in current:
                    current.append(evidence_id)


def export_comparison_table_workspace(
    config: WritingAgentConfig,
    label: str,
    tables: Sequence[Dict[str, Any]],
) -> None:
    if not getattr(config, "export_comparison_tables", True):
        return
    export_dir = Path(str(getattr(config, "table_export_dir", "") or "reports/report_agent_tables"))
    export_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_label = _safe_name(label)
    cells = [cell.to_dict() for cell in flatten_comparison_tables(tables)]
    csv_path = export_dir / f"{stamp}_{safe_label}.csv"
    jsonl_path = export_dir / f"{stamp}_{safe_label}.jsonl"
    fields = [
        "cell_id",
        "table_name",
        "row_index",
        "column",
        "competitor",
        "value",
        "evidence_ids",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in cells:
            csv_row = dict(row)
            csv_row["evidence_ids"] = json.dumps(csv_row.get("evidence_ids", []), ensure_ascii=False)
            writer.writerow(csv_row)
    with jsonl_path.open("w", encoding="utf-8") as file:
        for row in cells:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    if config.verbose and config.progress_printer:
        config.progress_printer(
            f"[writing-agent] table workspace exported: {csv_path}"
        )


def _columns(table: Dict[str, Any], rows: Iterable[Dict[str, Any]]) -> List[str]:
    columns: List[str] = []
    raw_columns = table.get("columns")
    if isinstance(raw_columns, list):
        for column in raw_columns:
            text = clean_text(column, 120)
            if text and text not in columns:
                columns.append(text)
    for row in rows:
        if not isinstance(row, dict):
            continue
        for column in row:
            text = clean_text(column, 120)
            if text and text not in columns:
                columns.append(text)
    return columns


def _competitor(row: Dict[str, Any]) -> str:
    for key in ("competitor", "竞品", "竞品名称", "产品", "产品名称", "competitor_name"):
        value = clean_text(row.get(key), 120)
        if value:
            return value
    return ""


def _evidence_ids(row: Dict[str, Any]) -> List[str]:
    for key in ("evidence_ids", "证据ID", "支持证据ID", "支撑证据ID", "关联证据ID"):
        value = row.get(key)
        if isinstance(value, list):
            return [clean_text(item, 80) for item in value if clean_text(item, 80)]
        if isinstance(value, str) and value.strip():
            return [clean_text(value, 120)]
    return []


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return clean_text(value, 500)


def _cell_id(table_name: str, row_index: int, column: str) -> str:
    raw = f"{table_name}|{row_index}|{column}"
    text = re.sub(r"\W+", "_", raw, flags=re.UNICODE).strip("_")
    return text[:120] or f"cell_{row_index}"


def _internal_column(column: str) -> bool:
    lowered = column.lower()
    return column == "pending_search_query" or lowered == "source_ids"


def _pending_or_blank(value: str) -> bool:
    text = clean_text(value, 500)
    return (
        not text
        or text.startswith("待搜索")
        or "未找到明确" in text
        or "暂未公开" in text
        or "未公开" in text
        or "未披露" in text
    )


def _safe_name(label: str) -> str:
    text = re.sub(r"\W+", "_", label, flags=re.UNICODE).strip("_")
    return text[:80] or "comparison_tables"

"""Search-backed enrichment for empty or weak comparison table cells."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

try:
    from .evidence_structurer import is_low_value_evidence_text
    from .llm_utils import call_json_llm, clean_text, valid_ids
    from .models import EvidenceCard, WritingAgentConfig
    from .search_adapter import ReportSearchConfig, search_queries_for_report
    from .table_debug import log_comparison_tables
    from .table_workspace import apply_cell_updates, pending_cell_payload
except ImportError:
    from report_agent.evidence_structurer import is_low_value_evidence_text
    from report_agent.llm_utils import call_json_llm, clean_text, valid_ids
    from report_agent.models import EvidenceCard, WritingAgentConfig
    from report_agent.search_adapter import ReportSearchConfig, search_queries_for_report
    from report_agent.table_debug import log_comparison_tables
    from report_agent.table_workspace import apply_cell_updates, pending_cell_payload


PENDING_SEARCH = "待搜索"
NO_PRODUCT_EVIDENCE = "未找到明确产品级证据"


@dataclass
class TableGap:
    """A missing comparison-table fact that may need targeted search."""

    gap_id: str
    table_name: str
    competitor: str = ""
    dimension: str = ""
    field: str = ""
    row_index: int = -1
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "table_name": self.table_name,
            "competitor": self.competitor,
            "dimension": self.dimension,
            "field": self.field,
            "row_index": self.row_index,
            "reason": self.reason,
        }


def enrich_tables_with_gap_search(
    *,
    profiles: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
    evidence_cards: List[EvidenceCard],
    competitors: Sequence[str],
    target_domain: str,
    config: WritingAgentConfig,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Mark table gaps as pending, optionally search, then LLM-fill from results."""

    if not _can_use_planning_llm(config):
        marked_profiles = _mark_profile_gaps(profiles, competitors)
        marked_tables = _mark_table_gaps(tables, competitors)
        gaps = _collect_gaps(marked_profiles, marked_tables, competitors)
        if not gaps:
            return _strip_internal_fields(marked_profiles, marked_tables, finalize_pending=False)
        _log(config, f"[writing-agent] table gaps need search: {len(gaps)}")
        queries = _fallback_gap_queries(
            gaps,
            target_domain,
            max(1, len(gaps)),
        )
        _attach_pending_queries(marked_profiles, marked_tables, gaps, queries)
        _embed_pending_directions(marked_profiles, marked_tables, gaps, queries)
        _log(config, "[writing-agent] no LLM for table gap search; keeping 待搜索 markers")
        return _strip_internal_fields(marked_profiles, marked_tables, finalize_pending=False)

    marked_profiles = [dict(item) for item in profiles]
    marked_tables = [dict(item) for item in tables]
    max_rounds = max(1, int(getattr(config, "table_gap_search_max_rounds", 3) or 3))
    searched_any = False
    gap_attempts: Dict[Tuple[str, int, str, str], int] = {}
    searched_queries: Set[str] = set()
    for round_index in range(1, max_rounds + 1):
        _log(config, f"[writing-agent] audit comparison tables round {round_index}/{max_rounds}")
        marked_profiles, marked_tables, changed, searched = _run_gap_search_round(
            profiles=marked_profiles,
            tables=marked_tables,
            evidence_cards=evidence_cards,
            competitors=competitors,
            target_domain=target_domain,
            config=config,
            gap_attempts=gap_attempts,
            searched_queries=searched_queries,
        )
        searched_any = searched_any or searched
        if not _contains_pending_outputs(marked_profiles, marked_tables):
            break
        if not changed and not searched:
            break
    return _strip_internal_fields(
        marked_profiles,
        marked_tables,
        finalize_pending=searched_any,
    )


def _run_gap_search_round(
    *,
    profiles: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
    evidence_cards: List[EvidenceCard],
    competitors: Sequence[str],
    target_domain: str,
    config: WritingAgentConfig,
    gap_attempts: Dict[Tuple[str, int, str, str], int],
    searched_queries: Set[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool, bool]:
    all_pending = _search_all_pending(config)
    seed_profiles = _mark_profile_gaps(profiles, competitors)
    seed_tables = _mark_table_gaps(tables, competitors)
    seed_gaps = _collect_gaps(seed_profiles, seed_tables, competitors)
    if not seed_gaps:
        return seed_profiles, seed_tables, False, False
    audit_gaps, llm_queries = _audit_table_gaps_with_llm(
        gaps=seed_gaps,
        profiles=seed_profiles,
        tables=seed_tables,
        evidence_cards=evidence_cards,
        competitors=competitors,
        target_domain=target_domain,
        config=config,
    )
    raw_gaps = seed_gaps if all_pending else (_searchable_audit_gaps(audit_gaps, seed_gaps) or seed_gaps)
    gaps, gap_id_map = _renumber_gaps(raw_gaps)
    llm_queries = _remap_query_ids(llm_queries, gap_id_map)
    query_limit = _gap_query_budget(config, len(gaps))
    if not all_pending:
        gaps = _limit_gaps_by_query_budget(gaps, query_limit)
    if not gaps:
        return profiles, tables, False, False
    allowed_gap_ids = {gap.gap_id for gap in gaps}
    llm_queries = {
        gap_id: query
        for gap_id, query in llm_queries.items()
        if gap_id in allowed_gap_ids
    }
    marked_profiles = _apply_audit_gaps_to_profiles(seed_profiles, gaps)
    marked_tables = _apply_audit_gaps_to_tables(seed_tables, gaps)
    _log(config, f"[writing-agent] table gaps need search: {len(gaps)}")
    if not llm_queries:
        llm_queries = _plan_gap_search_queries(
            gaps=gaps,
            profiles=marked_profiles,
            tables=marked_tables,
            evidence_cards=evidence_cards,
            competitors=competitors,
            target_domain=target_domain,
            config=config,
        )
    display_queries = _merge_gap_queries(
        primary=llm_queries,
        fallback=_fallback_gap_queries(gaps, target_domain, max(1, len(gaps))),
        max_unique=query_limit,
    )
    queries = display_queries if all_pending else _limit_query_map(display_queries, query_limit)
    if searched_queries:
        before_query_count = len({query for query in queries.values() if query})
        retry_queries = _rewrite_repeated_gap_queries(
            gaps,
            target_domain,
            queries,
            searched_queries,
            config,
        )
        queries = {
            gap_id: retry_queries.get(gap_id, query)
            for gap_id, query in queries.items()
            if query in searched_queries and retry_queries.get(gap_id)
        } | {
            gap_id: query
            for gap_id, query in queries.items()
            if query and query not in searched_queries
        }
        queries = {
            gap_id: query
            for gap_id, query in queries.items()
            if query and query not in searched_queries
        }
        skipped_query_count = before_query_count - len({query for query in queries.values() if query})
        if skipped_query_count:
            _log(config, f"[writing-agent] rewrite already searched table queries: {skipped_query_count}")
    _attach_pending_queries(marked_profiles, marked_tables, gaps, display_queries)
    _embed_pending_directions(marked_profiles, marked_tables, gaps, display_queries)

    if not getattr(config, "table_gap_search_enabled", True):
        _log(config, "[writing-agent] table gap search disabled; leaving 待搜索 markers")
        return marked_profiles, marked_tables, False, False
    if not queries:
        _log(config, "[writing-agent] no table gap search queries generated")
        return marked_profiles, marked_tables, False, False

    _log_gap_queries(config, queries)
    attempted_gap_ids = set(queries.keys())
    for gap in gaps:
        if gap.gap_id in attempted_gap_ids:
            key = _gap_key(gap)
            gap_attempts[key] = gap_attempts.get(key, 0) + 1
    searched_queries.update(query for query in queries.values() if query)
    results = _run_gap_search(queries, config)
    if not results:
        _log(config, "[writing-agent] table gap search returned no usable results")
        return marked_profiles, marked_tables, False, True

    _log(config, "[writing-agent] fill table gaps from search results")
    before_pending = _pending_count(marked_profiles) + _pending_count(marked_tables)
    filled_profiles, filled_tables = _fill_gaps_from_search_results(
        profiles=marked_profiles,
        tables=marked_tables,
        gaps=gaps,
        queries=queries,
        search_results=results,
        competitors=competitors,
        target_domain=target_domain,
        config=config,
    )
    if filled_profiles and filled_tables:
        after_pending = _pending_count(filled_profiles) + _pending_count(filled_tables)
        log_comparison_tables(config, "comparison tables after search fill", filled_tables)
        return filled_profiles, filled_tables, after_pending < before_pending, True
    return marked_profiles, marked_tables, False, True


def _mark_profile_gaps(
    profiles: List[Dict[str, Any]],
    competitors: Sequence[str],
) -> List[Dict[str, Any]]:
    rows = [dict(profile) for profile in profiles if isinstance(profile, dict)]
    by_competitor = {_norm(row.get("competitor")): row for row in rows}
    for competitor in competitors:
        key = _norm(competitor)
        if key and key not in by_competitor:
            row = {"competitor": competitor}
            rows.append(row)
            by_competitor[key] = row

    for row in rows:
        for field in (
            "target_user",
            "core_scenario",
            "product_form",
            "main_entry",
            "business_model",
            "strategic_judgement",
        ):
            if _is_missing(row.get(field)):
                row[field] = PENDING_SEARCH
        if not isinstance(row.get("evidence_ids"), list):
            row["evidence_ids"] = []
    return rows


def _mark_table_gaps(
    tables: List[Dict[str, Any]],
    competitors: Sequence[str],
) -> List[Dict[str, Any]]:
    marked: List[Dict[str, Any]] = []
    for raw_table in tables:
        if not isinstance(raw_table, dict):
            continue
        table = dict(raw_table)
        name = table.get("table_name")
        if name == "competitor_positioning_matrix":
            table["rows"] = _mark_positioning_rows(table.get("rows"), competitors)
        elif name == "agent_capability_scorecard":
            table["scoring_rule"] = table.get("scoring_rule") or (
                "0=无能力，1=Demo级，2=简单可用，3=业务可用，4=规模部署，5=成熟壁垒"
            )
            table["dimensions"] = _mark_scorecard_rows(
                table.get("dimensions"), competitors
            )
        elif name == "user_journey_comparison":
            table["rows"] = _mark_journey_rows(table.get("rows"))
        else:
            rows_key = "rows" if isinstance(table.get("rows"), list) else "dimensions"
            rows = table.get(rows_key)
            columns = _generic_columns(table)
            if isinstance(rows, list):
                table[rows_key] = _mark_generic_rows(
                    rows,
                    columns=columns,
                    competitors=competitors,
                    table_name=clean_text(name, 80) or "横向对比表",
                )
            elif columns:
                table["rows"] = _mark_generic_rows(
                    [],
                    columns=columns,
                    competitors=competitors,
                    table_name=clean_text(name, 80) or "横向对比表",
                )
        marked.append(table)
    if marked:
        return marked

    for name in [
        "competitor_positioning_matrix",
        "agent_capability_scorecard",
        "user_journey_comparison",
    ]:
        table = {"table_name": name}
        if name == "competitor_positioning_matrix":
            table["rows"] = _mark_positioning_rows([], competitors)
        elif name == "agent_capability_scorecard":
            table["scoring_rule"] = (
                "0=无能力，1=Demo级，2=简单可用，3=业务可用，4=规模部署，5=成熟壁垒"
            )
            table["dimensions"] = _mark_scorecard_rows([], competitors)
        else:
            table["rows"] = _mark_journey_rows([])
        marked.append(table)
    return marked


def _mark_generic_rows(
    rows: Any,
    *,
    columns: Sequence[str] | None = None,
    competitors: Sequence[str] = (),
    table_name: str = "横向对比表",
) -> List[Dict[str, Any]]:
    valid_rows = [dict(row) for row in rows or [] if isinstance(row, dict)]
    if not valid_rows:
        valid_rows = _generic_pending_rows(
            columns=columns or [],
            competitors=competitors,
            table_name=table_name,
        )
    else:
        valid_rows = _ensure_generic_competitor_rows(
            valid_rows,
            columns=columns or _columns_from_generic_rows(valid_rows),
            competitors=competitors,
            table_name=table_name,
        )
    for row in valid_rows:
        for column in columns or []:
            column = clean_text(column, 80)
            if column and column not in row and not _is_evidence_column(column):
                row[column] = PENDING_SEARCH
        for key, value in list(row.items()):
            if key in {"evidence_ids", "证据ID", "证据ids", "source_ids"}:
                continue
            if _is_missing(value):
                row[key] = PENDING_SEARCH
        if not any(key in row for key in ("evidence_ids", "证据ID")):
            row["evidence_ids"] = []
    return valid_rows


def _ensure_generic_competitor_rows(
    rows: List[Dict[str, Any]],
    *,
    columns: Sequence[str],
    competitors: Sequence[str],
    table_name: str,
) -> List[Dict[str, Any]]:
    competitor_column = _competitor_column(columns, rows)
    if not competitor_column:
        return rows
    existing = {
        _norm(_match_competitor(row.get(competitor_column), competitors) or row.get(competitor_column))
        for row in rows
        if isinstance(row, dict)
    }
    template_columns = list(columns) or _columns_from_generic_rows(rows)
    for competitor in competitors:
        name = clean_text(competitor, 80)
        if not name or _norm(name) in existing:
            continue
        row = _generic_pending_row_for_subject(
            columns=template_columns,
            competitor_column=competitor_column,
            subject=name,
            table_name=table_name,
        )
        rows.append(row)
        existing.add(_norm(name))
    return rows


def _competitor_column(
    columns: Sequence[str], rows: Sequence[Dict[str, Any]]
) -> str:
    candidates = {
        "竞品",
        "竞品名称",
        "产品",
        "产品名称",
        "competitor",
        "competitor_name",
        "product",
        "product_name",
    }
    for column in columns:
        text = clean_text(column, 80)
        if text in candidates:
            return text
    for row in rows:
        for key in row:
            text = clean_text(key, 80)
            if text in candidates:
                return text
    return ""


def _columns_from_generic_rows(rows: Sequence[Dict[str, Any]]) -> List[str]:
    columns: List[str] = []
    for row in rows:
        for key in row:
            text = clean_text(key, 80)
            if text and text not in columns and text != "pending_search_query":
                columns.append(text)
    return columns


def _is_evidence_column(column: str) -> bool:
    column = clean_text(column, 80)
    if "证据" in column or "evidence" in column.lower() or "source" in column.lower():
        return True
    return column in {
        "evidence_ids",
        "璇佹嵁ID",
        "璇佹嵁ids",
        "source_ids",
        "pending_search_query",
        "支持证据ID",
        "关联证据ID",
        "证据ID",
    }


def _generic_columns(table: Dict[str, Any]) -> List[str]:
    columns = table.get("columns")
    if isinstance(columns, list):
        return [
            clean_text(column, 80)
            for column in columns
            if clean_text(column, 80) and clean_text(column, 80) != "pending_search_query"
        ]
    rows = table.get("rows") if isinstance(table.get("rows"), list) else table.get("dimensions")
    values: List[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for key in row:
            text = clean_text(key, 80)
            if text and text not in values and text != "pending_search_query":
                values.append(text)
    return values


def _generic_pending_rows(
    *,
    columns: Sequence[str],
    competitors: Sequence[str],
    table_name: str,
) -> List[Dict[str, Any]]:
    visible_columns = [
        clean_text(column, 80)
        for column in columns
        if clean_text(column, 80)
        and clean_text(column, 80)
        not in {"evidence_ids", "证据ID", "证据ids", "source_ids", "pending_search_query"}
    ]
    if not visible_columns:
        visible_columns = ["竞品", "待补充信息"]
    competitor_column = _competitor_column(visible_columns, [])
    subjects = [clean_text(name, 80) for name in competitors if clean_text(name, 80)]
    if not competitor_column:
        subjects = [""]
    rows: List[Dict[str, Any]] = []
    for subject in subjects or [""]:
        rows.append(
            _generic_pending_row_for_subject(
                columns=visible_columns,
                competitor_column=competitor_column,
                subject=subject,
                table_name=table_name,
            )
        )
    return rows


def _generic_pending_row_for_subject(
    *,
    columns: Sequence[str],
    competitor_column: str,
    subject: str,
    table_name: str,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    for column in columns:
        if column in {"evidence_ids", "证据ID", "证据ids", "source_ids", "pending_search_query"}:
            continue
        if competitor_column and column == competitor_column:
            row[column] = subject or PENDING_SEARCH
            continue
        query_subject = subject or table_name
        row[column] = (
            f"{PENDING_SEARCH}（方向：{query_subject} {column}；"
            f"关键词：{query_subject} {column} 官方文档）"
        )
    row["evidence_ids"] = []
    return row


def _mark_positioning_rows(
    rows: Any,
    competitors: Sequence[str],
) -> List[Dict[str, Any]]:
    valid_rows = [dict(row) for row in rows or [] if isinstance(row, dict)]
    by_competitor = {_norm(row.get("competitor")): row for row in valid_rows}
    for competitor in competitors:
        key = _norm(competitor)
        if key and key not in by_competitor:
            row = {"competitor": competitor}
            valid_rows.append(row)
            by_competitor[key] = row
    for row in valid_rows:
        for field in (
            "target_user",
            "core_scenario",
            "product_form",
            "main_entry",
            "business_model",
            "strategic_judgement",
        ):
            if _is_missing(row.get(field)):
                row[field] = PENDING_SEARCH
        if not isinstance(row.get("evidence_ids"), list):
            row["evidence_ids"] = []
    return valid_rows


def _mark_scorecard_rows(
    rows: Any,
    competitors: Sequence[str],
) -> List[Dict[str, Any]]:
    valid_rows = [dict(row) for row in rows or [] if isinstance(row, dict)]
    if not valid_rows:
        valid_rows = [
            {"dimension": "任务规划", "weight": 0.18},
            {"dimension": "Tool Use / 集成", "weight": 0.16},
            {"dimension": "Agent 核心能力", "weight": 0.20},
            {"dimension": "信任与控制", "weight": 0.18},
            {"dimension": "用户体验", "weight": 0.14},
            {"dimension": "商业化与壁垒", "weight": 0.14},
        ]

    for row in valid_rows:
        if _is_missing(row.get("dimension")):
            row["dimension"] = PENDING_SEARCH
        raw_scores = row.get("scores")
        scores = dict(raw_scores) if isinstance(raw_scores, dict) else {}
        reason_missing = _is_missing(row.get("reason"))
        evidence_ids = row.get("evidence_ids") if isinstance(row.get("evidence_ids"), list) else []
        for competitor in competitors:
            value = scores.get(competitor)
            if _is_missing(value):
                scores[competitor] = PENDING_SEARCH
        row["scores"] = scores
        if reason_missing or _scorecard_reason_is_single_competitor(
            row.get("reason"), competitors
        ):
            row["reason"] = PENDING_SEARCH
            row["evidence_ids"] = []
        elif not isinstance(row.get("evidence_ids"), list):
            row["evidence_ids"] = []
    return valid_rows


def _mark_journey_rows(rows: Any) -> List[Dict[str, Any]]:
    valid_rows = [dict(row) for row in rows or [] if isinstance(row, dict)]
    if not valid_rows:
        valid_rows = [
            {"stage": "发现与评估"},
            {"stage": "创建 Agent"},
            {"stage": "授权与集成"},
            {"stage": "执行任务"},
            {"stage": "结果交付"},
        ]
    for row in valid_rows:
        if _is_missing(row.get("stage")):
            row["stage"] = PENDING_SEARCH
        for field in ("user_goal", "competitor_experience", "opportunity"):
            if _is_missing(row.get(field)):
                row[field] = PENDING_SEARCH
        if not isinstance(row.get("evidence_ids"), list):
            row["evidence_ids"] = []
    return valid_rows


def _collect_gaps(
    profiles: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
    competitors: Sequence[str],
) -> List[TableGap]:
    gaps: List[TableGap] = []

    def add(
        table_name: str,
        *,
        competitor: str = "",
        dimension: str = "",
        field: str = "",
        row_index: int = -1,
        reason: str = "",
    ) -> None:
        gaps.append(
            TableGap(
                gap_id=f"gap_{len(gaps) + 1:03d}",
                table_name=table_name,
                competitor=competitor,
                dimension=dimension,
                field=field,
                row_index=row_index,
                reason=reason,
            )
        )

    for index, profile in enumerate(profiles):
        competitor = clean_text(profile.get("competitor"), 80)
        for field in (
            "target_user",
            "core_scenario",
            "product_form",
            "main_entry",
            "business_model",
            "strategic_judgement",
        ):
            if _is_pending(profile.get(field)):
                add(
                    "competitor_profiles",
                    competitor=competitor,
                    field=field,
                    row_index=index,
                    reason="竞品画像字段缺少可用证据",
                )

    for table in tables:
        name = table.get("table_name")
        if name == "competitor_positioning_matrix":
            for index, row in enumerate(table.get("rows") or []):
                if not isinstance(row, dict):
                    continue
                competitor = clean_text(row.get("competitor"), 80)
                for field in (
                    "target_user",
                    "core_scenario",
                    "product_form",
                    "main_entry",
                    "business_model",
                    "strategic_judgement",
                ):
                    if _is_pending(row.get(field)):
                        add(
                            name,
                            competitor=competitor,
                            field=field,
                            row_index=index,
                            reason="定位矩阵字段缺少可用证据",
                        )
        elif name == "agent_capability_scorecard":
            for index, row in enumerate(table.get("dimensions") or []):
                if not isinstance(row, dict):
                    continue
                dimension = clean_text(row.get("dimension"), 80)
                scores = row.get("scores") if isinstance(row.get("scores"), dict) else {}
                for competitor in competitors:
                    if _is_pending(scores.get(competitor)):
                        add(
                            name,
                            competitor=competitor,
                            dimension=dimension,
                            field="score",
                            row_index=index,
                            reason="能力评分缺少竞品证据",
                        )
                if _is_pending(row.get("reason")):
                    add(
                        name,
                        dimension=dimension,
                        field="reason",
                        row_index=index,
                        reason="评分理由缺少可用证据",
                    )
        elif name == "user_journey_comparison":
            for index, row in enumerate(table.get("rows") or []):
                if not isinstance(row, dict):
                    continue
                stage = clean_text(row.get("stage"), 80)
                for field in ("user_goal", "competitor_experience", "opportunity"):
                    if _is_pending(row.get(field)):
                        add(
                            name,
                            dimension=stage,
                            field=field,
                            row_index=index,
                            reason="用户旅程字段缺少可用证据",
                        )
        else:
            rows = table.get("rows") if isinstance(table.get("rows"), list) else table.get("dimensions")
            if not isinstance(rows, list):
                continue
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                competitor = _row_competitor(row, competitors)
                for field, value in row.items():
                    if field in {"evidence_ids", "证据ID", "source_ids"}:
                        continue
                    if _is_pending(value) or _is_missing(value):
                        add(
                            clean_text(name, 80) or "comparison_table",
                            competitor=competitor,
                            dimension=clean_text(row.get("维度") or row.get("dimension"), 80),
                            field=str(field),
                            row_index=index,
                            reason="自由表格字段缺少可用证据",
                        )
    return gaps


def _row_competitor(row: Dict[str, Any], competitors: Sequence[str]) -> str:
    for key in ("competitor", "竞品", "产品", "产品名称"):
        matched = _match_competitor(row.get(key), competitors)
        if matched:
            return matched
    text = " ".join(clean_text(value, 80) for value in row.values())
    return _match_competitor(text, competitors)


def _audit_table_gaps_with_llm(
    *,
    gaps: List[TableGap],
    profiles: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
    evidence_cards: List[EvidenceCard],
    competitors: Sequence[str],
    target_domain: str,
    config: WritingAgentConfig,
) -> Tuple[List[TableGap], Dict[str, str]]:
    if not _can_use_planning_llm(config):
        return [], {}
    max_queries = _gap_query_budget(config, len(gaps))
    data = call_json_llm(
        config=config,
        system_prompt="你是竞品表格质检与检索规划专家，只输出 JSON。",
        user_prompt=f"""
目标领域:
{target_domain}

候选竞品:
{json.dumps(list(competitors), ensure_ascii=False)}

当前竞品画像:
{json.dumps(profiles, ensure_ascii=False, indent=2)}

当前对比表:
{json.dumps(tables, ensure_ascii=False, indent=2)}

程序已发现的待搜索缺口:
{json.dumps([gap.to_dict() for gap in gaps], ensure_ascii=False, indent=2)}

Evidence 摘要:
{json.dumps(_evidence_summary(evidence_cards), ensure_ascii=False, indent=2)}

请审计整张表，提取需要重新搜索/回填的位置。你需要发现:
- 单元格为空、待搜索、未找到明确证据。
- 单元格错栏，例如“产品定位”写到目标用户，“特色功能集”写到核心场景，“代码示例/快捷键/教程”写到主要入口。
- agent_capability_scorecard 的 reason 过长、只引用某一个竞品却代表整行、或包含教程/代码片段。
- scores 有分数但对应 reason/evidence 不足，应该搜索对应竞品和维度。
- 不要为“关联证据ID、ev_001 校验、回填修正、剔除无关片段”生成公网搜索词；这类是内部清洗/自检任务，不是外部事实缺口。

返回最多 {max_queries} 个搜索任务，但 gaps 可以多于搜索任务，多个 gap 可共用 query。
table_name 必须取自当前对比表里的原始 table_name；竞品画像使用 competitor_profiles。
field 必须是当前行里真实存在的字段名，可以是中文表头；不要凭空发明 pending_search_query 这类内部字段。
row_index 使用当前表 rows/dimensions 的 0 基下标。自由表格也要审计，不要只看固定三张表。

返回严格 JSON:
{{
  "gaps": [
    {{
      "gap_id": "gap_a001",
      "table_name": "产品形态与入口对比",
      "row_index": 0,
      "competitor": "OpenCode",
      "dimension": "",
      "field": "主要入口",
      "reason": "主要入口里混入代码示例和快捷键教程"
    }}
  ],
  "queries": [
    {{
      "query": "OpenCode 产品形态 主要入口 TUI desktop IDE extension official",
      "gap_ids": ["gap_a001"]
    }}
  ]
}}
""".strip(),
    )
    if not isinstance(data, dict):
        return [], {}

    audit_gaps = _parse_audit_gaps(data.get("gaps"), competitors)
    known_gap_ids = {gap.gap_id for gap in audit_gaps}
    query_map: Dict[str, str] = {}
    for item in data.get("queries") or []:
        if not isinstance(item, dict):
            continue
        query = clean_text(item.get("query"), 180)
        if not query:
            continue
        ids = valid_ids(item.get("gap_ids"), known_gap_ids)
        for gap_id in ids:
            query_map.setdefault(gap_id, query)
    return audit_gaps, query_map


def _parse_audit_gaps(raw_gaps: Any, competitors: Sequence[str]) -> List[TableGap]:
    gaps: List[TableGap] = []
    for index, raw in enumerate(raw_gaps or [], 1):
        if not isinstance(raw, dict):
            continue
        table_name = clean_text(raw.get("table_name"), 80)
        field = clean_text(raw.get("field"), 80)
        if not table_name or not field:
            continue
        competitor = _match_competitor(raw.get("competitor"), competitors)
        try:
            row_index = int(raw.get("row_index", -1))
        except (TypeError, ValueError):
            row_index = -1
        gaps.append(
            TableGap(
                gap_id=clean_text(raw.get("gap_id"), 40) or f"gap_a{index:03d}",
                table_name=table_name,
                competitor=competitor,
                dimension=clean_text(raw.get("dimension"), 80),
                field=field,
                row_index=row_index,
                reason=clean_text(raw.get("reason"), 160),
            )
        )
    return gaps


def _renumber_gaps(gaps: List[TableGap]) -> Tuple[List[TableGap], Dict[str, str]]:
    id_map: Dict[str, str] = {}
    for index, gap in enumerate(gaps, 1):
        old_id = gap.gap_id
        gap.gap_id = f"gap_{index:03d}"
        if old_id:
            id_map[old_id] = gap.gap_id
    return gaps, id_map


def _searchable_audit_gaps(
    audit_gaps: List[TableGap],
    seed_gaps: List[TableGap],
) -> List[TableGap]:
    if not audit_gaps:
        return []
    seed_keys = {_gap_key(gap) for gap in seed_gaps}
    return [gap for gap in audit_gaps if _gap_key(gap) in seed_keys]


def _gap_key(gap: TableGap) -> Tuple[str, int, str, str]:
    return (
        gap.table_name,
        gap.row_index,
        clean_text(gap.field, 80),
        clean_text(gap.competitor, 80),
    )


def _limit_gaps_by_query_budget(gaps: List[TableGap], query_limit: int) -> List[TableGap]:
    if len(gaps) <= query_limit:
        return gaps
    priority_fields = {
        "target_user",
        "core_scenario",
        "product_form",
        "main_entry",
        "business_model",
        "strategic_judgement",
        "目标用户",
        "核心场景",
        "产品形态",
        "主要入口",
        "商业模式",
        "战略判断",
    }
    prioritized = sorted(
        gaps,
        key=lambda gap: (
            0 if gap.field in priority_fields else 1,
            1 if gap.field == "reason" else 0,
            gap.gap_id,
        ),
    )
    return prioritized[:query_limit]


def _search_all_pending(config: WritingAgentConfig) -> bool:
    return bool(getattr(config, "table_gap_search_all_pending", True))


def _gap_query_budget(config: WritingAgentConfig, gap_count: int) -> int:
    if _search_all_pending(config):
        return max(1, int(gap_count or 1))
    return max(1, int(getattr(config, "table_gap_search_max_queries", 12) or 12))


def _remap_query_ids(query_map: Dict[str, str], id_map: Dict[str, str]) -> Dict[str, str]:
    if not query_map or not id_map:
        return query_map
    remapped: Dict[str, str] = {}
    for gap_id, query in query_map.items():
        remapped_id = id_map.get(gap_id, gap_id)
        if remapped_id:
            remapped.setdefault(remapped_id, query)
    return remapped


def _apply_audit_gaps_to_profiles(
    profiles: List[Dict[str, Any]], gaps: List[TableGap]
) -> List[Dict[str, Any]]:
    for gap in gaps:
        if gap.table_name != "competitor_profiles":
            continue
        if 0 <= gap.row_index < len(profiles):
            _set_gap_field(profiles[gap.row_index], gap)
    return profiles


def _apply_audit_gaps_to_tables(
    tables: List[Dict[str, Any]], gaps: List[TableGap]
) -> List[Dict[str, Any]]:
    for gap in gaps:
        if gap.table_name == "competitor_profiles":
            continue
        table = _table_by_name(tables, gap.table_name)
        if not table:
            continue
        rows = (
            table.get("dimensions")
            if gap.table_name == "agent_capability_scorecard"
            else table.get("rows")
        )
        if not isinstance(rows, list) and isinstance(table.get("dimensions"), list):
            rows = table.get("dimensions")
        if not isinstance(rows, list) or not (0 <= gap.row_index < len(rows)):
            continue
        row = rows[gap.row_index]
        if isinstance(row, dict):
            _set_gap_field(row, gap)
    return tables


def _set_gap_field(row: Dict[str, Any], gap: TableGap) -> None:
    if gap.field == "score":
        scores = row.get("scores")
        if isinstance(scores, dict) and gap.competitor:
            scores[gap.competitor] = PENDING_SEARCH
        return
    field = _resolve_row_field(gap.field, row)
    if not field:
        return
    gap.field = field
    row[field] = PENDING_SEARCH
    if gap.field == "reason" or gap.table_name == "agent_capability_scorecard":
        row["evidence_ids"] = []


def _resolve_row_field(field: str, row: Dict[str, Any]) -> str:
    if field in row:
        return field
    matched = _match_row_key(field, row)
    if matched:
        return matched
    alias = _field_alias(field)
    if alias and alias in row:
        return alias
    if alias:
        matched = _match_row_key(alias, row)
        if matched:
            return matched
    return ""


def _match_row_key(field: str, row: Dict[str, Any]) -> str:
    lowered = clean_text(field, 80).lower()
    for key in row:
        key_text = clean_text(key, 80)
        if lowered == key_text.lower():
            return str(key)
    for key in row:
        key_text = clean_text(key, 80)
        if lowered and (lowered in key_text.lower() or key_text.lower() in lowered):
            return str(key)
    return ""


def _field_alias(field: str) -> str:
    aliases = {
        "target_user": "目标用户",
        "core_scenario": "核心场景",
        "product_form": "产品形态",
        "main_entry": "主要入口",
        "business_model": "商业模式",
        "strategic_judgement": "战略判断",
        "reason": "依据",
        "user_goal": "用户目标",
        "competitor_experience": "竞品体验",
        "opportunity": "机会点",
        "competitor": "竞品",
        "dimension": "维度",
        "stage": "阶段",
    }
    return aliases.get(clean_text(field, 80), "")


def _plan_gap_search_queries(
    *,
    gaps: List[TableGap],
    profiles: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
    evidence_cards: List[EvidenceCard],
    competitors: Sequence[str],
    target_domain: str,
    config: WritingAgentConfig,
) -> Dict[str, str]:
    max_queries = _gap_query_budget(config, len(gaps))
    if not _can_use_planning_llm(config):
        return _fallback_gap_queries(gaps, target_domain, max_queries)

    data = call_json_llm(
        config=config,
        system_prompt="你是竞品表格缺口搜索词规划器，只输出 JSON。",
        user_prompt=f"""
目标领域:
{target_domain}

候选竞品:
{json.dumps(list(competitors), ensure_ascii=False)}

已有表格，待搜索位置已标为“待搜索”:
{json.dumps({"competitor_profiles": profiles, "comparison_tables": tables}, ensure_ascii=False, indent=2)}

缺口列表:
{json.dumps([gap.to_dict() for gap in gaps], ensure_ascii=False, indent=2)}

已有 EvidenceCard 摘要:
{json.dumps(_evidence_summary(evidence_cards), ensure_ascii=False, indent=2)}

请为最关键的缺口生成最多 {max_queries} 个搜索关键词。要求:
- 关键词要能搜到产品级事实，优先官方文档、定价页、发布说明、可信评测。
- 不要搜安装命令、Dockerfile、脚本、模板、OpenSpec、brainstorm、write-plan。
- 不要生成“关联证据ID、证据校验、ev_001、回填校验、剔除无关片段”这类内部处理查询；这类问题应通过已有 evidence_ids 自检，不走公网搜索。
- 每条 query 尽量包含竞品名和需要补的维度/字段。
- gap_ids 可以覆盖多个缺口。

返回严格 JSON:
{{
  "queries": [
    {{"query": "OpenCode AI coding agent features pricing model support", "gap_ids": ["gap_001"]}}
  ]
}}
""".strip(),
    )
    if not isinstance(data, dict):
        return _fallback_gap_queries(gaps, target_domain, max_queries)
    query_map: Dict[str, str] = {}
    known_gap_ids = {gap.gap_id for gap in gaps}
    for item in data.get("queries") or []:
        if not isinstance(item, dict):
            continue
        query = _clean_search_query(item.get("query"))
        if not query:
            continue
        ids = valid_ids(item.get("gap_ids"), known_gap_ids)
        if not ids:
            ids = [gap.gap_id for gap in gaps[:1]]
        for gap_id in ids:
            if gap_id not in query_map:
                query_map[gap_id] = query
    if query_map:
        return query_map
    return _fallback_gap_queries(gaps, target_domain, max_queries)


def _fallback_gap_queries(
    gaps: Sequence[TableGap],
    target_domain: str,
    max_queries: int,
) -> Dict[str, str]:
    query_map: Dict[str, str] = {}
    for gap in gaps:
        parts = [
            gap.competitor,
            target_domain,
            _query_label(gap.table_name, gap.field, gap.dimension),
            "官方文档 定价 功能 评测 发布说明",
        ]
        query = clean_text(" ".join(part for part in parts if part), 180)
        query = _clean_search_query(query)
        if not query:
            continue
        query_map[gap.gap_id] = query
    return query_map


def _rewrite_repeated_gap_queries(
    gaps: Sequence[TableGap],
    target_domain: str,
    query_map: Dict[str, str],
    searched_queries: Set[str],
    config: WritingAgentConfig,
) -> Dict[str, str]:
    repeated = {
        gap_id: query
        for gap_id, query in query_map.items()
        if query and query in searched_queries
    }
    if not repeated:
        return {}
    gap_by_id = {gap.gap_id: gap for gap in gaps}
    if _can_use_planning_llm(config):
        data = call_json_llm(
            config=config,
            system_prompt="你是搜索关键词改写器，只输出 JSON。",
            user_prompt=f"""
目标领域:
{target_domain}

下面这些搜索关键词上一轮没有让表格缺口成功回填。请为每一条生成一个极其相似、但字面不同的新搜索关键词。

要求:
- 保留竞品名称和要查的字段/维度。
- 不要扩大成泛泛竞品调研。
- 不要搜索 evidence_id、关联证据、校验回填、内部清洗任务。
- 新 query 不能与 old_query 完全相同。
- 每个 gap_id 返回 1 个 query。

缺口与旧关键词:
{json.dumps([
    {
        "gap_id": gap_id,
        "old_query": query,
        "gap": gap_by_id.get(gap_id).to_dict() if gap_by_id.get(gap_id) else {},
    }
    for gap_id, query in repeated.items()
], ensure_ascii=False, indent=2)}

返回严格 JSON:
{{"queries": [{{"gap_id": "gap_001", "query": "new similar query"}}]}}
""".strip(),
        )
        rewritten: Dict[str, str] = {}
        if isinstance(data, dict):
            for item in data.get("queries") or []:
                if not isinstance(item, dict):
                    continue
                gap_id = clean_text(item.get("gap_id"), 40)
                query = _clean_search_query(item.get("query"))
                if (
                    gap_id in repeated
                    and query
                    and query != repeated[gap_id]
                    and query not in searched_queries
                ):
                    rewritten[gap_id] = query
        if rewritten:
            return rewritten

    rewritten = {}
    for gap_id, old_query in repeated.items():
        gap = gap_by_id.get(gap_id)
        suffix = _retry_query_suffix(gap)
        query = _clean_search_query(clean_text(f"{old_query} {suffix}", 180))
        if query and query != old_query and query not in searched_queries:
            rewritten[gap_id] = query
    return rewritten


def _retry_query_suffix(gap: Optional[TableGap]) -> str:
    if not gap:
        return "official docs"
    field = clean_text(gap.field, 80)
    dimension = clean_text(gap.dimension, 80)
    if "price" in field.lower() or "定价" in field or "套餐" in field:
        return "pricing page plans official"
    if "安全" in field or "合规" in field or "security" in field.lower():
        return "security privacy compliance official"
    if "用户" in field or "场景" in field:
        return "use cases target users official"
    if dimension:
        return f"{dimension} official documentation"
    return "official documentation release notes"


def _clean_search_query(value: Any) -> str:
    query = clean_text(value, 180)
    if not query:
        return ""
    lowered = query.lower()
    internal_markers = [
        "关联证据",
        "证据id",
        "evidence_id",
        "校验回填",
        "校验修正",
        "有效信息提取",
        "剔除无关",
        "对齐官方画像证据列表",
    ]
    if any(marker.lower() in lowered for marker in internal_markers):
        return ""
    if re.search(r"\bev_\d{3,}\b", lowered):
        return ""
    return query


def _run_gap_search(query_map: Dict[str, str], config: WritingAgentConfig) -> List[Dict[str, Any]]:
    unique_queries: List[str] = []
    for query in query_map.values():
        if query and query not in unique_queries:
            unique_queries.append(query)
    if not unique_queries:
        return []

    search_config = ReportSearchConfig.from_env()
    search_config.source = clean_text(getattr(config, "search_source", ""), 40) or search_config.source
    search_config.bocha_api_key = (
        clean_text(getattr(config, "search_bocha_api_key", ""), 200)
        or search_config.bocha_api_key
    )
    search_config.google_api_key = (
        clean_text(getattr(config, "search_google_api_key", ""), 200)
        or search_config.google_api_key
    )
    search_config.google_cx_id = (
        clean_text(getattr(config, "search_google_cx_id", ""), 200)
        or search_config.google_cx_id
    )
    search_config.proxy = (
        clean_text(getattr(config, "search_proxy", ""), 400)
        or search_config.proxy
        or None
    )
    search_config.crawl_backend = int(
        getattr(config, "search_backend", search_config.crawl_backend) or 0
    )
    search_config.query_count = (
        len(unique_queries)
        if _search_all_pending(config)
        else min(
            len(unique_queries),
            max(1, int(getattr(config, "table_gap_search_max_queries", 12) or 12)),
        )
    )
    search_config.workers = max(0, int(getattr(config, "table_gap_search_workers", 0) or 0))
    result_count = max(1, int(getattr(config, "table_gap_search_results_per_query", 3) or 3))
    search_config.results_per_query = result_count
    search_config.max_search_results = result_count
    search_config.crawl_max_chars = max(
        0,
        int(getattr(config, "table_gap_search_crawl_max_chars", 2500) or 2500),
    )
    search_config.crawl_min_chars = 120 if search_config.crawl_max_chars > 0 else 0
    search_config.timeout = max(
        3,
        int(getattr(config, "table_gap_search_timeout", 8) or 8),
    )
    search_config.gap_query_timeout = max(
        1,
        int(getattr(config, "table_gap_query_timeout", 45) or 45),
    )
    if search_config.crawl_max_chars <= 0:
        _log(config, "[writing-agent] table gap search uses search snippets only (crawl disabled)")
    else:
        _log(
            config,
            f"[writing-agent] table gap search crawls page text: max_chars={search_config.crawl_max_chars} timeout={search_config.timeout}s query_timeout={search_config.gap_query_timeout}s",
        )
    search_config.verbose = config.verbose
    search_config.progress_printer = config.progress_printer

    try:
        bundle = search_queries_for_report(unique_queries, config=search_config)
    except Exception as exc:
        _log(config, f"[writing-agent] table gap search failed: {exc}")
        return []

    payload: List[Dict[str, Any]] = []
    for index, result in enumerate(bundle.results, 1):
        payload.append(
            {
                "source_id": f"gap_src_{index:03d}",
                "title": clean_text(getattr(result, "title", ""), 180),
                "url": clean_text(getattr(result, "url", ""), 400),
                "snippet": clean_text(getattr(result, "snippet", ""), 700),
                "content": clean_text(getattr(result, "content", ""), 1400),
                "source": clean_text(getattr(result, "source", ""), 80),
            }
        )
    return payload


def _log_gap_queries(config: WritingAgentConfig, query_map: Dict[str, str]) -> None:
    unique_queries: List[str] = []
    for query in query_map.values():
        if query and query not in unique_queries:
            unique_queries.append(query)
    if not unique_queries:
        return
    _log(config, f"[writing-agent] table gap search queries: {len(unique_queries)}")
    for index, query in enumerate(unique_queries, 1):
        _log(config, f"[writing-agent] table gap query {index}: {query}")


def _fill_gaps_from_search_results(
    *,
    profiles: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
    gaps: List[TableGap],
    queries: Dict[str, str],
    search_results: List[Dict[str, Any]],
    competitors: Sequence[str],
    target_domain: str,
    config: WritingAgentConfig,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not _can_use_planning_llm(config):
        return profiles, tables
    pending_cells = pending_cell_payload(tables)
    data = call_json_llm(
        config=config,
        system_prompt="你是竞品表格搜索结果分析器，只输出 JSON。",
        user_prompt=f"""
目标领域:
{target_domain}

候选竞品:
{json.dumps(list(competitors), ensure_ascii=False)}

待回填表格:
{json.dumps({"competitor_profiles": profiles, "comparison_tables": tables}, ensure_ascii=False, indent=2)}

pending_cells:
{json.dumps(pending_cells, ensure_ascii=False, indent=2)}

缺口列表:
{json.dumps([gap.to_dict() for gap in gaps], ensure_ascii=False, indent=2)}

缺口对应搜索词:
{json.dumps(queries, ensure_ascii=False, indent=2)}

搜索结果:
{json.dumps(search_results, ensure_ascii=False, indent=2)}

请只基于搜索结果回填“待搜索”单元格。要求:
- 只能回填搜索结果明确支持的产品级事实；不能使用常识猜测。
- 如果仍然没有证据，保持“待搜索”。
- 不要写安装命令、Dockerfile、脚本、原始配置、代码片段、教程步骤。
- 保持原有表名、列名和行顺序，不要把自由表格改成固定模板。
- 自由表格的中文字段要原字段回填；不要新增 pending_search_query 等内部字段。
- agent_capability_scorecard 的 scores 只能包含候选竞品 key，分数 0-5；无证据保持“待搜索”。
- 单元格写产品级摘要，每格不超过 80 个中文字符。
- evidence_ids 使用搜索结果中的 source_id，例如 gap_src_001。

返回严格 JSON:
{{
  "cell_updates": [
    {{"cell_id": "xxx", "value": "基于搜索结果的产品级事实", "evidence_ids": ["gap_src_001"]}}
  ],
  "competitor_profiles": [],
  "comparison_tables": []
}}
""".strip(),
    )
    if not isinstance(data, dict):
        return profiles, tables
    cell_updates = data.get("cell_updates")
    if isinstance(cell_updates, list):
        apply_cell_updates(tables, cell_updates)
    filled_profiles = data.get("competitor_profiles")
    filled_tables = data.get("comparison_tables")
    if isinstance(filled_profiles, list) and isinstance(filled_tables, list):
        return _merge_filled_outputs(
            profiles=profiles,
            tables=tables,
            filled_profiles=filled_profiles,
            filled_tables=filled_tables,
            competitors=competitors,
        )
    return profiles, tables


def _merge_filled_outputs(
    *,
    profiles: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
    filled_profiles: List[Dict[str, Any]],
    filled_tables: List[Dict[str, Any]],
    competitors: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    merged_profiles = [dict(profile) for profile in profiles]
    profile_by_name = {
        _norm(profile.get("competitor")): profile
        for profile in merged_profiles
        if isinstance(profile, dict)
    }
    for raw in filled_profiles:
        if not isinstance(raw, dict):
            continue
        name = _match_competitor(raw.get("competitor"), competitors)
        target = profile_by_name.get(_norm(name))
        if not target:
            continue
        _merge_pending_text_fields(
            target,
            raw,
            [
                "target_user",
                "core_scenario",
                "product_form",
                "main_entry",
                "business_model",
                "strategic_judgement",
            ],
        )
        _merge_evidence_ids(target, raw)

    merged_tables = [dict(table) for table in tables]
    table_by_name = {
        table.get("table_name"): table
        for table in merged_tables
        if isinstance(table, dict) and table.get("table_name")
    }
    filled_by_name = {
        table.get("table_name"): table
        for table in filled_tables
        if isinstance(table, dict) and table.get("table_name")
    }

    _merge_positioning_table(
        table_by_name.get("competitor_positioning_matrix"),
        filled_by_name.get("competitor_positioning_matrix"),
        competitors,
    )
    _merge_scorecard_table(
        table_by_name.get("agent_capability_scorecard"),
        filled_by_name.get("agent_capability_scorecard"),
        competitors,
    )
    _merge_journey_table(
        table_by_name.get("user_journey_comparison"),
        filled_by_name.get("user_journey_comparison"),
    )
    _merge_generic_tables(
        merged_tables=merged_tables,
        filled_tables=filled_tables,
    )
    _drop_resolved_pending_queries(merged_profiles, merged_tables)
    return merged_profiles, merged_tables


def _merge_positioning_table(
    target_table: Any,
    raw_table: Any,
    competitors: Sequence[str],
) -> None:
    if not isinstance(target_table, dict) or not isinstance(raw_table, dict):
        return
    target_rows = target_table.get("rows")
    raw_rows = raw_table.get("rows")
    if not isinstance(target_rows, list) or not isinstance(raw_rows, list):
        return
    by_competitor = {
        _norm(row.get("competitor")): row for row in target_rows if isinstance(row, dict)
    }
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        name = _match_competitor(raw.get("competitor"), competitors)
        target = by_competitor.get(_norm(name))
        if not target:
            continue
        _merge_pending_text_fields(
            target,
            raw,
            [
                "target_user",
                "core_scenario",
                "product_form",
                "main_entry",
                "business_model",
                "strategic_judgement",
            ],
        )
        _merge_evidence_ids(target, raw)


def _merge_scorecard_table(
    target_table: Any,
    raw_table: Any,
    competitors: Sequence[str],
) -> None:
    if not isinstance(target_table, dict) or not isinstance(raw_table, dict):
        return
    target_rows = target_table.get("dimensions")
    raw_rows = raw_table.get("dimensions")
    if not isinstance(target_rows, list) or not isinstance(raw_rows, list):
        return
    by_dimension = {
        _norm(row.get("dimension")): row for row in target_rows if isinstance(row, dict)
    }
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        dimension = clean_text(raw.get("dimension"), 80)
        target = by_dimension.get(_norm(dimension))
        if not target:
            continue
        raw_scores = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
        target_scores = target.get("scores") if isinstance(target.get("scores"), dict) else {}
        for competitor in competitors:
            if not _is_pending(target_scores.get(competitor)):
                continue
            raw_value = None
            for key, value in raw_scores.items():
                if _match_competitor(key, competitors) == competitor:
                    raw_value = value
                    break
            score = _clean_score(raw_value)
            if score is not None:
                target_scores[competitor] = score
        target["scores"] = target_scores
        if _is_pending(target.get("reason")):
            reason = _usable_cell_text(raw.get("reason") or raw.get("理由"), 180)
            if reason:
                target["reason"] = reason
        _merge_evidence_ids(target, raw)


def _merge_journey_table(target_table: Any, raw_table: Any) -> None:
    if not isinstance(target_table, dict) or not isinstance(raw_table, dict):
        return
    target_rows = target_table.get("rows")
    raw_rows = raw_table.get("rows")
    if not isinstance(target_rows, list) or not isinstance(raw_rows, list):
        return
    by_stage = {
        _norm(row.get("stage")): row for row in target_rows if isinstance(row, dict)
    }
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        target = by_stage.get(_norm(raw.get("stage")))
        if not target:
            continue
        _merge_pending_text_fields(
            target,
            raw,
            ["user_goal", "competitor_experience", "opportunity"],
        )
        _merge_evidence_ids(target, raw)


def _merge_generic_tables(
    *,
    merged_tables: List[Dict[str, Any]],
    filled_tables: List[Dict[str, Any]],
) -> None:
    fixed_names = {
        "competitor_positioning_matrix",
        "agent_capability_scorecard",
        "user_journey_comparison",
    }
    filled_by_name = {
        table.get("table_name"): table
        for table in filled_tables
        if isinstance(table, dict) and table.get("table_name") not in fixed_names
    }
    for target_table in merged_tables:
        if not isinstance(target_table, dict):
            continue
        table_name = target_table.get("table_name")
        if table_name in fixed_names:
            continue
        raw_table = filled_by_name.get(table_name)
        if not isinstance(raw_table, dict):
            continue
        target_rows = _table_rows(target_table)
        raw_rows = _table_rows(raw_table)
        if not isinstance(target_rows, list) or not isinstance(raw_rows, list):
            continue
        for index, target in enumerate(target_rows):
            if not isinstance(target, dict) or index >= len(raw_rows):
                continue
            raw = raw_rows[index]
            if not isinstance(raw, dict):
                continue
            _merge_generic_row(target, raw)


def _table_rows(table: Dict[str, Any]) -> Any:
    if isinstance(table.get("rows"), list):
        return table.get("rows")
    if isinstance(table.get("dimensions"), list):
        return table.get("dimensions")
    return None


def _merge_generic_row(target: Dict[str, Any], raw: Dict[str, Any]) -> None:
    for field, target_value in list(target.items()):
        if field in {"pending_search_query", "evidence_ids", "证据ID", "证据ids", "source_ids"}:
            continue
        if isinstance(target_value, dict):
            raw_value = raw.get(field)
            if isinstance(raw_value, dict):
                for key, nested_value in raw_value.items():
                    if _is_pending(target_value.get(key)):
                        value = _usable_cell_text(nested_value, 180)
                        if value:
                            target_value[key] = value
            continue
        if not _is_pending(target_value):
            continue
        value = _usable_cell_text(raw.get(field), 180)
        if value:
            target[field] = value
    _merge_evidence_ids(target, raw)
    _merge_chinese_evidence_ids(target, raw)


def _merge_pending_text_fields(
    target: Dict[str, Any],
    raw: Dict[str, Any],
    fields: Sequence[str],
) -> None:
    for field in fields:
        if not _is_pending(target.get(field)):
            continue
        value = _usable_cell_text(raw.get(field), 180)
        if value:
            target[field] = value


def _merge_evidence_ids(target: Dict[str, Any], raw: Dict[str, Any]) -> None:
    values = raw.get("evidence_ids")
    if not isinstance(values, list):
        return
    current = target.setdefault("evidence_ids", [])
    if not isinstance(current, list):
        current = []
        target["evidence_ids"] = current
    for value in values:
        item = clean_text(value, 80)
        if item and item not in current:
            current.append(item)


def _merge_chinese_evidence_ids(target: Dict[str, Any], raw: Dict[str, Any]) -> None:
    values = raw.get("证据ID") or raw.get("证据ids")
    if not isinstance(values, list):
        return
    current = target.setdefault("证据ID", [])
    if not isinstance(current, list):
        current = []
        target["证据ID"] = current
    for value in values:
        item = clean_text(value, 80)
        if item and item not in current:
            current.append(item)


def _drop_resolved_pending_queries(
    profiles: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
) -> None:
    for row in profiles:
        if isinstance(row, dict) and not _contains_pending(row):
            row.pop("pending_search_query", None)
    for table in tables:
        if not isinstance(table, dict):
            continue
        for rows_key in ("rows", "dimensions"):
            rows = table.get(rows_key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and not _contains_pending(row):
                    row.pop("pending_search_query", None)


def _strip_internal_fields(
    profiles: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
    *,
    finalize_pending: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    cleaned_profiles = [
        _strip_internal_from_row(row, finalize_pending=finalize_pending)
        for row in profiles
    ]
    cleaned_tables: List[Dict[str, Any]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        next_table = dict(table)
        columns = _generic_columns(next_table)
        for rows_key in ("rows", "dimensions"):
            rows = table.get(rows_key)
            if isinstance(rows, list):
                next_table[rows_key] = [
                    _strip_internal_from_row(
                        row,
                        finalize_pending=finalize_pending,
                        columns=columns,
                    )
                    if isinstance(row, dict)
                    else row
                    for row in rows
                ]
        cleaned_tables.append(next_table)
    return cleaned_profiles, cleaned_tables


def _strip_internal_from_row(
    row: Dict[str, Any],
    *,
    finalize_pending: bool = True,
    columns: Sequence[str] = (),
) -> Dict[str, Any]:
    next_row = dict(row)
    next_row.pop("pending_search_query", None)
    if finalize_pending:
        _fill_missing_columns(next_row, columns)
        _finalize_pending_values(next_row)
    return next_row


def _fill_missing_columns(row: Dict[str, Any], columns: Sequence[str]) -> None:
    for column in columns:
        column = clean_text(column, 80)
        if not column or _is_evidence_column(column):
            continue
        if column not in row or _is_missing(row.get(column)):
            row[column] = NO_PRODUCT_EVIDENCE


def _finalize_pending_values(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if key == "pending_search_query":
                value.pop(key, None)
                continue
            if isinstance(item, dict):
                _finalize_pending_values(item)
            elif isinstance(item, list):
                for child in item:
                    _finalize_pending_values(child)
            elif _is_pending(item):
                value[key] = NO_PRODUCT_EVIDENCE


def _contains_pending_outputs(
    profiles: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
) -> bool:
    return any(_contains_pending(row) for row in profiles if isinstance(row, dict)) or _contains_pending_tables(tables)


def _pending_count(value: Any) -> int:
    if isinstance(value, dict):
        return sum(
            _pending_count(item)
            for key, item in value.items()
            if key != "pending_search_query"
        )
    if isinstance(value, list):
        return sum(_pending_count(item) for item in value)
    return 1 if _is_pending(value) else 0


def _contains_pending(row: Dict[str, Any]) -> bool:
    for key, value in row.items():
        if key == "pending_search_query":
            continue
        if isinstance(value, dict):
            if any(_is_pending(item) for item in value.values()):
                return True
        elif _is_pending(value):
            return True
    return False


def _contains_pending_tables(tables: List[Dict[str, Any]]) -> bool:
    for table in tables:
        if not isinstance(table, dict):
            continue
        for key in ("rows", "dimensions"):
            rows = table.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and _contains_pending(row):
                    return True
    return False


def _match_competitor(value: Any, competitors: Sequence[str]) -> str:
    text = clean_text(value, 120).lower()
    for competitor in competitors:
        name = clean_text(competitor, 120)
        if text == name.lower():
            return name
    for competitor in competitors:
        name = clean_text(competitor, 120)
        if name and name.lower() in text:
            return name
    return ""


def _usable_cell_text(value: Any, max_chars: int) -> str:
    text = clean_text(value, max_chars)
    if _is_missing(text) or is_low_value_evidence_text(text, text):
        return ""
    return text


def _clean_score(value: Any) -> Optional[int]:
    if _is_missing(value):
        return None
    try:
        score = int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        return None
    return max(0, min(5, score))


def _attach_pending_queries(
    profiles: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
    gaps: List[TableGap],
    queries: Dict[str, str],
) -> None:
    if not queries:
        return
    context_queries: Dict[Tuple[str, int], List[str]] = {}
    for gap in gaps:
        query = queries.get(gap.gap_id)
        if not query:
            continue
        context_queries.setdefault((gap.table_name, gap.row_index), [])
        if query not in context_queries[(gap.table_name, gap.row_index)]:
            context_queries[(gap.table_name, gap.row_index)].append(query)

    for index, profile in enumerate(profiles):
        if not isinstance(profile, dict):
            continue
        query = _query_for_context(context_queries, "competitor_profiles", index)
        if query:
            profile.setdefault("pending_search_query", query)
    for table in tables:
        if not isinstance(table, dict):
            continue
        name = table.get("table_name")
        rows = table.get("dimensions") if name == "agent_capability_scorecard" else table.get("rows")
        if not isinstance(rows, list) and isinstance(table.get("dimensions"), list):
            rows = table.get("dimensions")
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            query = _query_for_context(context_queries, str(name), index)
            if query:
                row.setdefault("pending_search_query", query)


def _embed_pending_directions(
    profiles: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
    gaps: List[TableGap],
    queries: Dict[str, str],
) -> None:
    query_by_gap = {gap.gap_id: queries.get(gap.gap_id, "") for gap in gaps}
    for gap in gaps:
        query = query_by_gap.get(gap.gap_id)
        if not query:
            continue
        direction = _search_direction_label(gap, query)
        value = f"{PENDING_SEARCH}（方向：{direction}）"
        if gap.table_name == "competitor_profiles":
            if 0 <= gap.row_index < len(profiles):
                _set_pending_field(profiles[gap.row_index], gap.field, value)
            continue
        table = _table_by_name(tables, gap.table_name)
        if not table:
            continue
        rows = (
            table.get("dimensions")
            if gap.table_name == "agent_capability_scorecard"
            else table.get("rows")
        )
        if not isinstance(rows, list) and isinstance(table.get("dimensions"), list):
            rows = table.get("dimensions")
        if not isinstance(rows, list) or not (0 <= gap.row_index < len(rows)):
            continue
        row = rows[gap.row_index]
        if not isinstance(row, dict):
            continue
        if gap.table_name == "agent_capability_scorecard" and gap.field == "score":
            scores = row.get("scores")
            if isinstance(scores, dict) and gap.competitor in scores:
                scores[gap.competitor] = value
        else:
            field = _resolve_row_field(gap.field, row)
            if field:
                gap.field = field
                _set_pending_field(row, field, value)


def _set_pending_field(row: Dict[str, Any], field: str, value: str) -> None:
    if field and (_is_pending(row.get(field)) or _is_missing(row.get(field))):
        row[field] = value


def _table_by_name(tables: Sequence[Dict[str, Any]], table_name: str) -> Dict[str, Any]:
    for table in tables:
        if isinstance(table, dict) and table.get("table_name") == table_name:
            return table
    return {}


def _query_for_context(
    context_queries: Dict[Tuple[str, int], List[str]],
    table_name: str,
    row_index: int,
) -> str:
    values = context_queries.get((table_name, row_index), [])
    return "；".join(values[:2])


def _limit_query_map(query_map: Dict[str, str], max_queries: int) -> Dict[str, str]:
    used: List[str] = []
    limited: Dict[str, str] = {}
    for gap_id, query in query_map.items():
        if query not in used:
            if len(used) >= max_queries:
                continue
            used.append(query)
        limited[gap_id] = query
    return limited


def _merge_gap_queries(
    *,
    primary: Dict[str, str],
    fallback: Dict[str, str],
    max_unique: int,
) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    used: List[str] = []
    for source in (primary, fallback):
        for gap_id, query in source.items():
            if gap_id in merged or not query:
                continue
            if query not in used and len(used) >= max_unique:
                continue
            merged[gap_id] = query
            if query not in used:
                used.append(query)
    return merged


def _evidence_summary(cards: Sequence[EvidenceCard]) -> List[Dict[str, Any]]:
    return [
        {
            "evidence_id": card.evidence_id,
            "competitor": card.competitor,
            "dimension": card.dimension,
            "claim": clean_text(card.claim, 160),
        }
        for card in cards[:24]
    ]


def _query_label(table_name: str, field: str, dimension: str) -> str:
    mapping = {
        "target_user": "target users customer segment",
        "core_scenario": "use cases scenarios",
        "product_form": "product form IDE CLI web extension",
        "main_entry": "main entry platform IDE plugin CLI",
        "business_model": "pricing plans enterprise",
        "strategic_judgement": "positioning differentiation advantages",
        "score": f"{dimension} capability",
        "reason": f"{dimension} capability evidence",
        "user_goal": "user journey onboarding goal",
        "competitor_experience": "user experience workflow",
        "opportunity": "reviews pain points limitations",
    }
    return clean_text(mapping.get(field, f"{dimension} {field}"), 120)


def _search_direction_label(gap: TableGap, query: str) -> str:
    subject = clean_text(gap.competitor or gap.dimension or gap.table_name, 50)
    field_labels = {
        "target_user": "目标用户",
        "core_scenario": "核心场景",
        "product_form": "产品形态",
        "main_entry": "主要入口",
        "business_model": "商业模式/定价",
        "strategic_judgement": "定位差异",
        "score": f"{gap.dimension}能力证据",
        "reason": f"{gap.dimension}评分依据",
        "user_goal": "用户目标",
        "competitor_experience": "竞品体验",
        "opportunity": "机会点/痛点",
    }
    label = field_labels.get(gap.field, gap.field or "补充证据")
    query_text = clean_text(query, 90)
    if subject:
        return f"{subject} {label}；关键词：{query_text}"
    return f"{label}；关键词：{query_text}"


def _is_missing(value: Any) -> bool:
    text = clean_text(value, 80)
    if not text:
        return True
    compact = re.sub(r"\s+", "", text)
    if compact.startswith(PENDING_SEARCH):
        return True
    if compact in {
        PENDING_SEARCH,
        NO_PRODUCT_EVIDENCE,
        "未找到明确证据",
        "未找到明确公开证据",
        "未找到明确公开信息",
        "未找到明确信息",
        "未找到公开信息",
        "暂无明确公开信息",
        "暂未公开明确披露相关信息",
        "暂未公开明确披露",
        "暂未公开相关信息",
        "未公开相关信息",
        "无公开信息",
        "暂无可渲染对比数据",
        "暂无可渲染对比数据。",
        "无",
        "N/A",
        "NA",
        "null",
        "None",
    }:
        return True
    weak_markers = [
        "缺少明确证据",
        "需要补充",
        "仍需进一步验证",
        "需进一步确认",
        "现有资料有限",
        "资料不足",
        "未提供明确",
        "未形成明确",
        "未找到明确公开",
        "未找到公开",
        "未公开",
        "暂未公开",
        "暂无明确",
        "暂未披露",
        "未披露",
        "Web / API / 工作台等产品形态",
        "Web、API 或企业系统集成入口",
        "围绕 Agent 自动化任务完成与报告生成",
        "订阅或企业采购路径需进一步确认",
        "资料显示其在企业落地、集成或可信控制上具有分析价值",
        "实现一个快速排序算法",
        "def quicksort",
        "python运行",
        "自动弹出补全建议",
        "generate code from context",
        "实际应用案例演示",
        "flask rest api",
    ]
    return any(marker in text for marker in weak_markers)


def _is_pending(value: Any) -> bool:
    return clean_text(value, 80).startswith(PENDING_SEARCH)


def _scorecard_reason_is_single_competitor(
    reason: Any, competitors: Sequence[str]
) -> bool:
    text = clean_text(reason, 400)
    if not text:
        return True
    mentioned = [name for name in competitors if name and name in text]
    if len(mentioned) == 1:
        return True
    if is_low_value_evidence_text(text, text):
        return True
    return False


def _norm(value: Any) -> str:
    return clean_text(value, 120).lower()


def _can_use_planning_llm(config: WritingAgentConfig) -> bool:
    return bool(
        config.use_llm
        and config.llm_api_key
        and config.llm_base_url
        and config.llm_model
    )


def _log(config: WritingAgentConfig, message: str) -> None:
    if config.verbose and config.progress_printer:
        config.progress_printer(message)

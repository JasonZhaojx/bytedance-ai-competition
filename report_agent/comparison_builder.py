"""横向对比 Agent。

本节点负责把证据和洞察组织成 PM 报告里的三类核心对比表：竞品定位矩阵、
Agent 能力评分表、用户旅程对比表。表格输出保持 dict/list，方便报告层渲染，
也方便下游检测。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Sequence, Tuple

try:
    from .batch_runner import run_parallel_batches
    from .chunking import chunk_evidence_cards, evidence_prompt_payload
    from .evidence_structurer import infer_competitor, is_low_value_evidence_text
    from .llm_utils import call_json_llm, clean_text
    from .models import EvidenceCard, PMInsight, WritingAgentConfig
    from .table_debug import log_comparison_tables
    from .table_gap_search import enrich_tables_with_gap_search
except ImportError:
    from report_agent.batch_runner import run_parallel_batches
    from report_agent.chunking import chunk_evidence_cards, evidence_prompt_payload
    from report_agent.evidence_structurer import infer_competitor, is_low_value_evidence_text
    from report_agent.llm_utils import call_json_llm, clean_text
    from report_agent.models import EvidenceCard, PMInsight, WritingAgentConfig
    from report_agent.table_debug import log_comparison_tables
    from report_agent.table_gap_search import enrich_tables_with_gap_search


PENDING_SEARCH = "待搜索"


def build_comparisons(
    evidence_cards: List[EvidenceCard],
    pm_insights: List[PMInsight],
    competitors: Sequence[str],
    target_domain: str,
    config: WritingAgentConfig,
    *,
    enrich_table_gaps: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """生成竞品画像和横向对比表。"""

    competitor_list = _competitor_names(evidence_cards, competitors)
    profiles, tables = _comparisons_from_llm(
        evidence_cards=evidence_cards,
        pm_insights=pm_insights,
        competitors=competitor_list,
        target_domain=target_domain,
        config=config,
    )
    if profiles and tables:
        profiles, tables = _sanitize_comparisons_with_llm(
            profiles=profiles,
            tables=tables,
            evidence_cards=evidence_cards,
            pm_insights=pm_insights,
            competitors=competitor_list,
            target_domain=target_domain,
            config=config,
        )
        normalized_profiles = _normalize_llm_profiles(profiles, competitor_list)
        normalized_tables = _normalize_llm_tables(tables, competitor_list)
        if _profiles_are_renderable(normalized_profiles) and normalized_tables:
            log_comparison_tables(
                config,
                "comparison tables normalized before gap search",
                normalized_tables,
            )
            if not enrich_table_gaps:
                return normalized_profiles, normalized_tables
            return enrich_tables_with_gap_search(
                profiles=normalized_profiles,
                tables=normalized_tables,
                evidence_cards=evidence_cards,
                competitors=competitor_list,
                target_domain=target_domain,
                config=config,
            )
    fallback_profiles, fallback_tables = _fallback_comparisons(
        evidence_cards, competitor_list
    )
    log_comparison_tables(config, "comparison tables fallback filled", fallback_tables)
    if not enrich_table_gaps:
        return fallback_profiles, fallback_tables
    return enrich_tables_with_gap_search(
        profiles=fallback_profiles,
        tables=fallback_tables,
        evidence_cards=evidence_cards,
        competitors=competitor_list,
        target_domain=target_domain,
        config=config,
    )


def _comparisons_from_llm(
    *,
    evidence_cards: List[EvidenceCard],
    pm_insights: List[PMInsight],
    competitors: List[str],
    target_domain: str,
    config: WritingAgentConfig,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """让 LLM 生成对比表。"""

    chunks = chunk_evidence_cards(evidence_cards)
    if len(chunks) > 1:
        merged_profiles: List[Dict[str, Any]] = []
        merged_tables: List[Dict[str, Any]] = []
        batch_results = run_parallel_batches(
            label="comparison tables",
            batches=chunks,
            config=config,
            worker=lambda cards: _comparisons_from_llm(
                evidence_cards=cards,
                pm_insights=_insights_for_cards(pm_insights, cards),
                competitors=competitors,
                target_domain=target_domain,
                config=config,
            ),
        )
        for profile_items, table_items in batch_results:
            merged_profiles.extend(profile_items)
            merged_tables.extend(table_items)
        merged = _merge_tables(merged_tables)
        log_comparison_tables(config, "comparison tables merged from batches", merged)
        return _dedupe_profiles(merged_profiles), merged

    plan = _plan_comparison_tables(
        evidence_cards=evidence_cards,
        pm_insights=pm_insights,
        competitors=competitors,
        target_domain=target_domain,
        config=config,
    )
    if plan:
        planned_profiles, planned_tables = _fill_comparisons_from_plan(
            plan=plan,
            evidence_cards=evidence_cards,
            pm_insights=pm_insights,
            competitors=competitors,
            target_domain=target_domain,
            config=config,
        )
        if planned_profiles and planned_tables:
            return planned_profiles, planned_tables

    data = call_json_llm(
        config=config,
        system_prompt="你是产品竞品横向对比专家，只输出 JSON。",
        user_prompt=f"""
分析领域:
{target_domain}

候选竞品:
{json.dumps(competitors, ensure_ascii=False)}

Evidence Cards:
{json.dumps(evidence_prompt_payload(evidence_cards), ensure_ascii=False, indent=2)}

PM Insights:
{json.dumps([insight.to_dict() for insight in pm_insights], ensure_ascii=False, indent=2)}

请输出竞品画像和你认为最适合 PM 决策的对比表。表格数量、表名和列名由你根据原文决定，不要被固定模板限制。

- 所有判断必须由 evidence_ids 支撑；没有证据时写“待搜索”，不要猜测。
- 每张对比表必须为每个候选竞品各输出一行；不能返回空 rows，不能只返回表头。
- 先从 Evidence Cards 的 claim/raw_excerpt 填入已有事实；只有原文完全没有该字段证据时才写“待搜索”。
- 表格必须服务 PM 决策，优先围绕目标用户、核心场景、产品形态/入口、定价/商业化、Agent 能力、集成生态、安全合规、限制风险、用户反馈等从原文真实出现的信息组织。
- 如果 Evidence Cards 中包含我方产品参数词库或已知产品参数词库，请把它理解为用户自己的产品/我方产品基准参数，不是竞品参数；把这些参数点优先转化为横向对比维度，例如定价/套餐、部署方式、平台支持、核心功能、目标用户、限制、安全合规、集成生态、售后服务等。
- 如果 Evidence Cards 中包含问卷分析，请用它校准对比维度的权重：用户高频场景、价格敏感度、替换意愿、采购顾虑和风险偏好应影响战略判断，但不能被写成某个竞品的官方事实。

返回严格 JSON:
{{
  "competitor_profiles": [
    {{
      "competitor": "竞品名",
      "target_user": "目标用户",
      "core_scenario": "核心场景",
      "product_form": "产品形态",
      "main_entry": "主要入口",
      "business_model": "商业模式",
      "strategic_judgement": "战略判断",
      "evidence_ids": ["ev_001"]
    }}
  ],
  "comparison_tables": [
    {{
      "table_name": "中文表名",
      "columns": ["竞品", "维度1", "维度2", "证据ID"],
      "rows": [
        {{"竞品": "竞品名", "维度1": "产品级摘要或待搜索", "证据ID": ["ev_001"]}}
      ]
    }}
  ]
}}
""".strip(),
    )
    if not isinstance(data, dict):
        return [], []
    profiles = data.get("competitor_profiles")
    tables = data.get("comparison_tables")
    if not isinstance(profiles, list) or not isinstance(tables, list):
        return [], []
    if not _filled_tables_have_source_content(tables):
        _log(config, "[writing-agent] comparison tables contain no source-backed rows")
        return [], []
    log_comparison_tables(config, "comparison tables filled from source", tables)
    return profiles, tables


def _plan_comparison_tables(
    *,
    evidence_cards: List[EvidenceCard],
    pm_insights: List[PMInsight],
    competitors: List[str],
    target_domain: str,
    config: WritingAgentConfig,
) -> Dict[str, Any]:
    """First let the model decide useful tables and dimensions from source text."""

    _log(config, "[writing-agent] plan comparison tables")
    data = call_json_llm(
        config=config,
        system_prompt="你是竞品分析表格规划师，只输出 JSON。",
        user_prompt=f"""
你现在只做表格规划，不填表。

目标领域:
{target_domain}

候选竞品:
{json.dumps(competitors, ensure_ascii=False)}

证据卡，包含原文片段:
{json.dumps(_comparison_evidence_payload(evidence_cards), ensure_ascii=False, indent=2)}

PM 洞察:
{json.dumps([insight.to_dict() for insight in pm_insights], ensure_ascii=False, indent=2)}

任务:
先读证据原文，判断哪些内容适合做产品经理可读的横向表格。

规划规则:
- 只规划能由 evidence_ids 支撑的表格和维度。
- 不要把安装教程、shell 命令、Dockerfile/build 脚本、原始配置、代码片段、插件安装步骤、开发流程模板、OpenSpec/brainstorming/write-plan 模板规划进表格。
- 如果原文只是教程步骤，但可抽象为产品级能力，只规划抽象能力，例如“任务规划流程支持”“多模型接入”“本地部署”；不要规划教程步骤本身。
- 表格必须服务 PM 决策，优先选择定位、目标用户、核心场景、产品形态、商业化、部署/安全、集成生态、Agent 能力、用户旅程。
- table_name 用中文，表头由你根据证据内容自由规划；不要创造无关表。
- 如果某个 PM 重要字段原文没有证据，也可以规划该列并标注需要待搜索，方便后续检索补全。
- 每个 planned row/dimension 尽量列出 usable_evidence_ids；如果该维度对 PM 决策关键但当前原文缺证据，可写空数组并给出 search_intent。

返回严格 JSON:
{{
  "competitor_profile_fields": ["competitor", "target_user", "core_scenario", "product_form", "main_entry", "business_model", "strategic_judgement", "evidence_ids"],
  "tables": [
    {{
      "table_name": "Agent 能力与落地能力对比",
      "purpose": "为什么这张表值得生成",
      "columns": ["竞品", "任务规划", "工具调用/集成", "安全与控制", "证据ID"],
      "dimensions": [
        {{
          "dimension": "任务规划",
          "definition": "产品级判断口径",
          "usable_evidence_ids": ["ev_001"],
          "search_intent": "缺证据时应搜索什么"
        }}
      ]
    }}
  ]
}}
""".strip(),
    )
    return data if isinstance(data, dict) else {}


def _fill_comparisons_from_plan(
    *,
    plan: Dict[str, Any],
    evidence_cards: List[EvidenceCard],
    pm_insights: List[PMInsight],
    competitors: List[str],
    target_domain: str,
    config: WritingAgentConfig,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fill comparison tables only after a plan has constrained the structure."""

    _log(config, "[writing-agent] fill comparison tables from plan")
    data = call_json_llm(
        config=config,
        system_prompt="你是竞品对比表填写专家，只输出 JSON。",
        user_prompt=f"""
你必须严格按表格规划填表，不要新增表格和维度。

目标领域:
{target_domain}

候选竞品:
{json.dumps(competitors, ensure_ascii=False)}

表格规划:
{json.dumps(plan, ensure_ascii=False, indent=2)}

证据卡，包含原文片段:
{json.dumps(_comparison_evidence_payload(evidence_cards), ensure_ascii=False, indent=2)}

PM 洞察:
{json.dumps([insight.to_dict() for insight in pm_insights], ensure_ascii=False, indent=2)}

填写规则:
- 只能使用规划中的 table_name、columns、字段、dimension。
- 每个结论必须绑定 evidence_ids，且 evidence_ids 必须来自输入。
- 单元格必须是产品级摘要，不得复制长原文，不得写教程步骤、命令、代码、配置片段。
- 没有证据的单元格写“待搜索（方向：...；关键词：...）”，关键词要包含竞品名和待补字段，方便后续审表模型检索。
- 单元格不超过 80 个中文字符。
- 表格字段优先用中文；证据列可用 evidence_ids 或 证据ID。
- 每张对比表必须为每个候选竞品各输出一行；不能返回空 rows，不能只返回表头。
- 先尽最大努力从 Evidence Cards 的 claim/raw_excerpt 中提取已有事实填入单元格；只有该竞品该字段在原文完全没有证据时，才写“待搜索”。

返回严格 JSON:
{{
  "competitor_profiles": [
    {{
      "competitor": "竞品名",
      "target_user": "目标用户",
      "core_scenario": "核心场景",
      "product_form": "产品形态",
      "main_entry": "主要入口",
      "business_model": "商业模式",
      "strategic_judgement": "战略判断",
      "evidence_ids": ["ev_001"]
    }}
  ],
  "comparison_tables": [
    {{
      "table_name": "中文表名",
      "columns": ["竞品", "字段1", "字段2", "证据ID"],
      "rows": [
        {{"竞品": "竞品名", "字段1": "从原文提取的产品级摘要或待搜索", "evidence_ids": ["ev_001"]}}
      ]
    }}
  ]
}}
""".strip(),
    )
    if not isinstance(data, dict):
        return [], []
    profiles = data.get("competitor_profiles")
    tables = data.get("comparison_tables")
    if not isinstance(profiles, list) or not isinstance(tables, list):
        return [], []
    if not _filled_tables_have_source_content(tables):
        _log(config, "[writing-agent] filled comparison tables contain no source-backed rows; retry fallback")
        return [], []
    log_comparison_tables(config, "comparison tables filled from plan", tables)
    return profiles, tables


def _insights_for_cards(
    pm_insights: List[PMInsight], evidence_cards: List[EvidenceCard]
) -> List[PMInsight]:
    allowed = {card.evidence_id for card in evidence_cards}
    return [
        insight
        for insight in pm_insights
        if any(evidence_id in allowed for evidence_id in insight.evidence_ids)
    ]


def _comparison_evidence_payload(cards: Sequence[EvidenceCard]) -> List[Dict[str, Any]]:
    payload = evidence_prompt_payload(cards)
    by_id = {card.evidence_id: card for card in cards}
    for item in payload:
        card = by_id.get(item.get("evidence_id"))
        if not card:
            continue
        item["raw_excerpt"] = clean_text(card.raw_excerpt, 900)
    return payload


def _dedupe_profiles(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        name = clean_text(
            profile.get("competitor") or profile.get("competitor_name") or profile.get("name"),
            80,
        )
        if not name:
            continue
        if name not in merged:
            merged[name] = dict(profile)
            continue
        target = merged[name]
        for key, value in profile.items():
            if key == "evidence_ids":
                ids = target.setdefault("evidence_ids", [])
                if isinstance(value, list):
                    ids.extend(item for item in value if item not in ids)
            elif value and not target.get(key):
                target[key] = value
    return list(merged.values())


def _merge_tables(tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for table in tables:
        if not isinstance(table, dict):
            continue
        name = table.get("table_name")
        if not name:
            continue
        target = merged.setdefault(name, {"table_name": name})
        if name == "agent_capability_scorecard":
            rows = target.setdefault("dimensions", [])
            rows.extend(table.get("dimensions") or [])
            if table.get("scoring_rule") and not target.get("scoring_rule"):
                target["scoring_rule"] = table["scoring_rule"]
        else:
            rows_key = "rows" if isinstance(table.get("rows"), list) else "dimensions"
            rows = target.setdefault(rows_key, [])
            rows.extend(table.get(rows_key) or [])
            if table.get("columns") and not target.get("columns"):
                target["columns"] = table["columns"]
    return list(merged.values())


def _sanitize_comparisons_with_llm(
    *,
    profiles: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
    evidence_cards: List[EvidenceCard],
    pm_insights: List[PMInsight],
    competitors: Sequence[str],
    target_domain: str,
    config: WritingAgentConfig,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Use a second LLM pass to remove tutorial/code noise from comparison tables."""

    data = call_json_llm(
        config=config,
        system_prompt="你是竞品对比表清洗器，只输出 JSON。",
        user_prompt=f"""
任务: 清洗竞品对比结构化表格，保留产品经理可读的产品级对比结论。

分析领域:
{target_domain}

候选竞品，只允许这些名字出现在 competitor 和 scores key 中:
{json.dumps(list(competitors), ensure_ascii=False)}

原始 competitor_profiles:
{json.dumps(profiles, ensure_ascii=False, indent=2)}

原始 comparison_tables:
{json.dumps(tables, ensure_ascii=False, indent=2)}

可用 Evidence Cards:
{json.dumps(evidence_prompt_payload(evidence_cards), ensure_ascii=False, indent=2)}

PM Insights:
{json.dumps([insight.to_dict() for insight in pm_insights], ensure_ascii=False, indent=2)}

清洗规则:
- 不要新增证据，只能使用输入 evidence_ids。
- 删除或改写所有安装教程、shell 命令、Dockerfile/build 脚本、原始配置、代码片段、插件安装步骤、开发流程模板、OpenSpec/brainstorming/write-plan 模板。
- 表格单元格必须是产品级摘要，不能粘贴长原文。reason、target_user、core_scenario、strategic_judgement 等单元格不超过 80 个中文字符。
- agent_capability_scorecard 的 scores 只能包含候选竞品 key；不能出现“用户需求、参数词库、问卷背景”等 key。
- 如果某维度只有教程/安装/模板证据，没有产品级能力证据，reason 写“未找到明确产品级证据”，对应 evidence_ids 置空或只保留真正相关证据。
- competitor_positioning_matrix 不要把“产品定位:”这类标题当成动态列；优先输出 competitor、target_user、core_scenario、product_form、main_entry、business_model、strategic_judgement、evidence_ids。
- user_journey_comparison 只写用户旅程阶段的产品体验摘要，不写教程步骤。

返回严格 JSON:
{{
  "competitor_profiles": [],
  "comparison_tables": []
}}
""".strip(),
    )
    if not isinstance(data, dict):
        return profiles, tables
    cleaned_profiles = data.get("competitor_profiles")
    cleaned_tables = data.get("comparison_tables")
    if isinstance(cleaned_profiles, list) and isinstance(cleaned_tables, list):
        return cleaned_profiles, cleaned_tables
    return profiles, tables


def _normalize_llm_profiles(
    profiles: List[Dict[str, Any]],
    competitors: Sequence[str],
) -> List[Dict[str, Any]]:
    """Normalize common LLM field variants into the renderer schema."""

    normalized: List[Dict[str, Any]] = []
    for raw in profiles:
        if not isinstance(raw, dict):
            continue
        competitor = clean_text(
            raw.get("competitor")
            or raw.get("competitor_name")
            or raw.get("name")
            or raw.get("竞品名称"),
            80,
        )
        competitor = _normalize_competitor_name(competitor, competitors)
        if not competitor:
            continue
        normalized.append(
            {
                "competitor": competitor,
                "target_user": clean_text(
                    raw.get("target_user")
                    or raw.get("target_users")
                    or raw.get("目标用户"),
                    160,
                ),
                "core_scenario": clean_text(
                    raw.get("core_scenario")
                    or raw.get("core_positioning")
                    or raw.get("核心场景")
                    or raw.get("核心定位"),
                    180,
                ),
                "product_form": clean_text(
                    raw.get("product_form") or raw.get("产品形态"), 120
                ),
                "main_entry": clean_text(
                    raw.get("main_entry") or raw.get("主要入口"), 120
                ),
                "business_model": clean_text(
                    raw.get("business_model") or raw.get("商业模式"), 120
                ),
                "strategic_judgement": clean_text(
                    raw.get("strategic_judgement")
                    or raw.get("core_features")
                    or raw.get("核心差异化卖点")
                    or raw.get("战略判断"),
                    220,
                ),
                "evidence_ids": raw.get("evidence_ids") if isinstance(raw.get("evidence_ids"), list) else [],
            }
        )
    return normalized


def _normalize_llm_tables(
    tables: List[Dict[str, Any]],
    competitors: Sequence[str],
) -> List[Dict[str, Any]]:
    """Keep only tables already compatible with report_composer."""

    normalized: List[Dict[str, Any]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        name = table.get("table_name")
        if name == "competitor_positioning_matrix" and isinstance(
            table.get("rows"), list
        ):
            normalized.append(
                {
                    **table,
                    "rows": [
                        _normalize_positioning_row(row, competitors)
                        for row in table.get("rows", [])
                        if isinstance(row, dict)
                    ],
                }
            )
        elif name == "agent_capability_scorecard" and isinstance(
            table.get("dimensions"), list
        ):
            normalized.append(
                {
                    **table,
                    "dimensions": [
                        row
                        for row in (
                            _normalize_scorecard_row(row, competitors)
                            for row in table.get("dimensions", [])
                            if isinstance(row, dict)
                        )
                        if row
                    ],
                }
            )
        elif name == "user_journey_comparison" and isinstance(table.get("rows"), list):
            normalized.append(
                {
                    **table,
                    "rows": [
                        row
                        for row in (
                            _normalize_journey_row(row)
                            for row in table.get("rows", [])
                            if isinstance(row, dict)
                        )
                        if row
                    ],
                }
            )
        elif isinstance(table.get("rows"), list) or isinstance(table.get("dimensions"), list):
            normalized.append(_normalize_generic_table(table, competitors))
    return normalized


def _normalize_generic_table(
    table: Dict[str, Any], competitors: Sequence[str]
) -> Dict[str, Any]:
    rows = []
    raw_rows = table.get("rows") if isinstance(table.get("rows"), list) else table.get("dimensions", [])
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        next_row = {}
        for key, value in row.items():
            if key in {"evidence_ids", "证据ID", "证据ids"}:
                next_row["evidence_ids"] = _evidence_ids(row) or (
                    value if isinstance(value, list) else []
                )
                continue
            text = _clean_table_text(value, 180)
            if key in {"competitor", "competitor_name", "竞品", "竞品名称", "产品", "产品名称"}:
                competitor = _normalize_competitor_name(text, competitors)
                next_row[_generic_column_key(key)] = competitor or text
            else:
                next_row[_generic_column_key(key)] = text
        if next_row:
            rows.append(next_row)
    columns = table.get("columns")
    if not isinstance(columns, list):
        columns = _columns_from_rows(rows)
    else:
        columns = [_generic_column_key(column) for column in columns]
        columns = ["evidence_ids" if column in {"证据ID", "证据ids"} else column for column in columns]
        columns = _align_columns_with_rows(columns, rows)
    return {
        **table,
        "table_name": clean_text(table.get("table_name"), 80) or "横向对比表",
        "columns": [clean_text(column, 80) for column in columns if clean_text(column, 80)],
        "rows": rows,
    }


def _generic_column_key(value: Any) -> str:
    key = clean_text(value, 80)
    mapping = {
        "competitor": "竞品",
        "competitor_name": "竞品",
        "竞品名称": "竞品名称",
        "product": "竞品",
        "product_name": "竞品",
        "target_user": "目标用户",
        "target_users": "目标用户",
        "core_scenario": "核心场景",
        "core_positioning": "核心定位",
        "product_form": "产品形态",
        "main_entry": "主要入口",
        "business_model": "商业模式",
        "strategic_judgement": "战略判断",
        "strategy_judgement": "战略判断",
        "dimension": "维度",
        "capability": "能力维度",
        "score": "评分",
        "scores": "评分",
        "reason": "依据",
        "stage": "阶段",
        "journey_stage": "阶段",
        "user_goal": "用户目标",
        "competitor_experience": "竞品体验",
        "opportunity": "机会点",
        "evidence_ids": "evidence_ids",
        "source_ids": "evidence_ids",
    }
    return mapping.get(key, key)


def _align_columns_with_rows(
    columns: Sequence[str], rows: Sequence[Dict[str, Any]]
) -> List[str]:
    row_columns = _columns_from_rows(rows)
    if not row_columns:
        return _dedupe_columns(columns)
    aligned: List[str] = []
    for column in columns:
        if column in row_columns and column not in aligned:
            aligned.append(column)
    for column in row_columns:
        if column not in aligned:
            aligned.append(column)
    return aligned


def _dedupe_columns(columns: Sequence[str]) -> List[str]:
    deduped: List[str] = []
    for column in columns:
        item = clean_text(column, 80)
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _generic_pending_rows(
    *,
    columns: Sequence[str],
    competitors: Sequence[str],
    table_name: str,
) -> List[Dict[str, Any]]:
    visible_columns = [
        column
        for column in _dedupe_columns(columns)
        if column not in {"evidence_ids", "pending_search_query"}
    ]
    if not visible_columns:
        visible_columns = ["竞品", "待补充信息"]
    has_competitor_column = any(column in {"竞品", "竞品名称", "产品", "产品名称"} for column in visible_columns)
    subjects = [clean_text(name, 80) for name in competitors if clean_text(name, 80)]
    if not has_competitor_column:
        subjects = [""]
    rows: List[Dict[str, Any]] = []
    for subject in subjects or [""]:
        row: Dict[str, Any] = {}
        for column in visible_columns:
            if column in {"竞品", "竞品名称", "产品", "产品名称"}:
                row[column] = subject or PENDING_SEARCH
            elif column in {"维度", "阶段", "能力维度"} and not has_competitor_column:
                row[column] = f"{PENDING_SEARCH}（方向：{table_name} {column}）"
            else:
                query_subject = subject or table_name
                row[column] = (
                    f"{PENDING_SEARCH}（方向：{query_subject} {column}；"
                    f"关键词：{query_subject} {column} 官方文档）"
                )
        row["evidence_ids"] = []
        rows.append(row)
    return rows


def _columns_from_rows(rows: Sequence[Dict[str, Any]]) -> List[str]:
    columns: List[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns


def _filled_tables_have_source_content(tables: List[Dict[str, Any]]) -> bool:
    for table in tables:
        if not isinstance(table, dict):
            continue
        rows = table.get("rows") if isinstance(table.get("rows"), list) else table.get("dimensions")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and _row_has_source_content(row):
                return True
    return False


def _row_has_source_content(row: Dict[str, Any]) -> bool:
    evidence_ids = _evidence_ids(row)
    for key, value in row.items():
        if key in {"evidence_ids", "证据ID", "证据ids", "source_ids", "pending_search_query"}:
            continue
        if _is_competitor_key(key):
            continue
        if isinstance(value, dict):
            if any(_source_cell_text(item) for item in value.values()):
                return True
            continue
        text = _source_cell_text(value)
        if text and (evidence_ids or not text.startswith(PENDING_SEARCH)):
            return True
    return False


def _source_cell_text(value: Any) -> str:
    text = clean_text(value, 220)
    if not text or text.startswith(PENDING_SEARCH):
        return ""
    if text in {"未找到明确产品级证据", "未找到明确证据", "暂无"}:
        return ""
    return text


def _is_competitor_key(key: Any) -> bool:
    return clean_text(key, 80) in {
        "竞品",
        "竞品名称",
        "产品",
        "产品名称",
        "competitor",
        "competitor_name",
        "product",
        "product_name",
    }


def _normalize_positioning_row(
    row: Dict[str, Any],
    competitors: Sequence[str],
) -> Dict[str, Any]:
    competitor = _normalize_competitor_name(row.get("competitor"), competitors)
    if competitor:
        return {
            "competitor": competitor,
            "target_user": _clean_positioning_field(
                "target_user", row.get("target_user") or row.get("目标用户"), 120
            ),
            "core_scenario": _clean_positioning_field(
                "core_scenario", row.get("core_scenario") or row.get("核心场景"), 140
            ),
            "product_form": _clean_positioning_field(
                "product_form", row.get("product_form") or row.get("产品形态"), 100
            ),
            "main_entry": _clean_positioning_field(
                "main_entry", row.get("main_entry") or row.get("主要入口"), 100
            ),
            "business_model": _clean_positioning_field(
                "business_model", row.get("business_model") or row.get("商业模式"), 120
            ),
            "strategic_judgement": _clean_positioning_field(
                "strategic_judgement",
                row.get("strategic_judgement")
                or row.get("core_features")
                or row.get("核心差异化卖点")
                or row.get("战略判断"),
                160,
            ),
            "evidence_ids": _evidence_ids(row),
        }
    dynamic = _dynamic_values(row)
    if dynamic:
        return {}
    return {}


def _normalize_scorecard_row(
    row: Dict[str, Any],
    competitors: Sequence[str],
) -> Dict[str, Any]:
    raw_scores = row.get("scores")
    scores: Dict[str, Any] = {}
    if isinstance(raw_scores, dict):
        for key, value in raw_scores.items():
            competitor = _normalize_competitor_name(key, competitors)
            if competitor:
                scores[competitor] = value
    else:
        dynamic = _dynamic_values(row)
        for key, value in dynamic.items():
            competitor = _normalize_competitor_name(key, competitors)
            if competitor:
                scores[competitor] = value

    reason = _clean_table_text(row.get("reason") or row.get("理由"), 180)
    evidence_ids = _evidence_ids(row)
    if is_low_value_evidence_text(reason, reason) or _is_table_placeholder(reason):
        reason = "未找到明确产品级证据"
        evidence_ids = []
        scores = {
            competitor: "待搜索"
            for competitor in competitors
            if competitor in scores or scores
        } or {competitor: "待搜索" for competitor in competitors}
    if not scores and not reason:
        return {}
    return {
        **row,
        "dimension": _clean_table_text(
            row.get("dimension") or row.get("维度") or row.get("capability"),
            80,
        ),
        "scores": scores,
        "reason": reason or "未找到明确产品级证据",
        "evidence_ids": evidence_ids,
    }


def _normalize_journey_row(row: Dict[str, Any]) -> Dict[str, Any]:
    competitor_experience = _clean_table_text(
        row.get("competitor_experience") or row.get("竞品体验"), 180
    )
    if is_low_value_evidence_text(competitor_experience, competitor_experience):
        competitor_experience = "未找到明确产品级证据"
    return {
        **row,
        "stage": _clean_table_text(
            row.get("stage") or row.get("journey_stage") or row.get("阶段"),
            80,
        ),
        "user_goal": _clean_table_text(
            row.get("user_goal") or row.get("用户目标") or "未找到明确证据",
            140,
        ),
        "competitor_experience": competitor_experience,
        "opportunity": _clean_table_text(
            row.get("opportunity") or row.get("机会点") or "未找到明确证据",
            160,
        ),
        "evidence_ids": _evidence_ids(row),
    }


def _normalize_competitor_name(value: Any, competitors: Sequence[str]) -> str:
    text = clean_text(value, 100)
    if not text:
        return ""
    lowered = text.lower()
    for competitor in competitors:
        name = clean_text(competitor, 100)
        if lowered == name.lower():
            return name
    for competitor in competitors:
        name = clean_text(competitor, 100)
        if name and name.lower() in lowered:
            return name
    return ""


def _clean_table_text(value: Any, max_chars: int) -> str:
    text = clean_text(value)
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    if is_low_value_evidence_text(text, text) or _is_table_placeholder(text):
        return "未找到明确产品级证据"
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text


def _clean_positioning_field(field: str, value: Any, max_chars: int) -> str:
    text = _clean_table_text(value, max_chars)
    if _positioning_field_mismatch(field, text):
        return "未找到明确产品级证据"
    return text


def _positioning_field_mismatch(field: str, text: str) -> bool:
    value = clean_text(text, 260)
    if not value or value == "未找到明确产品级证据":
        return False

    tutorial_markers = [
        "实现一个",
        "def ",
        "python运行",
        "自动弹出补全建议",
        "generate code from context",
        "实际应用案例",
        "输入以下注释",
        "快捷键",
        "命令面板",
        "右键菜单",
        "flask rest api",
    ]
    if any(marker.lower() in value.lower() for marker in tutorial_markers):
        return True

    wrong_heading_by_field = {
        "target_user": [
            "产品定位",
            "特色AI开发功能",
            "全版本定价",
            "产品形态/入口",
            "集成生态",
            "企业级服务",
            "限制或风险",
        ],
        "core_scenario": [
            "产品定位",
            "特色AI开发功能",
            "全版本定价",
            "产品形态/入口",
            "集成生态",
            "企业级服务",
            "限制或风险",
        ],
        "product_form": [
            "全版本定价",
            "特色AI开发功能",
            "集成生态",
            "限制或风险",
        ],
        "main_entry": [
            "全版本定价",
            "特色AI开发功能",
            "限制或风险",
        ],
        "business_model": [
            "产品定位",
            "特色AI开发功能",
            "产品形态/入口",
            "集成生态",
            "限制或风险",
        ],
        "strategic_judgement": [
            "全版本定价",
            "特色AI开发功能",
            "产品形态/入口",
        ],
    }
    return any(marker in value for marker in wrong_heading_by_field.get(field, []))


def _is_table_placeholder(text: str) -> bool:
    value = clean_text(text, 240)
    if not value:
        return True
    markers = [
        "资料显示其在企业落地、集成或可信控制上具有分析价值",
        "围绕 Agent 自动化任务完成与报告生成",
        "Web / API / 工作台等产品形态",
        "Web、API 或企业系统集成入口",
        "订阅或企业采购路径需进一步确认",
        "未找到明确证据说明",
        "暂无法确认",
        "无公开信息说明",
        "缺乏完善测试流程",
    ]
    return any(marker in value for marker in markers)


def _dynamic_values(row: Dict[str, Any]) -> Dict[str, Any]:
    fixed = {
        "table_name",
        "dimension",
        "维度",
        "competitor",
        "target_user",
        "core_scenario",
        "business_model",
        "strategic_judgement",
        "product_form",
        "main_entry",
        "weight",
        "scores",
        "reason",
        "理由",
        "evidence_ids",
        "stage",
        "journey_stage",
        "阶段",
        "user_goal",
        "用户目标",
        "competitor_experience",
        "竞品体验",
        "opportunity",
        "机会点",
        "pending_search_query",
    }
    values = {}
    for key, value in row.items():
        if key in fixed:
            continue
        text = clean_text(value, 180)
        if text:
            values[str(key)] = text
    return values


def _join_dynamic_values(values: Dict[str, Any]) -> str:
    parts = []
    for key, value in values.items():
        text = clean_text(value, 160)
        if text:
            parts.append(f"{key}: {text}")
    return "；".join(parts)


def _evidence_ids(row: Dict[str, Any]) -> List[Any]:
    value = row.get("evidence_ids")
    if not isinstance(value, list):
        value = row.get("证据ID") or row.get("证据ids") or row.get("source_ids")
    return value if isinstance(value, list) else []


def _table_has_content(table: Dict[str, Any]) -> bool:
    """Return True only when a comparison table has at least one useful row."""

    name = table.get("table_name")
    rows = table.get("dimensions") if name == "agent_capability_scorecard" else table.get("rows")
    if not isinstance(rows, list):
        return False
    for row in rows:
        if isinstance(row, dict) and _row_has_required_content(name, row):
            return True
    return False


def _row_has_required_content(table_name: Any, row: Dict[str, Any]) -> bool:
    if table_name == "competitor_positioning_matrix":
        if row.get("dimension") and _dynamic_values(row):
            return True
        return bool(
            clean_text(row.get("competitor"), 80)
            and (
                clean_text(row.get("target_user"), 120)
                or clean_text(row.get("core_scenario"), 120)
                or clean_text(row.get("business_model"), 120)
                or clean_text(row.get("strategic_judgement"), 160)
            )
        )
    if table_name == "agent_capability_scorecard":
        scores = row.get("scores")
        has_scores = isinstance(scores, dict) and any(
            value not in {"", None, "未找到明确证据"} for value in scores.values()
        )
        return bool(
            clean_text(row.get("dimension"), 120)
            and (has_scores or clean_text(row.get("reason"), 160))
        )
    if table_name == "user_journey_comparison":
        return bool(
            clean_text(row.get("stage"), 100)
            and (
                clean_text(row.get("user_goal"), 160)
                or clean_text(row.get("competitor_experience"), 160)
                or clean_text(row.get("opportunity"), 160)
            )
        )
    return False


def _profiles_are_renderable(profiles: List[Dict[str, Any]]) -> bool:
    return bool(profiles) and all(profile.get("competitor") for profile in profiles)


def _tables_are_renderable(tables: List[Dict[str, Any]]) -> bool:
    required = {
        "competitor_positioning_matrix",
        "agent_capability_scorecard",
        "user_journey_comparison",
    }
    table_by_name = {
        table.get("table_name"): table for table in tables if isinstance(table, dict)
    }
    return all(_table_has_content(table_by_name.get(name, {})) for name in required)


def _fallback_comparisons(
    evidence_cards: List[EvidenceCard],
    competitors: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """离线生成基础画像和三张核心表。"""

    names = _competitor_names(evidence_cards, competitors)
    profiles = [_profile_for_competitor(name, evidence_cards) for name in names]
    tables = [
        _positioning_matrix(profiles),
        _capability_scorecard(names, evidence_cards),
        _user_journey_table(evidence_cards),
    ]
    return profiles, tables


def _ensure_required_tables(
    tables: List[Dict[str, Any]],
    evidence_cards: List[EvidenceCard],
    competitors: Sequence[str],
) -> List[Dict[str, Any]]:
    """补齐或替换 LLM 输出中缺失/空壳的必备表。"""

    fallback_profiles, fallback_tables = _fallback_comparisons(
        evidence_cards, competitors
    )
    del fallback_profiles
    fallback_by_name = {table["table_name"]: table for table in fallback_tables}
    table_by_name = {
        table.get("table_name"): table
        for table in tables
        if isinstance(table, dict) and table.get("table_name")
    }
    required_names = [
        "competitor_positioning_matrix",
        "agent_capability_scorecard",
        "user_journey_comparison",
    ]
    merged: List[Dict[str, Any]] = []
    for name in required_names:
        table = table_by_name.get(name)
        if not table or not _table_has_content(table):
            table = fallback_by_name[name]
        merged.append(table)
    return merged


def _competitor_names(
    evidence_cards: List[EvidenceCard],
    competitors: Sequence[str],
) -> List[str]:
    names: List[str] = []
    for competitor in competitors:
        value = clean_text(competitor, 80)
        if value and value not in names:
            names.append(value)
    if not names:
        for card in evidence_cards:
            value = clean_text(card.competitor, 80)
            if value and value not in names:
                names.append(value)
    if not names:
        names.append("未识别竞品")
    return names[:6]


def _profile_for_competitor(
    name: str, evidence_cards: List[EvidenceCard]
) -> Dict[str, Any]:
    cards = _cards_for_competitor(name, evidence_cards)
    return {
        "competitor": name,
        "target_user": _field_from_dimension(
            cards, "user_and_scenario", "未找到明确产品级证据"
        ),
        "core_scenario": _field_from_dimension(
            cards, "task_completion", "未找到明确产品级证据"
        ),
        "product_form": _field_from_dimension(
            cards, "experience", "未找到明确产品级证据"
        ),
        "main_entry": _field_from_dimension(
            cards, "integration", "未找到明确产品级证据"
        ),
        "business_model": _field_from_dimension(
            cards, "pricing_and_gtm", "未找到明确产品级证据"
        ),
        "strategic_judgement": _strategic_judgement(cards),
        "evidence_ids": [card.evidence_id for card in cards[:5]],
    }


def _positioning_matrix(profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "table_name": "competitor_positioning_matrix",
        "rows": profiles,
    }


def _capability_scorecard(
    competitors: Sequence[str],
    evidence_cards: List[EvidenceCard],
) -> Dict[str, Any]:
    """构造 Agent 能力评分表。

    离线评分只基于证据数量和置信度做粗略估计，目的是形成可读、可检测的
    scorecard；真实评分应由更多实测证据校准。
    """

    dimensions = [
        ("任务规划", "task_completion", 0.18),
        ("Tool Use / 集成", "integration", 0.16),
        ("Agent 核心能力", "agent_capability", 0.20),
        ("信任与控制", "trust_and_control", 0.18),
        ("用户体验", "experience", 0.14),
        ("商业化与壁垒", "pricing_and_gtm", 0.14),
    ]
    rows = []
    for label, dimension, weight in dimensions:
        related = [
            card
            for card in evidence_cards
            if card.dimension == dimension and card.competitor in competitors
        ]
        rows.append(
            {
                "dimension": label,
                "weight": weight,
                "scores": {
                    name: _score_competitor_dimension(name, dimension, evidence_cards)
                    for name in competitors
                },
                "reason": _score_reason(label, related),
                "evidence_ids": [card.evidence_id for card in related[:5]],
            }
        )
    return {
        "table_name": "agent_capability_scorecard",
        "scoring_rule": "0=无能力，1=Demo级，2=简单可用，3=业务可用，4=规模部署，5=成熟壁垒",
        "dimensions": rows,
    }


def _user_journey_table(evidence_cards: List[EvidenceCard]) -> Dict[str, Any]:
    stage_map = [
        ("发现与评估", "user_and_scenario", "判断产品是否匹配目标场景"),
        ("创建 Agent", "experience", "快速配置一个可执行任务的 Agent"),
        ("授权与集成", "trust_and_control", "安全连接工具、数据源和业务系统"),
        ("执行任务", "task_completion", "稳定完成规划、执行和异常处理"),
        ("结果交付", "user_feedback", "获得可解释、可采纳、可追溯的结果"),
    ]
    rows = []
    for stage, dimension, user_goal in stage_map:
        cards = [card for card in evidence_cards if card.dimension == dimension]
        rows.append(
            {
                "stage": stage,
                "user_goal": user_goal,
                "competitor_experience": _journey_summary(cards),
                "opportunity": _journey_opportunity(dimension),
                "evidence_ids": [card.evidence_id for card in cards[:4]],
            }
        )
    return {
        "table_name": "user_journey_comparison",
        "rows": rows,
    }


def _cards_for_competitor(
    name: str, evidence_cards: List[EvidenceCard]
) -> List[EvidenceCard]:
    matched = [card for card in evidence_cards if card.competitor == name]
    if matched:
        return matched
    return [
        card
        for card in evidence_cards
        if infer_competitor(f"{card.claim} {card.raw_excerpt}", [name]) == name
    ][:5]


def _field_from_dimension(
    cards: List[EvidenceCard], dimension: str, default: str
) -> str:
    for card in cards:
        if card.dimension == dimension:
            return clean_text(card.claim, 120)
    return default


def _strategic_judgement(cards: List[EvidenceCard]) -> str:
    dimensions = {card.dimension for card in cards}
    if "trust_and_control" in dimensions or "integration" in dimensions:
        return _field_from_dimensions(
            cards,
            ["trust_and_control", "integration"],
            "未找到明确产品级证据",
        )
    if "agent_capability" in dimensions or "task_completion" in dimensions:
        return _field_from_dimensions(
            cards,
            ["agent_capability", "task_completion"],
            "未找到明确产品级证据",
        )
    return "未找到明确产品级证据"


def _field_from_dimensions(
    cards: List[EvidenceCard], dimensions: Sequence[str], default: str
) -> str:
    for dimension in dimensions:
        value = _field_from_dimension(cards, dimension, "")
        if value:
            return value
    return default


def _score_competitor_dimension(
    competitor: str,
    dimension: str,
    evidence_cards: List[EvidenceCard],
) -> Any:
    cards = [
        card
        for card in evidence_cards
        if card.dimension == dimension
        and card.competitor == competitor
    ]
    if not cards:
        return "待搜索"
    avg_confidence = sum(card.confidence for card in cards) / len(cards)
    return max(1, min(5, int(round(2 + avg_confidence * 2.5))))


def _score_reason(label: str, cards: List[EvidenceCard]) -> str:
    if not cards:
        return "未找到明确产品级证据"
    selected = max(cards, key=lambda card: card.confidence)
    return clean_text(selected.claim, 160)


def _journey_summary(cards: List[EvidenceCard]) -> str:
    if not cards:
        return "现有资料未提供明确描述。"
    return clean_text(cards[0].claim, 160)


def _journey_opportunity(dimension: str) -> str:
    mapping = {
        "user_and_scenario": "用更明确的场景模板降低用户评估成本。",
        "experience": "提供半自动配置向导和可复用模板。",
        "trust_and_control": "补齐分级授权、审批、人审和日志回放。",
        "task_completion": "强化任务状态展示、异常处理和结果验证。",
        "user_feedback": "把用户痛点转成可追踪的产品改进指标。",
    }
    return mapping.get(dimension, "围绕证据不足处补充调研和实测。")


def _log(config: WritingAgentConfig, message: str) -> None:
    if config.verbose and config.progress_printer:
        config.progress_printer(message)

"""横向对比 Agent。

本节点负责把证据和洞察组织成 PM 报告里的三类核心对比表：竞品定位矩阵、
Agent 能力评分表、用户旅程对比表。表格输出保持 dict/list，方便报告层渲染，
也方便下游检测。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence, Tuple

try:
    from .evidence_structurer import infer_competitor
    from .llm_utils import call_json_llm, clean_text
    from .models import EvidenceCard, PMInsight, WritingAgentConfig
except ImportError:
    from report_agent.evidence_structurer import infer_competitor
    from report_agent.llm_utils import call_json_llm, clean_text
    from report_agent.models import EvidenceCard, PMInsight, WritingAgentConfig


def build_comparisons(
    evidence_cards: List[EvidenceCard],
    pm_insights: List[PMInsight],
    competitors: Sequence[str],
    target_domain: str,
    config: WritingAgentConfig,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """生成竞品画像和横向对比表。"""

    profiles, tables = _comparisons_from_llm(
        evidence_cards=evidence_cards,
        pm_insights=pm_insights,
        competitors=list(competitors),
        target_domain=target_domain,
        config=config,
    )
    if profiles and tables:
        normalized_profiles = _normalize_llm_profiles(profiles)
        normalized_tables = _normalize_llm_tables(tables)
        if _profiles_are_renderable(normalized_profiles) and _tables_are_renderable(
            normalized_tables
        ):
            return normalized_profiles, _ensure_required_tables(
                normalized_tables, evidence_cards, competitors
            )
    return _fallback_comparisons(evidence_cards, competitors)


def _comparisons_from_llm(
    *,
    evidence_cards: List[EvidenceCard],
    pm_insights: List[PMInsight],
    competitors: List[str],
    target_domain: str,
    config: WritingAgentConfig,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """让 LLM 生成对比表。

    LLM 只生成结构化 JSON；缺表或格式不对时，由 `_ensure_required_tables`
    和 fallback 保证报告必需表格不缺失。
    """

    data = call_json_llm(
        config=config,
        system_prompt="你是产品竞品横向对比专家，只输出 JSON。",
        user_prompt=f"""
分析领域:
{target_domain}

候选竞品:
{json.dumps(competitors, ensure_ascii=False)}

Evidence Cards:
{json.dumps([card.to_dict() for card in evidence_cards], ensure_ascii=False, indent=2)}

PM Insights:
{json.dumps([insight.to_dict() for insight in pm_insights], ensure_ascii=False, indent=2)}

请输出竞品画像和三张对比表:
1. competitor_positioning_matrix
2. agent_capability_scorecard
3. user_journey_comparison

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
      "table_name": "competitor_positioning_matrix",
      "rows": []
    }},
    {{
      "table_name": "agent_capability_scorecard",
      "scoring_rule": "0=无能力，1=Demo级，2=简单可用，3=业务可用，4=规模部署，5=成熟壁垒",
      "dimensions": []
    }},
    {{
      "table_name": "user_journey_comparison",
      "rows": []
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
    return profiles, tables


def _normalize_llm_profiles(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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


def _normalize_llm_tables(tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only tables already compatible with report_composer."""

    normalized: List[Dict[str, Any]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        name = table.get("table_name")
        if name == "competitor_positioning_matrix" and isinstance(
            table.get("rows"), list
        ):
            normalized.append(table)
        elif name == "agent_capability_scorecard" and isinstance(
            table.get("dimensions"), list
        ):
            normalized.append(table)
        elif name == "user_journey_comparison" and isinstance(table.get("rows"), list):
            normalized.append(table)
    return normalized


def _profiles_are_renderable(profiles: List[Dict[str, Any]]) -> bool:
    return bool(profiles) and all(profile.get("competitor") for profile in profiles)


def _tables_are_renderable(tables: List[Dict[str, Any]]) -> bool:
    names = {table.get("table_name") for table in tables if isinstance(table, dict)}
    return {
        "competitor_positioning_matrix",
        "agent_capability_scorecard",
        "user_journey_comparison",
    }.issubset(names)


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
    """补齐 LLM 输出中缺失的必备表。"""

    names = {table.get("table_name") for table in tables if isinstance(table, dict)}
    fallback_profiles, fallback_tables = _fallback_comparisons(
        evidence_cards, competitors
    )
    del fallback_profiles
    for table in fallback_tables:
        if table["table_name"] not in names:
            tables.append(table)
    return tables


def _competitor_names(
    evidence_cards: List[EvidenceCard],
    competitors: Sequence[str],
) -> List[str]:
    names: List[str] = []
    for competitor in competitors:
        value = clean_text(competitor, 80)
        if value and value not in names:
            names.append(value)
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
            cards, "user_and_scenario", "从现有资料看，目标用户仍需进一步验证"
        ),
        "core_scenario": _field_from_dimension(
            cards, "task_completion", "围绕 Agent 自动化任务完成与报告生成"
        ),
        "product_form": _field_from_dimension(
            cards, "experience", "Web / API / 工作台等产品形态"
        ),
        "main_entry": _field_from_dimension(
            cards, "integration", "Web、API 或企业系统集成入口"
        ),
        "business_model": _field_from_dimension(
            cards, "pricing_and_gtm", "订阅或企业采购路径需进一步确认"
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
        related = [card for card in evidence_cards if card.dimension == dimension]
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
        return "资料显示其在企业落地、集成或可信控制上具有分析价值。"
    if "agent_capability" in dimensions or "task_completion" in dimensions:
        return "资料显示其核心竞争点集中在任务闭环和 Agent 能力。"
    return "现有资料有限，需要补充实测与用户反馈后再判断战略位置。"


def _score_competitor_dimension(
    competitor: str,
    dimension: str,
    evidence_cards: List[EvidenceCard],
) -> int:
    cards = [
        card
        for card in evidence_cards
        if card.dimension == dimension
        and (not card.competitor or card.competitor == competitor)
    ]
    if not cards:
        return 2
    avg_confidence = sum(card.confidence for card in cards) / len(cards)
    return max(1, min(5, int(round(2 + avg_confidence * 2.5))))


def _score_reason(label: str, cards: List[EvidenceCard]) -> str:
    if not cards:
        return f"{label} 缺少明确证据，暂按基础可用水平处理。"
    return clean_text(cards[0].claim, 160)


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

"""写作 Agent 的主工作流入口。

本文件只负责 orchestration：按“证据 -> 洞察 -> 对比 -> SWOT -> 策略 ->
报告 -> 自检”的顺序串联各节点。具体生成逻辑放在独立 agent 文件中，避免
core 变成一个难维护的大函数。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from .comparison_builder import build_comparisons
    from .evidence_structurer import structure_evidence
    from .insight_extractor import extract_pm_insights
    from .models import ReportPackage, ReportState, WritingAgentConfig
    from .precheck import precheck_report_package
    from .report_composer import compose_report
    from .strategy_recommender import generate_recommendations
    from .swot_generator import generate_swot
    from .table_gap_search import enrich_tables_with_gap_search
except ImportError:
    from report_agent.comparison_builder import build_comparisons
    from report_agent.evidence_structurer import structure_evidence
    from report_agent.insight_extractor import extract_pm_insights
    from report_agent.models import ReportPackage, ReportState, WritingAgentConfig
    from report_agent.precheck import precheck_report_package
    from report_agent.report_composer import compose_report
    from report_agent.strategy_recommender import generate_recommendations
    from report_agent.swot_generator import generate_swot
    from report_agent.table_gap_search import enrich_tables_with_gap_search


def run_writing_agent(
    search_results: Iterable[Any],
    config: Optional[WritingAgentConfig] = None,
    *,
    task_id: str = "task_001",
    analysis_goal: str = "生成面向产品经理的竞品分析报告",
    target_domain: str = "AI Agent",
    competitors: Optional[Sequence[str]] = None,
) -> ReportPackage:
    """运行完整写作链路并返回可检测的报告包。

    Args:
        search_results: 上游搜索模块输出，兼容 SearchResult、dict 或属性对象。
        config: 写作 Agent 配置；`use_llm=False` 时全流程走本地 fallback。
        task_id: 外部任务标识，会原样写入 ReportPackage。
        analysis_goal: 本次报告服务的产品决策目标。
        target_domain: 竞品分析领域。
        competitors: 可选竞品名，用于更稳定地归属 evidence 和画像。

    Returns:
        ReportPackage: Markdown 报告、结构化分析、证据映射和生成轨迹。
    """

    runtime_config = config or WritingAgentConfig()
    competitor_list = list(competitors or [])

    # 第一步先把外部输入标准化并拆成 evidence cards。后续所有结论都从
    # evidence_id 出发，保证可以被下游检测模块追溯。
    _log(runtime_config, "[writing-agent] structure evidence")
    sources, evidence_cards = structure_evidence(
        search_results,
        runtime_config,
        analysis_goal=analysis_goal,
        target_domain=target_domain,
        competitors=competitor_list,
    )
    state = ReportState(
        task_id=task_id,
        analysis_goal=analysis_goal,
        target_domain=target_domain,
        competitors=competitor_list,
        sources=sources,
        evidence_cards=evidence_cards,
    )
    _trace(
        state,
        "evidence_structuring",
        [source.source_id for source in sources],
        [card.evidence_id for card in evidence_cards],
    )

    # 洞察层只把证据转成 PM 语言，不直接写长报告。
    _log(runtime_config, "[writing-agent] extract PM insights")
    state.pm_insights = extract_pm_insights(
        state.evidence_cards,
        runtime_config,
        analysis_goal=analysis_goal,
        target_domain=target_domain,
    )
    _trace(
        state,
        "pm_insight_extraction",
        [card.evidence_id for card in state.evidence_cards],
        [insight.insight_id for insight in state.pm_insights],
    )

    # 对比层固定产出核心表，避免报告退化成“功能点流水账”。
    _log(runtime_config, "[writing-agent] build comparison tables")
    state.competitor_profiles, state.comparison_tables = build_comparisons(
        state.evidence_cards,
        state.pm_insights,
        competitor_list,
        target_domain,
        runtime_config,
        enrich_table_gaps=False,
    )
    _trace(
        state,
        "comparison_building",
        [insight.insight_id for insight in state.pm_insights],
        [table.get("table_name", "table") for table in state.comparison_tables],
    )

    base_profiles = deepcopy(state.competitor_profiles)
    base_tables = deepcopy(state.comparison_tables)
    _log(runtime_config, "[writing-agent] parallel SWOT and table gap enrichment")
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="report-agent-report") as executor:
        swot_future = executor.submit(
            generate_swot,
            state.evidence_cards,
            state.pm_insights,
            base_profiles,
            runtime_config,
        )
        table_gap_future = executor.submit(
            enrich_tables_with_gap_search,
            profiles=deepcopy(base_profiles),
            tables=deepcopy(base_tables),
            evidence_cards=state.evidence_cards,
            competitors=competitor_list,
            target_domain=target_domain,
            config=runtime_config,
        )

        # SWOT 只消费已结构化的 evidence/insight/profile，避免重新自由发挥。
        _log(runtime_config, "[writing-agent] generate SWOT")
        state.swot = swot_future.result()
        _trace(
            state,
            "swot_generation",
            [insight.insight_id for insight in state.pm_insights],
            _swot_refs(state),
        )

        _log(runtime_config, "[writing-agent] generate recommendations")
        state.recommendations = generate_recommendations(
            state.evidence_cards,
            state.pm_insights,
            state.swot,
            runtime_config,
        )
        _trace(
            state,
            "strategy_recommendation",
            _swot_refs(state),
            [f"rec_{index + 1:03d}" for index, _ in enumerate(state.recommendations)],
        )

        _log(runtime_config, "[writing-agent] wait table gap enrichment")
        state.competitor_profiles, state.comparison_tables = _table_gap_result_or_base(
            table_gap_future,
            base_profiles,
            base_tables,
            runtime_config,
        )
        _trace(
            state,
            "table_gap_enrichment",
            [table.get("table_name", "table") for table in base_tables],
            [table.get("table_name", "table") for table in state.comparison_tables],
        )

    # claim_evidence_map 是给下游质检 Agent 的关键协议字段。
    state.claim_evidence_map = _build_claim_evidence_map(state)

    _log(runtime_config, "[writing-agent] compose report")
    state.report_markdown = compose_report(state, runtime_config)
    _trace(
        state,
        "report_composition",
        [table.get("table_name", "table") for table in state.comparison_tables],
        ["report_markdown"],
    )

    precheck_report_package(state)
    return _package_from_state(state)


def _build_claim_evidence_map(state: ReportState) -> List[Dict[str, Any]]:
    """把每个 evidence claim 映射回 evidence/source。

    这里不把 PM insight 和 SWOT 额外展开为 claim，是为了保证最小可验证单元
    足够清晰；下游可以通过 evidence_ids 继续关联到更高层判断。
    """

    source_by_evidence = {
        card.evidence_id: card.source_id for card in state.evidence_cards
    }
    items: List[Dict[str, Any]] = []
    for index, card in enumerate(state.evidence_cards, 1):
        items.append(
            {
                "claim_id": f"claim_{index:03d}",
                "claim": card.claim,
                "evidence_ids": [card.evidence_id],
                "source_ids": [source_by_evidence[card.evidence_id]],
                "confidence": card.confidence,
            }
        )
    return items


def _table_gap_result_or_base(
    future: Any,
    base_profiles: List[Dict[str, Any]],
    base_tables: List[Dict[str, Any]],
    config: WritingAgentConfig,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    try:
        profiles, tables = future.result()
    except Exception as exc:
        _log(
            config,
            f"[writing-agent] table gap enrichment failed, using base tables: {exc}",
        )
        return deepcopy(base_profiles), deepcopy(base_tables)
    if isinstance(profiles, list) and isinstance(tables, list):
        return profiles, tables
    _log(config, "[writing-agent] table gap enrichment returned invalid result; using base tables")
    return deepcopy(base_profiles), deepcopy(base_tables)


def _structured_analysis_from_state(state: ReportState) -> Dict[str, Any]:
    """生成对外稳定的 structured_analysis。

    同时保留 `recommendations` 和 `product_recommendations` 两个 key，兼容
    文档示例和更直观的调用命名。
    """

    return {
        "executive_summary": {
            "analysis_goal": state.analysis_goal,
            "target_domain": state.target_domain,
            "key_findings": [insight.title for insight in state.pm_insights[:5]],
        },
        "evidence_cards": [card.to_dict() for card in state.evidence_cards],
        "pm_insights": [insight.to_dict() for insight in state.pm_insights],
        "competitor_profiles": state.competitor_profiles,
        "comparison_tables": state.comparison_tables,
        "swot": state.swot.to_dict(),
        "recommendations": [rec.to_dict() for rec in state.recommendations],
        "product_recommendations": [rec.to_dict() for rec in state.recommendations],
    }


def _package_from_state(state: ReportState) -> ReportPackage:
    """把内部状态压缩成对外输出包。"""

    return ReportPackage(
        task_id=state.task_id,
        report_markdown=state.report_markdown,
        structured_analysis=_structured_analysis_from_state(state),
        claim_evidence_map=state.claim_evidence_map,
        generation_trace=state.generation_trace,
        sources=[source.to_dict() for source in state.sources],
        missing_info=state.missing_info,
        low_confidence_claims=state.low_confidence_claims,
    )


def _swot_refs(state: ReportState) -> List[str]:
    refs: List[str] = []
    for prefix, items in (
        ("strength", state.swot.strengths),
        ("weakness", state.swot.weaknesses),
        ("opportunity", state.swot.opportunities),
        ("threat", state.swot.threats),
    ):
        refs.extend(f"{prefix}_{index + 1:03d}" for index, _ in enumerate(items))
    return refs


def _has_pending_table_cells(tables: List[Dict[str, Any]]) -> bool:
    for table in tables:
        if not isinstance(table, dict):
            continue
        rows = (
            table.get("dimensions")
            if table.get("table_name") == "agent_capability_scorecard"
            else table.get("rows")
        )
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and _contains_pending_value(row):
                return True
    return False


def _contains_pending_value(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_pending_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_pending_value(item) for item in value)
    return isinstance(value, str) and value.strip().startswith("待搜索")


def _can_use_table_gap_llm(config: WritingAgentConfig) -> bool:
    return bool(
        config.use_llm
        and config.llm_api_key
        and config.llm_base_url
        and config.llm_model
        and getattr(config, "table_gap_search_enabled", True)
    )


def _trace(
    state: ReportState, step: str, input_refs: List[str], output_refs: List[str]
) -> None:
    """记录每个节点消费了哪些引用、产出了哪些引用。"""

    state.generation_trace.append(
        {
            "step": step,
            "input_refs": input_refs,
            "output_refs": output_refs,
        }
    )


def _log(config: WritingAgentConfig, message: str) -> None:
    if config.verbose and config.progress_printer:
        config.progress_printer(message)

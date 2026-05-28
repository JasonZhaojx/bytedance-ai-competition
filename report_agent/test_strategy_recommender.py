"""Focused checks for strategy recommendation timeframe normalization."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from report_agent.models import ProductRecommendation
from report_agent.strategy_recommender import (
    _normalize_timeframe,
    _rebalance_timeframes,
)


def test_normalize_timeframe_understands_chinese_and_numeric_values() -> None:
    assert _normalize_timeframe("30天", 0) == "30_days"
    assert _normalize_timeframe("中期", 0) == "60_days"
    assert _normalize_timeframe("90 days", 0) == "90_days"
    assert _normalize_timeframe("模型没按格式返回", 2) == "90_days"


def test_rebalance_timeframes_prevents_all_60_days_output() -> None:
    recommendations = [
        ProductRecommendation(
            priority="P0",
            timeframe="60_days",
            action=f"action {index}",
            reason="reason",
            expected_impact="impact",
            risk="risk",
            evidence_ids=["ev_001"],
            success_metric="metric",
        )
        for index in range(3)
    ]

    balanced = _rebalance_timeframes(recommendations)

    assert [rec.timeframe for rec in balanced] == ["30_days", "60_days", "90_days"]


if __name__ == "__main__":
    test_normalize_timeframe_understands_chinese_and_numeric_values()
    test_rebalance_timeframes_prevents_all_60_days_output()
    print("strategy recommender focused test passed")

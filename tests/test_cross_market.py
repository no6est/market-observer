"""Tests for cross-market analysis (GLOBAL mode)."""

from __future__ import annotations

import pytest

from app.enrichers.monthly_analysis import _compute_cross_market_analysis
from app.enrichers.market_response import split_reaction_lag_by_market


class TestComputeCrossMarketAnalysis:
    def _make_enriched(self) -> list[dict]:
        """Create mixed US/JP enriched events."""
        return [
            {"ticker": "NVDA", "date": "2026-02-01", "narrative_category": "AI/LLM/自動化"},
            {"ticker": "NVDA", "date": "2026-02-02", "narrative_category": "AI/LLM/自動化"},
            {"ticker": "MSFT", "date": "2026-02-01", "narrative_category": "AI/LLM/自動化"},
            {"ticker": "XOM", "date": "2026-02-01", "narrative_category": "エネルギー/資源"},
            {"ticker": "7203.T", "date": "2026-02-01", "narrative_category": "ガバナンス/経営"},
            {"ticker": "6758.T", "date": "2026-02-01", "narrative_category": "半導体/供給網"},
            {"ticker": "8035.T", "date": "2026-02-02", "narrative_category": "半導体/供給網"},
            {"ticker": "9984.T", "date": "2026-02-01", "narrative_category": "AI/LLM/自動化"},
        ]

    def test_narrative_comparison(self) -> None:
        enriched = self._make_enriched()
        result = _compute_cross_market_analysis(enriched, [], {})
        comparison = result["narrative_comparison"]
        assert len(comparison) > 0
        cats = {c["category"] for c in comparison}
        assert "AI/LLM/自動化" in cats

    def test_notable_differences(self) -> None:
        enriched = self._make_enriched()
        result = _compute_cross_market_analysis(enriched, [], {})
        comparison = result["narrative_comparison"]
        # AI should have high US share (3/4) vs JP (1/4)
        ai_entry = next(c for c in comparison if c["category"] == "AI/LLM/自動化")
        assert ai_entry["us_pct"] > ai_entry["jp_pct"]

    def test_empty_enriched(self) -> None:
        result = _compute_cross_market_analysis([], [], {})
        assert result["narrative_comparison"] == []

    def test_reaction_speed_with_lag_data(self) -> None:
        enriched = self._make_enriched()
        reaction_lag = {
            "event_lags": [
                {"ticker": "NVDA", "date": "2026-02-01", "reacted": True, "lag_days": 1},
                {"ticker": "MSFT", "date": "2026-02-01", "reacted": True, "lag_days": 3},
                {"ticker": "7203.T", "date": "2026-02-01", "reacted": True, "lag_days": 2},
                {"ticker": "6758.T", "date": "2026-02-01", "reacted": False, "lag_days": None},
            ],
        }
        full_result = {"reaction_lag": reaction_lag}
        result = _compute_cross_market_analysis(enriched, [], full_result)
        speed = result["reaction_speed_comparison"]
        assert "us" in speed
        assert "jp" in speed
        assert speed["us"]["total"] == 2
        assert speed["jp"]["total"] == 2


class TestSplitReactionLagByMarket:
    def test_split(self) -> None:
        lag_result = {
            "event_lags": [
                {"ticker": "NVDA", "reacted": True, "lag_days": 1},
                {"ticker": "7203.T", "reacted": True, "lag_days": 3},
                {"ticker": "MSFT", "reacted": False, "lag_days": None},
            ],
        }
        split = split_reaction_lag_by_market(lag_result)
        assert split["US"]["total"] == 2
        assert split["JP"]["total"] == 1

    def test_empty(self) -> None:
        split = split_reaction_lag_by_market({"event_lags": []})
        assert split["US"]["total"] == 0
        assert split["JP"]["total"] == 0

    def test_all_us(self) -> None:
        lag_result = {
            "event_lags": [
                {"ticker": "NVDA", "reacted": True, "lag_days": 1},
                {"ticker": "MSFT", "reacted": True, "lag_days": 2},
            ],
        }
        split = split_reaction_lag_by_market(lag_result)
        assert split["US"]["total"] == 2
        assert split["JP"]["total"] == 0

    def test_stats_computed(self) -> None:
        lag_result = {
            "event_lags": [
                {"ticker": "NVDA", "reacted": True, "lag_days": 1},
                {"ticker": "NVDA", "reacted": True, "lag_days": 5},
                {"ticker": "7203.T", "reacted": True, "lag_days": 0},
                {"ticker": "6758.T", "reacted": False, "lag_days": None},
            ],
        }
        split = split_reaction_lag_by_market(lag_result)
        us = split["US"]
        assert us["avg_lag"] == 3.0
        assert us["immediate_rate"] == 0.5

        jp = split["JP"]
        assert jp["total"] == 2
        assert jp["immediate_rate"] == 0.5
        assert jp["no_reaction_rate"] == 0.5

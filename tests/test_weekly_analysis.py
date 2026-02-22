"""Tests for weekly meta-analysis."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.enrichers.weekly_analysis import compute_weekly_analysis


def _make_mock_db(
    enriched_events: list[dict] | None = None,
    history: list[dict] | None = None,
) -> MagicMock:
    db = MagicMock()
    db.get_enriched_events_history.return_value = enriched_events or []
    db.get_narrative_history.return_value = history or []
    return db


class TestComputeWeeklyAnalysis:
    def test_empty_db(self) -> None:
        db = _make_mock_db()
        result = compute_weekly_analysis(db, days=7)
        assert result["period"] == "過去7日間"
        assert result["shock_type_distribution"] == {}
        assert result["narrative_trend"] == []

    def test_shock_type_distribution(self) -> None:
        enriched = [
            {"ticker": "NVDA", "shock_type": "Tech shock", "sis": 0.8, "ai_centricity": 0.9, "summary": "AI surge", "narrative_category": "AI/LLM/自動化"},
            {"ticker": "MSFT", "shock_type": "Tech shock", "sis": 0.7, "ai_centricity": 0.85, "summary": "AI launch", "narrative_category": "AI/LLM/自動化"},
            {"ticker": "CRWD", "shock_type": "Regulation shock", "sis": 0.6, "ai_centricity": 0.1, "summary": "SEC probe", "narrative_category": "規制/政策/地政学"},
        ]
        db = _make_mock_db(enriched_events=enriched)
        result = compute_weekly_analysis(db)
        dist = result["shock_type_distribution"]
        assert "テクノロジーショック" in dist
        assert dist["テクノロジーショック"] == 2
        assert "規制ショック" in dist
        assert dist["規制ショック"] == 1

    def test_narrative_trend(self) -> None:
        history = [
            {"date": "2025-01-14", "category": "AI/LLM/自動化", "event_pct": 0.5},
            {"date": "2025-01-14", "category": "その他", "event_pct": 0.5},
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.7},
            {"date": "2025-01-15", "category": "その他", "event_pct": 0.3},
        ]
        db = _make_mock_db(history=history)
        result = compute_weekly_analysis(db)
        trend = result["narrative_trend"]
        assert len(trend) == 2
        assert trend[0]["date"] == "2025-01-14"
        assert trend[1]["date"] == "2025-01-15"

    def test_turning_point_detection(self) -> None:
        history = [
            {"date": "2025-01-13", "category": "AI/LLM/自動化", "event_pct": 0.3},
            {"date": "2025-01-13", "category": "規制/政策/地政学", "event_pct": 0.7},
            {"date": "2025-01-14", "category": "AI/LLM/自動化", "event_pct": 0.4},
            {"date": "2025-01-14", "category": "規制/政策/地政学", "event_pct": 0.6},
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.7},
            {"date": "2025-01-15", "category": "規制/政策/地政学", "event_pct": 0.3},
        ]
        db = _make_mock_db(history=history)
        result = compute_weekly_analysis(db)
        tp = result["turning_point_candidates"]
        assert len(tp) > 0
        # AI went from 0.3 to 0.7 = +0.4 (>= 0.15 threshold)
        ai_tp = [t for t in tp if "AI" in t["category"]]
        assert len(ai_tp) > 0
        assert ai_tp[0]["direction"] == "上昇"

    def test_non_ai_highlights(self) -> None:
        enriched = [
            {"ticker": "NVDA", "shock_type": "Tech shock", "sis": 0.9, "ai_centricity": 0.95, "summary": "AI GPU demand", "narrative_category": "AI/LLM/自動化"},
            {"ticker": "XOM", "shock_type": "Business model shock", "sis": 0.7, "ai_centricity": 0.05, "summary": "Oil supply disruption", "narrative_category": "エネルギー/資源"},
            {"ticker": "JPM", "shock_type": "Execution signal", "sis": 0.5, "ai_centricity": 0.1, "summary": "Rate policy change", "narrative_category": "金融/金利/流動性"},
        ]
        db = _make_mock_db(enriched_events=enriched)
        result = compute_weekly_analysis(db)
        non_ai = result["non_ai_highlights"]
        tickers = [h["ticker"] for h in non_ai]
        assert "XOM" in tickers
        assert "JPM" in tickers
        # NVDA has high ai_centricity, should not appear
        assert "NVDA" not in tickers

    def test_non_ai_highlights_include_metadata(self) -> None:
        enriched = [
            {"ticker": "XOM", "shock_type": "Business model shock", "sis": 0.7, "ai_centricity": 0.05, "summary": "Oil disruption", "narrative_category": "エネルギー/資源"},
        ]
        db = _make_mock_db(enriched_events=enriched)
        result = compute_weekly_analysis(db)
        non_ai = result["non_ai_highlights"]
        assert len(non_ai) == 1
        assert non_ai[0]["narrative_category"] == "エネルギー/資源"
        assert non_ai[0]["shock_type"] == "Business model shock"

    def test_org_impact_hypotheses(self) -> None:
        enriched = [
            {"ticker": f"T{i}", "shock_type": "Tech shock", "sis": 0.8, "ai_centricity": 0.5, "summary": "Tech event", "narrative_category": "AI/LLM/自動化"}
            for i in range(5)
        ]
        history = [
            {"date": "2025-01-13", "category": "AI/LLM/自動化", "event_pct": 0.3},
            {"date": "2025-01-13", "category": "その他", "event_pct": 0.7},
            {"date": "2025-01-14", "category": "AI/LLM/自動化", "event_pct": 0.5},
            {"date": "2025-01-14", "category": "その他", "event_pct": 0.5},
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.8},
            {"date": "2025-01-15", "category": "その他", "event_pct": 0.2},
        ]
        db = _make_mock_db(enriched_events=enriched, history=history)
        result = compute_weekly_analysis(db)
        hyps = result["org_impact_hypotheses"]
        assert len(hyps) > 0
        assert "hypothesis" in hyps[0]
        assert "evidence" in hyps[0]

    def test_result_keys(self) -> None:
        db = _make_mock_db()
        result = compute_weekly_analysis(db)
        expected_keys = {
            "shock_type_distribution",
            "narrative_trend",
            "non_ai_highlights",
            "turning_point_candidates",
            "org_impact_hypotheses",
            "bias_correction_actions",
            "propagation_structure",
            "spp_top3",
            "regime_history",
            "event_persistence",
            "week_over_week",
            "regime_narrative_cross",
            "early_drift_candidates",
            "period",
        }
        assert set(result.keys()) == expected_keys

    def test_bias_correction_actions_generated(self) -> None:
        """Bias corrections suggested when category distribution is imbalanced."""
        enriched = [
            {"ticker": f"T{i}", "shock_type": "Tech shock", "sis": 0.8,
             "ai_centricity": 0.9, "summary": "AI event",
             "narrative_category": "AI/LLM/自動化"}
            for i in range(5)
        ] + [
            {"ticker": "XOM", "shock_type": "Regulation shock", "sis": 0.5,
             "ai_centricity": 0.05, "summary": "Energy",
             "narrative_category": "エネルギー/資源"},
        ]
        history = [
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.83},
            {"date": "2025-01-15", "category": "エネルギー/資源", "event_pct": 0.17},
        ]
        db = _make_mock_db(enriched_events=enriched, history=history)
        result = compute_weekly_analysis(db)
        actions = result["bias_correction_actions"]
        assert len(actions) > 0
        assert all("action" in a and "reason" in a for a in actions)

    def test_bias_correction_over_concentration_warning(self) -> None:
        """Over-concentrated categories should get a warning action."""
        history = [
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.80},
            {"date": "2025-01-15", "category": "その他", "event_pct": 0.20},
        ]
        db = _make_mock_db(history=history)
        result = compute_weekly_analysis(db)
        actions = result["bias_correction_actions"]
        over_actions = [a for a in actions if "過集中" in a["action"]]
        assert len(over_actions) > 0

    def test_turning_point_requires_persistence(self) -> None:
        """V-shaped 1-day spike should be excluded from turning points."""
        # Day1: 30%, Day2: 60% (spike), Day3: 30% (revert) => not persistent
        history = [
            {"date": "2025-01-13", "category": "AI/LLM/自動化", "event_pct": 0.30},
            {"date": "2025-01-13", "category": "その他", "event_pct": 0.70},
            {"date": "2025-01-14", "category": "AI/LLM/自動化", "event_pct": 0.60},
            {"date": "2025-01-14", "category": "その他", "event_pct": 0.40},
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.30},
            {"date": "2025-01-15", "category": "その他", "event_pct": 0.70},
        ]
        db = _make_mock_db(history=history)
        result = compute_weekly_analysis(db)
        tp = result["turning_point_candidates"]
        # V-shape spike has no persistence → no turning points
        ai_tp = [t for t in tp if "AI" in t["category"]]
        assert len(ai_tp) == 0

    def test_turning_point_fallback_short_data(self) -> None:
        """With only 2 days, fallback to first-vs-last comparison."""
        history = [
            {"date": "2025-01-14", "category": "AI/LLM/自動化", "event_pct": 0.30},
            {"date": "2025-01-14", "category": "金融/金利/流動性", "event_pct": 0.70},
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.70},
            {"date": "2025-01-15", "category": "金融/金利/流動性", "event_pct": 0.30},
        ]
        db = _make_mock_db(history=history)
        result = compute_weekly_analysis(db)
        tp = result["turning_point_candidates"]
        assert len(tp) > 0
        ai_tp = [t for t in tp if "AI" in t["category"]]
        assert len(ai_tp) == 1
        assert ai_tp[0]["direction"] == "上昇"

    def test_bias_correction_uses_week_average_with_surge(self) -> None:
        """Bias corrections use week average; surge flag on large latest divergence."""
        enriched = [
            {"ticker": "JPM", "shock_type": "Execution signal", "sis": 0.5,
             "ai_centricity": 0.05, "summary": "Rate event",
             "narrative_category": "金融/金利/流動性"},
        ]
        history = [
            # Day1-3: 金融 0%, Day4: 金融 22% (surge on last day)
            # Week avg = 0.22/4 = 5.5% (below 6.25% threshold)
            # Surge: 22% - 5.5% = 16.5pt >= 15pt
            {"date": "2025-01-12", "category": "金融/金利/流動性", "event_pct": 0.0},
            {"date": "2025-01-12", "category": "AI/LLM/自動化", "event_pct": 1.0},
            {"date": "2025-01-13", "category": "金融/金利/流動性", "event_pct": 0.0},
            {"date": "2025-01-13", "category": "AI/LLM/自動化", "event_pct": 1.0},
            {"date": "2025-01-14", "category": "金融/金利/流動性", "event_pct": 0.0},
            {"date": "2025-01-14", "category": "AI/LLM/自動化", "event_pct": 1.0},
            {"date": "2025-01-15", "category": "金融/金利/流動性", "event_pct": 0.22},
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.78},
        ]
        db = _make_mock_db(enriched_events=enriched, history=history)
        result = compute_weekly_analysis(db)
        actions = result["bias_correction_actions"]
        # 金融 week avg 5.5% < 6.25% => under-represented with events => action
        fin_actions = [a for a in actions if a["category"] == "金融/金利/流動性"]
        assert len(fin_actions) == 1
        # Surge flag: latest 22% vs avg 5.5% => 16.5pt divergence >= 15pt
        assert fin_actions[0].get("recent_surge") is True
        assert fin_actions[0].get("latest_pct") == 0.22

    def test_event_persistence_tracking(self) -> None:
        """Track ticker appearances across days with SPP trend."""
        enriched = [
            {"ticker": "NVDA", "date": "2025-01-13", "shock_type": "Tech shock",
             "sis": 0.8, "ai_centricity": 0.9, "summary": "Day1", "spp": 0.5,
             "narrative_category": "AI/LLM/自動化"},
            {"ticker": "NVDA", "date": "2025-01-14", "shock_type": "Tech shock",
             "sis": 0.8, "ai_centricity": 0.9, "summary": "Day2", "spp": 0.6,
             "narrative_category": "AI/LLM/自動化"},
            {"ticker": "NVDA", "date": "2025-01-15", "shock_type": "Tech shock",
             "sis": 0.8, "ai_centricity": 0.9, "summary": "Day3", "spp": 0.7,
             "narrative_category": "AI/LLM/自動化"},
            {"ticker": "MSFT", "date": "2025-01-15", "shock_type": "Tech shock",
             "sis": 0.5, "ai_centricity": 0.8, "summary": "Single day", "spp": 0.3,
             "narrative_category": "AI/LLM/自動化"},
        ]
        db = _make_mock_db(enriched_events=enriched)
        result = compute_weekly_analysis(db)
        ep = result["event_persistence"]
        assert len(ep) == 2
        nvda = [e for e in ep if e["ticker"] == "NVDA"][0]
        assert nvda["days_appeared"] == 3
        assert nvda["total_days"] == 3  # 3 distinct observed dates
        assert nvda["spp_trend"] == "上昇"  # 0.5 -> 0.7
        assert nvda["latest_spp"] == 0.7

    def test_event_persistence_total_days_is_observed(self) -> None:
        """total_days counts observed dates, not calendar days."""
        enriched = [
            {"ticker": "NVDA", "date": "2025-01-13", "shock_type": "Tech shock",
             "sis": 0.8, "ai_centricity": 0.9, "summary": "D1", "spp": 0.5,
             "narrative_category": "AI/LLM/自動化"},
            {"ticker": "MSFT", "date": "2025-01-15", "shock_type": "Tech shock",
             "sis": 0.5, "ai_centricity": 0.8, "summary": "D3", "spp": 0.3,
             "narrative_category": "AI/LLM/自動化"},
            {"ticker": "GOOG", "date": "2025-01-17", "shock_type": "Tech shock",
             "sis": 0.4, "ai_centricity": 0.7, "summary": "D5", "spp": 0.2,
             "narrative_category": "AI/LLM/自動化"},
        ]
        db = _make_mock_db(enriched_events=enriched)
        result = compute_weekly_analysis(db)
        ep = result["event_persistence"]
        # 3 distinct dates across 5 calendar days
        assert all(e["total_days"] == 3 for e in ep)

    def test_non_ai_highlights_include_ai_centricity(self) -> None:
        """Non-AI highlights include ai_centricity field."""
        enriched = [
            {"ticker": "XOM", "shock_type": "Business model shock", "sis": 0.7,
             "ai_centricity": 0.05, "summary": "Oil event",
             "narrative_category": "エネルギー/資源"},
        ]
        db = _make_mock_db(enriched_events=enriched)
        result = compute_weekly_analysis(db)
        non_ai = result["non_ai_highlights"]
        assert len(non_ai) == 1
        assert "ai_centricity" in non_ai[0]
        assert non_ai[0]["ai_centricity"] == 0.05


def _make_mock_db_with_prev(
    curr_enriched: list[dict] | None = None,
    curr_history: list[dict] | None = None,
    curr_regime: list[dict] | None = None,
    prev_enriched: list[dict] | None = None,
    prev_history: list[dict] | None = None,
    prev_regime: list[dict] | None = None,
) -> MagicMock:
    """Mock DB that returns different data for current vs previous week."""
    db = MagicMock()

    def _enriched_side_effect(days=7, reference_date=None):
        if reference_date and reference_date < "2025-01-13":
            return prev_enriched or []
        return curr_enriched or []

    def _narrative_side_effect(days=7, reference_date=None):
        if reference_date and reference_date < "2025-01-13":
            return prev_history or []
        return curr_history or []

    def _regime_side_effect(days=7, reference_date=None):
        if reference_date and reference_date < "2025-01-13":
            return prev_regime or []
        return curr_regime or []

    db.get_enriched_events_history.side_effect = _enriched_side_effect
    db.get_narrative_history.side_effect = _narrative_side_effect
    db.get_regime_history.side_effect = _regime_side_effect
    return db


class TestWeekOverWeek:
    def test_week_over_week_shock_delta(self) -> None:
        """WoW correctly computes shock type deltas."""
        curr_enriched = [
            {"ticker": "NVDA", "date": "2025-01-15", "shock_type": "Tech shock",
             "sis": 0.8, "ai_centricity": 0.9, "summary": "s", "narrative_category": "AI/LLM/自動化"},
            {"ticker": "MSFT", "date": "2025-01-15", "shock_type": "Tech shock",
             "sis": 0.7, "ai_centricity": 0.8, "summary": "s", "narrative_category": "AI/LLM/自動化"},
        ]
        prev_enriched = [
            {"ticker": "XOM", "date": "2025-01-08", "shock_type": "Regulation shock",
             "sis": 0.5, "ai_centricity": 0.1, "summary": "s", "narrative_category": "規制/政策/地政学"},
        ]
        curr_history = [
            {"date": "2025-01-14", "category": "AI/LLM/自動化", "event_pct": 0.8},
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.8},
        ]
        prev_history = [
            {"date": "2025-01-07", "category": "AI/LLM/自動化", "event_pct": 0.5},
            {"date": "2025-01-08", "category": "AI/LLM/自動化", "event_pct": 0.5},
        ]
        db = _make_mock_db_with_prev(
            curr_enriched=curr_enriched, curr_history=curr_history,
            prev_enriched=prev_enriched, prev_history=prev_history,
        )
        result = compute_weekly_analysis(db, days=7, reference_date="2025-01-15")
        wow = result["week_over_week"]
        assert wow["available"] is True
        assert wow["shock_type_delta"]["テクノロジーショック"]["current"] == 2
        assert wow["shock_type_delta"]["テクノロジーショック"]["previous"] == 0
        assert wow["event_count_delta"]["current"] == 2
        assert wow["event_count_delta"]["previous"] == 1

    def test_week_over_week_unavailable(self) -> None:
        """WoW returns available=False when previous data is empty."""
        curr_enriched = [
            {"ticker": "NVDA", "date": "2025-01-15", "shock_type": "Tech shock",
             "sis": 0.8, "ai_centricity": 0.9, "summary": "s", "narrative_category": "AI/LLM/自動化"},
        ]
        curr_history = [
            {"date": "2025-01-14", "category": "AI/LLM/自動化", "event_pct": 0.8},
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.8},
        ]
        db = _make_mock_db_with_prev(
            curr_enriched=curr_enriched, curr_history=curr_history,
        )
        result = compute_weekly_analysis(db, days=7, reference_date="2025-01-15")
        wow = result["week_over_week"]
        assert wow["available"] is False

    def test_week_over_week_regime_shift(self) -> None:
        """WoW detects regime change between weeks."""
        curr_enriched = [
            {"ticker": "NVDA", "date": "2025-01-15", "shock_type": "Tech shock",
             "sis": 0.8, "ai_centricity": 0.9, "summary": "s", "narrative_category": "AI/LLM/自動化"},
        ]
        curr_history = [
            {"date": "2025-01-14", "category": "AI/LLM/自動化", "event_pct": 0.8},
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.8},
        ]
        prev_history = [
            {"date": "2025-01-07", "category": "AI/LLM/自動化", "event_pct": 0.5},
            {"date": "2025-01-08", "category": "AI/LLM/自動化", "event_pct": 0.5},
        ]
        curr_regime = [
            {"date": "2025-01-14", "regime": "high_vol", "avg_volatility": 0.05,
             "declining_pct": 0.6, "regime_confidence": 0.8},
            {"date": "2025-01-15", "regime": "high_vol", "avg_volatility": 0.05,
             "declining_pct": 0.6, "regime_confidence": 0.8},
        ]
        prev_regime = [
            {"date": "2025-01-07", "regime": "normal", "avg_volatility": 0.02,
             "declining_pct": 0.3, "regime_confidence": 0.9},
            {"date": "2025-01-08", "regime": "normal", "avg_volatility": 0.02,
             "declining_pct": 0.3, "regime_confidence": 0.9},
        ]
        db = _make_mock_db_with_prev(
            curr_enriched=curr_enriched, curr_history=curr_history,
            curr_regime=curr_regime, prev_history=prev_history,
            prev_regime=prev_regime,
        )
        result = compute_weekly_analysis(db, days=7, reference_date="2025-01-15")
        wow = result["week_over_week"]
        assert wow["available"] is True
        assert wow["regime_shift"]["changed"] is True
        assert wow["regime_shift"]["previous_regime"] == "normal"
        assert wow["regime_shift"]["current_regime"] == "high_vol"

    def test_regime_narrative_cross_analysis(self) -> None:
        """Detect co-movement of regime change and narrative shift."""
        curr_enriched = [
            {"ticker": "T1", "date": "2025-01-14", "shock_type": "Tech shock",
             "sis": 0.5, "ai_centricity": 0.5, "summary": "s", "narrative_category": "AI/LLM/自動化"},
        ]
        curr_history = [
            {"date": "2025-01-14", "category": "AI/LLM/自動化", "event_pct": 0.4},
            {"date": "2025-01-14", "category": "金融/金利/流動性", "event_pct": 0.6},
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.7},
            {"date": "2025-01-15", "category": "金融/金利/流動性", "event_pct": 0.3},
        ]
        curr_regime = [
            {"date": "2025-01-14", "regime": "normal", "avg_volatility": 0.02,
             "declining_pct": 0.3, "regime_confidence": 0.9},
            {"date": "2025-01-15", "regime": "high_vol", "avg_volatility": 0.05,
             "declining_pct": 0.6, "regime_confidence": 0.8},
        ]
        db = _make_mock_db_with_prev(
            curr_enriched=curr_enriched, curr_history=curr_history,
            curr_regime=curr_regime,
        )
        result = compute_weekly_analysis(db, days=7, reference_date="2025-01-15")
        cross = result["regime_narrative_cross"]
        assert len(cross) > 0
        # Verify no causal language
        causal_words = ["因果", "影響", "転換"]
        for f in cross:
            for word in causal_words:
                assert word not in f["finding"], f"Causal word '{word}' found in: {f['finding']}"
        # Should detect regime change + narrative shift co-occurrence
        transition_findings = [f for f in cross if "同時期に観測" in f["finding"]]
        assert len(transition_findings) > 0


class TestEarlyDrift:
    def _make_drift_db(
        self,
        enriched: list[dict] | None = None,
        history: list[dict] | None = None,
        baseline_history: list[dict] | None = None,
    ) -> MagicMock:
        """Mock DB with support for 30-day baseline queries."""
        db = MagicMock()

        def _enriched_side_effect(days=7, reference_date=None):
            return enriched or []

        def _narrative_side_effect(days=7, reference_date=None):
            if days >= 30:
                return baseline_history or history or []
            return history or []

        db.get_enriched_events_history.side_effect = _enriched_side_effect
        db.get_narrative_history.side_effect = _narrative_side_effect
        db.get_regime_history.return_value = []
        db.get_articles_by_date_range.return_value = []
        return db

    def test_early_drift_detection(self) -> None:
        """Detect early drift when all 4 conditions are met."""
        enriched = [
            {"ticker": "LMT", "date": "2025-01-15",
             "shock_type": "Regulation shock", "signal_type": "mention_surge",
             "sis": 0.5, "ai_centricity": 0.05,
             "summary": "Defense contractor news",
             "spp": 0.3, "narrative_category": "規制/政策/地政学",
             "diffusion_pattern": "sns_to_tier2"},
        ]
        # Current day: 規制 category at 15% (< 20%)
        history = [
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.85},
            {"date": "2025-01-15", "category": "規制/政策/地政学", "event_pct": 0.15},
        ]
        # 30-day baseline: 規制 usually at 3% → z-score high when at 15%
        baseline_history = [
            {"date": f"2025-01-{d:02d}", "category": "AI/LLM/自動化", "event_pct": 0.95}
            for d in range(1, 15)
        ] + [
            {"date": f"2025-01-{d:02d}", "category": "規制/政策/地政学", "event_pct": 0.03}
            for d in range(1, 15)
        ] + history  # add current day

        db = self._make_drift_db(
            enriched=enriched, history=history,
            baseline_history=baseline_history,
        )
        result = compute_weekly_analysis(db, days=7, reference_date="2025-01-15")
        drift = result["early_drift_candidates"]
        assert len(drift) == 1
        assert drift[0]["ticker"] == "LMT"
        assert drift[0]["narrative_category"] == "規制/政策/地政学"
        assert drift[0]["price_unreacted"] is True
        assert drift[0]["z_score"] >= 1.5

    def test_early_drift_excluded_when_price_reacted(self) -> None:
        """No drift when ticker has price_change signal (price already reacted)."""
        enriched = [
            {"ticker": "LMT", "date": "2025-01-15",
             "shock_type": "Regulation shock", "signal_type": "mention_surge",
             "sis": 0.5, "ai_centricity": 0.05,
             "summary": "Defense news",
             "spp": 0.3, "narrative_category": "規制/政策/地政学",
             "diffusion_pattern": "sns_to_tier2"},
            # Same ticker also has price_change → price already reacted
            {"ticker": "LMT", "date": "2025-01-15",
             "shock_type": "Regulation shock", "signal_type": "price_change",
             "sis": 0.4, "ai_centricity": 0.05,
             "summary": "Price moved",
             "spp": 0.25, "narrative_category": "規制/政策/地政学",
             "diffusion_pattern": "sns_only"},
        ]
        history = [
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.85},
            {"date": "2025-01-15", "category": "規制/政策/地政学", "event_pct": 0.15},
        ]
        baseline_history = [
            {"date": f"2025-01-{d:02d}", "category": "AI/LLM/自動化", "event_pct": 0.95}
            for d in range(1, 15)
        ] + [
            {"date": f"2025-01-{d:02d}", "category": "規制/政策/地政学", "event_pct": 0.03}
            for d in range(1, 15)
        ] + history

        db = self._make_drift_db(
            enriched=enriched, history=history,
            baseline_history=baseline_history,
        )
        result = compute_weekly_analysis(db, days=7, reference_date="2025-01-15")
        drift = result["early_drift_candidates"]
        assert len(drift) == 0

    def test_early_drift_excluded_when_category_dominant(self) -> None:
        """No drift when category ratio >= 20% (already dominant)."""
        enriched = [
            {"ticker": "LMT", "date": "2025-01-15",
             "shock_type": "Regulation shock", "signal_type": "mention_surge",
             "sis": 0.5, "ai_centricity": 0.05,
             "summary": "Defense news",
             "spp": 0.3, "narrative_category": "規制/政策/地政学",
             "diffusion_pattern": "sns_to_tier2"},
        ]
        # 規制 at 25% → already dominant, not "early"
        history = [
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.75},
            {"date": "2025-01-15", "category": "規制/政策/地政学", "event_pct": 0.25},
        ]
        baseline_history = [
            {"date": f"2025-01-{d:02d}", "category": "AI/LLM/自動化", "event_pct": 0.95}
            for d in range(1, 15)
        ] + [
            {"date": f"2025-01-{d:02d}", "category": "規制/政策/地政学", "event_pct": 0.03}
            for d in range(1, 15)
        ] + history

        db = self._make_drift_db(
            enriched=enriched, history=history,
            baseline_history=baseline_history,
        )
        result = compute_weekly_analysis(db, days=7, reference_date="2025-01-15")
        drift = result["early_drift_candidates"]
        assert len(drift) == 0

    def test_early_drift_empty_when_no_data(self) -> None:
        """No drift when there's no data."""
        db = _make_mock_db()
        result = compute_weekly_analysis(db)
        assert result["early_drift_candidates"] == []


class TestCrossHypotheses:
    def test_org_hypotheses_from_persistence(self) -> None:
        """Persistent events (3+ days) generate context-rich hypotheses."""
        enriched = [
            {"ticker": "NVDA", "date": f"2025-01-{d}", "shock_type": "Tech shock",
             "signal_type": "mention_surge",
             "sis": 0.8, "ai_centricity": 0.9, "summary": "GPU",
             "spp": 0.5 + d * 0.05, "narrative_category": "AI/LLM/自動化"}
            for d in [13, 14, 15]
        ]
        history = [
            {"date": f"2025-01-{d}", "category": "AI/LLM/自動化", "event_pct": 0.8}
            for d in [13, 14, 15]
        ]
        db = _make_mock_db_with_prev(
            curr_enriched=enriched, curr_history=history,
        )
        result = compute_weekly_analysis(db, days=7, reference_date="2025-01-15")
        hyps = result["org_impact_hypotheses"]
        # Should have hypothesis about NVDA with context
        nvda_hyps = [h for h in hyps if "NVDA" in h["hypothesis"]]
        assert len(nvda_hyps) > 0
        # Context-rich: should mention signal type or shock type
        hyp = nvda_hyps[0]
        assert "AI/LLM" in hyp["hypothesis"] or "テクノロジー" in hyp["hypothesis"]

    def test_org_hypotheses_from_regime_shift(self) -> None:
        """WoW regime change generates hypothesis without causal language."""
        curr_enriched = [
            {"ticker": "T1", "date": "2025-01-15", "shock_type": "Tech shock",
             "sis": 0.5, "ai_centricity": 0.5, "summary": "s", "narrative_category": "AI/LLM/自動化"},
        ]
        curr_history = [
            {"date": "2025-01-14", "category": "AI/LLM/自動化", "event_pct": 0.8},
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.8},
        ]
        prev_history = [
            {"date": "2025-01-07", "category": "AI/LLM/自動化", "event_pct": 0.5},
            {"date": "2025-01-08", "category": "AI/LLM/自動化", "event_pct": 0.5},
        ]
        curr_regime = [
            {"date": "2025-01-14", "regime": "high_vol", "avg_volatility": 0.05,
             "declining_pct": 0.6, "regime_confidence": 0.8},
            {"date": "2025-01-15", "regime": "high_vol", "avg_volatility": 0.05,
             "declining_pct": 0.6, "regime_confidence": 0.8},
        ]
        prev_regime = [
            {"date": "2025-01-07", "regime": "normal", "avg_volatility": 0.02,
             "declining_pct": 0.3, "regime_confidence": 0.9},
            {"date": "2025-01-08", "regime": "normal", "avg_volatility": 0.02,
             "declining_pct": 0.3, "regime_confidence": 0.9},
        ]
        db = _make_mock_db_with_prev(
            curr_enriched=curr_enriched, curr_history=curr_history,
            curr_regime=curr_regime, prev_history=prev_history,
            prev_regime=prev_regime,
        )
        result = compute_weekly_analysis(db, days=7, reference_date="2025-01-15")
        hyps = result["org_impact_hypotheses"]
        regime_hyps = [h for h in hyps if "レジーム" in h["hypothesis"] and "リスク管理" in h["hypothesis"]]
        assert len(regime_hyps) > 0
        # Verify no causal language
        causal_words = ["因果", "〜のため", "〜により"]
        for h in regime_hyps:
            for word in causal_words:
                assert word not in h["hypothesis"], f"Causal word '{word}' in: {h['hypothesis']}"

    def test_contextual_hypothesis_has_evidence_elements(self) -> None:
        """Context-enriched hypotheses include evidence_elements and data_period."""
        enriched = [
            {"ticker": "MSFT", "date": f"2025-01-{d}", "shock_type": "Narrative shift",
             "signal_type": "mention_surge",
             "sis": 0.8, "ai_centricity": 0.8, "summary": "AI news",
             "spp": 0.4 + d * 0.02, "narrative_category": "AI/LLM/自動化"}
            for d in [13, 14, 15]
        ]
        history = [
            {"date": f"2025-01-{d}", "category": "AI/LLM/自動化", "event_pct": 0.9}
            for d in [13, 14, 15]
        ]
        regime = [
            {"date": "2025-01-15", "regime": "tightening", "avg_volatility": 0.05,
             "declining_pct": 0.7, "regime_confidence": 0.9},
        ]
        db = _make_mock_db_with_prev(
            curr_enriched=enriched, curr_history=history, curr_regime=regime,
        )
        result = compute_weekly_analysis(db, days=7, reference_date="2025-01-15")
        cross_hyps = [h for h in result["org_impact_hypotheses"] if h.get("evidence_elements")]
        assert len(cross_hyps) > 0
        hyp = cross_hyps[0]
        assert isinstance(hyp["evidence_elements"], list)
        assert len(hyp["evidence_elements"]) >= 2
        assert "data_period" in hyp
        assert "confidence_note" in hyp

    def test_contextual_hypothesis_max_three(self) -> None:
        """Cross-hypotheses are limited to 3 max."""
        # Create 5 tickers each appearing 3+ days → would generate many hypotheses
        enriched = []
        for ticker in ["NVDA", "MSFT", "GOOGL", "CRWD", "PLTR"]:
            for d in [13, 14, 15]:
                enriched.append({
                    "ticker": ticker, "date": f"2025-01-{d}",
                    "shock_type": "Tech shock", "signal_type": "mention_surge",
                    "sis": 0.7, "ai_centricity": 0.8, "summary": "event",
                    "spp": 0.5 + d * 0.01, "narrative_category": "AI/LLM/自動化",
                })
        history = [
            {"date": f"2025-01-{d}", "category": "AI/LLM/自動化", "event_pct": 0.9}
            for d in [13, 14, 15]
        ]
        db = _make_mock_db_with_prev(
            curr_enriched=enriched, curr_history=history,
        )
        result = compute_weekly_analysis(db, days=7, reference_date="2025-01-15")
        # org_impact_hypotheses includes both _generate_org_hypotheses and cross,
        # but cross-hypotheses alone should be max 3
        cross_hyps = [h for h in result["org_impact_hypotheses"] if h.get("evidence_elements")]
        assert len(cross_hyps) <= 3

    def test_contextual_hypothesis_no_causal_language(self) -> None:
        """All hypotheses avoid causal assertions."""
        enriched = [
            {"ticker": "NVDA", "date": f"2025-01-{d}", "shock_type": "Tech shock",
             "signal_type": "volume_spike",
             "sis": 0.8, "ai_centricity": 0.9, "summary": "GPU surge",
             "spp": 0.5 + d * 0.05, "narrative_category": "AI/LLM/自動化"}
            for d in [13, 14, 15]
        ]
        history = [
            {"date": f"2025-01-{d}", "category": "AI/LLM/自動化", "event_pct": 0.8}
            for d in [13, 14, 15]
        ]
        db = _make_mock_db_with_prev(
            curr_enriched=enriched, curr_history=history,
        )
        result = compute_weekly_analysis(db, days=7, reference_date="2025-01-15")
        causal_words = ["因果", "〜のため", "〜により", "〜が原因"]
        for h in result["org_impact_hypotheses"]:
            for word in causal_words:
                assert word not in h.get("hypothesis", ""), \
                    f"Causal word '{word}' in: {h['hypothesis']}"
            # confidence_note should exist on cross-hyps
            if h.get("evidence_elements"):
                assert h.get("confidence_note"), "Missing confidence_note"

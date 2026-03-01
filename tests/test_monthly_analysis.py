"""Tests for monthly narrative analysis."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.enrichers.monthly_analysis import (
    _classify_trajectory,
    _compute_hypothesis_scorecard,
    _compute_regime_arc,
    _compute_structural_persistence,
    compute_monthly_analysis,
)


def _make_mock_db(
    enriched_events: list[dict] | None = None,
    history: list[dict] | None = None,
    regime: list[dict] | None = None,
    hypothesis_stats: dict | None = None,
    pending_hypotheses: list[dict] | None = None,
) -> MagicMock:
    """Build a mock DB for monthly analysis tests."""
    db = MagicMock()
    db.get_enriched_events_history.return_value = enriched_events or []
    db.get_narrative_history.return_value = history or []
    db.get_regime_history.return_value = regime or []
    db.get_hypothesis_stats.return_value = hypothesis_stats or {
        "total": 0, "evaluated": 0, "pending": 0,
    }
    db.get_pending_hypotheses.return_value = pending_hypotheses or []
    return db


class TestComputeMonthlyAnalysis:
    def test_result_keys(self) -> None:
        """All expected top-level keys are present."""
        db = _make_mock_db()
        result = compute_monthly_analysis(db, days=30)
        expected_keys = {
            "narrative_lifecycle",
            "lifecycle_stats",
            "hypothesis_evaluations",
            "hypothesis_scorecard",
            "regime_arc",
            "structural_persistence",
            "month_over_month",
            "shock_type_distribution",
            "propagation_structure",
            "forward_posture",
            "narrative_trend",
            "regime_history",
            "period",
            # v7: market response structure
            "reaction_lag",
            "watch_ticker_followup",
            "extinction_chains",
            "drift_evaluation",
            "response_profile",
            # v8: direction-aware market response
            "direction_analysis",
            "regime_cross",
            "exhaustion",
            "exhaustion_evaluation",
        }
        assert set(result.keys()) == expected_keys

    def test_empty_db(self) -> None:
        """Empty DB returns safe defaults without errors."""
        db = _make_mock_db()
        result = compute_monthly_analysis(db, days=30)
        assert result["period"] == "過去30日間"
        assert result["narrative_lifecycle"] == {}
        assert result["hypothesis_evaluations"] == []
        assert result["narrative_trend"] == []
        assert result["regime_arc"]["dominant"] == "unknown"
        assert result["structural_persistence"]["core_tickers"] == []
        assert result["month_over_month"]["available"] is False

    def test_narrative_lifecycle_with_trajectory(self) -> None:
        """Lifecycle data includes trajectory classification."""
        history = []
        for d in range(1, 31):
            date = f"2026-01-{d:02d}"
            history.append({"date": date, "category": "AI/LLM/自動化", "event_pct": 0.7})
            history.append({"date": date, "category": "その他", "event_pct": 0.3})

        db = _make_mock_db(history=history)
        result = compute_monthly_analysis(db, days=30, reference_date="2026-01-30")
        lifecycle = result["narrative_lifecycle"]
        # AI category should have a trajectory assigned
        if "AI/LLM/自動化" in lifecycle:
            assert "trajectory" in lifecycle["AI/LLM/自動化"]
            assert lifecycle["AI/LLM/自動化"]["trajectory"] in [
                "安定支配", "上昇", "下降", "急騰消滅", "新興", "不安定", "不在",
            ]


class TestClassifyTrajectory:
    def test_absent(self) -> None:
        """Very low presence → absent."""
        series = [0.0] * 30
        assert _classify_trajectory(series, 30) == "不在"

    def test_absent_with_occasional_blip(self) -> None:
        """<10% persistence → absent."""
        series = [0.0] * 28 + [0.15, 0.12]  # 2/30 = 6.7% < 10%
        assert _classify_trajectory(series, 30) == "不在"

    def test_dominant_stable(self) -> None:
        """High persistence + low variance → stable dominance."""
        series = [0.70] * 30  # 100% persistence, 0 variance
        assert _classify_trajectory(series, 30) == "安定支配"

    def test_dominant_stable_with_small_variance(self) -> None:
        """High persistence + low variance → stable dominance."""
        series = [0.65, 0.70, 0.68, 0.72, 0.66] * 6  # 30 days, low var
        assert _classify_trajectory(series, 30) == "安定支配"

    def test_rising(self) -> None:
        """Second half avg > first half avg + 10pt → rising."""
        first_half = [0.20] * 15
        second_half = [0.45] * 15  # 0.45 - 0.20 = 0.25 > 0.10
        series = first_half + second_half
        assert _classify_trajectory(series, 30) == "上昇"

    def test_falling(self) -> None:
        """First half avg > second half avg + 10pt → falling."""
        first_half = [0.50] * 15
        second_half = [0.25] * 15  # 0.50 - 0.25 = 0.25 > 0.10
        series = first_half + second_half
        assert _classify_trajectory(series, 30) == "下降"

    def test_spike_and_fade(self) -> None:
        """Peak > avg * 2.0 + convergence < 5 days → spike and fade."""
        # Moderate baseline with a spike that fades quickly
        # Baseline ~12% keeps persistence above 10%, spike at 80% fades in 2 days
        series = [0.12] * 12 + [0.80, 0.15, 0.03] + [0.12] * 15
        assert _classify_trajectory(series, 30) == "急騰消滅"

    def test_emerging(self) -> None:
        """First half absent + second half present >=10% → emerging."""
        first_half = [0.02] * 15  # below 10% threshold
        second_half = [0.25] * 15  # well above 10%
        series = first_half + second_half
        assert _classify_trajectory(series, 30) == "新興"

    def test_empty_series(self) -> None:
        """Empty series → absent."""
        assert _classify_trajectory([], 0) == "不在"
        assert _classify_trajectory([], 30) == "不在"

    def test_unstable_fallback(self) -> None:
        """Series that doesn't match any pattern → unstable."""
        # Fluctuating between 0.20 and 0.40 — not stable, not trending
        series = [0.20, 0.40] * 15
        result = _classify_trajectory(series, 30)
        assert result == "不安定"


class TestHypothesisScorecard:
    def test_scorecard_computation(self) -> None:
        """Correctly counts confirmed/expired/inconclusive."""
        evaluations = [
            {"id": 1, "evaluation": "confirmed", "hypothesis": "H1", "date": "2026-01-01", "ticker": "T1"},
            {"id": 2, "evaluation": "confirmed", "hypothesis": "H2", "date": "2026-01-02", "ticker": "T2"},
            {"id": 3, "evaluation": "expired", "hypothesis": "H3", "date": "2026-01-03", "ticker": "T3"},
            {"id": 4, "evaluation": "inconclusive", "hypothesis": "H4", "date": "2026-01-04", "ticker": None},
        ]
        stats = {"total": 10, "evaluated": 4, "pending": 6}
        scorecard = _compute_hypothesis_scorecard(evaluations, stats)
        assert scorecard["total_evaluated"] == 4
        assert scorecard["confirmed"] == 2
        assert scorecard["expired"] == 1
        assert scorecard["inconclusive"] == 1
        assert scorecard["confirmation_rate"] == 0.5
        assert scorecard["pending"] == 6

    def test_scorecard_empty(self) -> None:
        """Empty inputs return empty dict."""
        assert _compute_hypothesis_scorecard([], {}) == {}

    def test_scorecard_no_evaluations_with_stats(self) -> None:
        """No evaluations but stats has pending."""
        stats = {"total": 5, "evaluated": 0, "pending": 5}
        scorecard = _compute_hypothesis_scorecard([], stats)
        assert scorecard["total_evaluated"] == 0
        assert scorecard["confirmation_rate"] == 0.0
        assert scorecard["pending"] == 5


class TestRegimeArc:
    def test_transitions_detected(self) -> None:
        """Detect regime transitions and compute stability."""
        regime = [
            {"date": "2026-01-01", "regime": "normal", "avg_volatility": 0.02, "declining_pct": 0.3, "regime_confidence": 0.9},
            {"date": "2026-01-02", "regime": "normal", "avg_volatility": 0.02, "declining_pct": 0.3, "regime_confidence": 0.9},
            {"date": "2026-01-03", "regime": "high_vol", "avg_volatility": 0.05, "declining_pct": 0.6, "regime_confidence": 0.8},
            {"date": "2026-01-04", "regime": "high_vol", "avg_volatility": 0.06, "declining_pct": 0.7, "regime_confidence": 0.8},
        ]
        arc = _compute_regime_arc(regime)
        assert len(arc["transitions"]) == 1
        assert arc["transitions"][0]["from"] == "normal"
        assert arc["transitions"][0]["to"] == "high_vol"
        assert arc["dominant"] == "normal" or arc["dominant"] == "high_vol"  # 2-2 tie resolved by Counter order
        assert 0.0 < arc["stability_score"] <= 1.0
        assert arc["volatility_trend"] in ("上昇", "下降", "横ばい", "不明")

    def test_single_regime(self) -> None:
        """Single regime → stability=1.0, no transitions."""
        regime = [
            {"date": f"2026-01-{d:02d}", "regime": "normal", "avg_volatility": 0.02, "declining_pct": 0.3, "regime_confidence": 0.9}
            for d in range(1, 11)
        ]
        arc = _compute_regime_arc(regime)
        assert arc["transitions"] == []
        assert arc["dominant"] == "normal"
        assert arc["stability_score"] == 1.0

    def test_empty_regime(self) -> None:
        """Empty history → safe defaults."""
        arc = _compute_regime_arc([])
        assert arc["dominant"] == "unknown"
        assert arc["stability_score"] == 0.0
        assert arc["transitions"] == []


class TestStructuralPersistence:
    def test_partitioning(self) -> None:
        """Core (60%+) vs transient (<20%) partitioning."""
        enriched = []
        # NVDA appears 8/10 days = 80% → core
        for d in range(1, 9):
            enriched.append({
                "ticker": "NVDA", "date": f"2026-01-{d:02d}",
                "shock_type": "Tech shock", "spp": 0.7,
            })
        # MSFT appears 1/10 days = 10% → transient
        enriched.append({
            "ticker": "MSFT", "date": "2026-01-01",
            "shock_type": "Tech shock", "spp": 0.3,
        })
        # GOOG appears 5/10 days = 50% → neither core nor transient
        for d in range(1, 6):
            enriched.append({
                "ticker": "GOOG", "date": f"2026-01-{d:02d}",
                "shock_type": "Tech shock", "spp": 0.5,
            })
        # XOM appears 1/10 days = 10% → transient
        enriched.append({
            "ticker": "XOM", "date": "2026-01-10",
            "shock_type": "Business model shock", "spp": 0.2,
        })

        result = _compute_structural_persistence(enriched)
        core_tickers = [t["ticker"] for t in result["core_tickers"]]
        transient_tickers = [t["ticker"] for t in result["transient_tickers"]]

        assert "NVDA" in core_tickers
        assert "MSFT" in transient_tickers
        assert "XOM" in transient_tickers
        assert "GOOG" not in core_tickers
        assert "GOOG" not in transient_tickers
        assert result["turnover_rate"] > 0

    def test_empty_history(self) -> None:
        """Empty enriched history → safe defaults."""
        result = _compute_structural_persistence([])
        assert result["core_tickers"] == []
        assert result["transient_tickers"] == []
        assert result["turnover_rate"] == 0.0


class TestMonthOverMonth:
    def _make_mock_db_with_prev(
        self,
        curr_enriched: list[dict] | None = None,
        curr_history: list[dict] | None = None,
        curr_regime: list[dict] | None = None,
        prev_enriched: list[dict] | None = None,
        prev_history: list[dict] | None = None,
        prev_regime: list[dict] | None = None,
    ) -> MagicMock:
        """Mock DB for MoM comparison.

        Previous period ref_date = 2026-02-15 - 30d = 2026-01-16,
        so we use < "2026-02-01" to distinguish.
        """
        db = MagicMock()

        def _enriched_side_effect(days=30, reference_date=None):
            if reference_date and reference_date < "2026-02-01":
                return prev_enriched or []
            return curr_enriched or []

        def _narrative_side_effect(days=30, reference_date=None):
            if reference_date and reference_date < "2026-02-01":
                return prev_history or []
            return curr_history or []

        def _regime_side_effect(days=30, reference_date=None):
            if reference_date and reference_date < "2026-02-01":
                return prev_regime or []
            return curr_regime or []

        db.get_enriched_events_history.side_effect = _enriched_side_effect
        db.get_narrative_history.side_effect = _narrative_side_effect
        db.get_regime_history.side_effect = _regime_side_effect
        db.get_hypothesis_stats.return_value = {"total": 0, "evaluated": 0, "pending": 0}
        db.get_pending_hypotheses.return_value = []
        return db

    def test_month_over_month_available(self) -> None:
        """MoM available when previous month has data."""
        curr_enriched = [
            {"ticker": "NVDA", "date": "2026-02-15", "shock_type": "Tech shock",
             "sis": 0.8, "narrative_category": "AI/LLM/自動化"},
        ]
        prev_enriched = [
            {"ticker": "XOM", "date": "2026-01-10", "shock_type": "Regulation shock",
             "sis": 0.5, "narrative_category": "規制/政策/地政学"},
        ]
        curr_history = [
            {"date": "2026-02-14", "category": "AI/LLM/自動化", "event_pct": 0.8},
            {"date": "2026-02-15", "category": "AI/LLM/自動化", "event_pct": 0.8},
        ]
        prev_history = [
            {"date": "2026-01-01", "category": "AI/LLM/自動化", "event_pct": 0.5},
            {"date": "2026-01-02", "category": "AI/LLM/自動化", "event_pct": 0.5},
        ]

        db = self._make_mock_db_with_prev(
            curr_enriched=curr_enriched, curr_history=curr_history,
            prev_enriched=prev_enriched, prev_history=prev_history,
        )

        result = compute_monthly_analysis(db, days=30, reference_date="2026-02-15")
        mom = result["month_over_month"]
        assert mom["available"] is True
        assert "narrative_delta" in mom
        assert "ticker_turnover" in mom
        # NVDA is new, XOM is gone
        assert "NVDA" in mom["ticker_turnover"]["new"]
        assert "XOM" in mom["ticker_turnover"]["gone"]

    def test_month_over_month_unavailable(self) -> None:
        """MoM unavailable when previous month data is insufficient."""
        curr_history = [
            {"date": "2026-02-14", "category": "AI/LLM/自動化", "event_pct": 0.8},
            {"date": "2026-02-15", "category": "AI/LLM/自動化", "event_pct": 0.8},
        ]
        db = self._make_mock_db_with_prev(curr_history=curr_history)
        result = compute_monthly_analysis(db, days=30, reference_date="2026-02-15")
        assert result["month_over_month"]["available"] is False


class TestReportRendering:
    def test_report_renders(self) -> None:
        """Monthly template renders without error."""
        from app.reporter.daily_report import generate_monthly_report

        analysis = {
            "narrative_lifecycle": {
                "AI/LLM/自動化": {
                    "active_days": 25,
                    "peak_pct": 0.8,
                    "peak_date": "2026-01-15",
                    "convergence_days": 3,
                    "avg_pct": 0.5,
                    "persistence_ratio": 0.83,
                    "trajectory": "安定支配",
                },
            },
            "lifecycle_stats": {
                "period_days": 30,
                "avg_lifespan_days": 20.0,
                "avg_convergence_days": 5.0,
                "persistence_distribution": {"常時（80%+）": 1},
            },
            "hypothesis_evaluations": [],
            "hypothesis_scorecard": {},
            "regime_arc": {
                "transitions": [],
                "dominant": "normal",
                "stability_score": 1.0,
                "volatility_trend": "横ばい",
                "regime_composition": {"normal": {"days": 30, "pct": 1.0}},
            },
            "structural_persistence": {
                "core_tickers": [
                    {"ticker": "NVDA", "days_appeared": 25, "total_days": 30,
                     "appearance_ratio": 0.833, "spp_trend": "上昇", "latest_spp": 0.75},
                ],
                "transient_tickers": [
                    {"ticker": "XOM", "days_appeared": 2, "total_days": 30,
                     "appearance_ratio": 0.067, "spp_trend": "横ばい", "latest_spp": 0.2},
                ],
                "turnover_rate": 0.5,
            },
            "month_over_month": {"available": False},
            "shock_type_distribution": {"テクノロジーショック": 15},
            "propagation_structure": {"sns_to_tier2": 5, "no_coverage": 10},
            "forward_posture": {
                "attention_reallocation": [
                    {"category": "AI/LLM/自動化", "action": "注目度を引き上げ", "reason": "上昇トレンド"},
                ],
                "watch_tickers": [
                    {"ticker": "NVDA", "reason": "コア銘柄"},
                ],
                "regime_outlook": "平時レジームが安定。",
            },
            "narrative_trend": [
                {"date": "2026-01-15", "categories": {"AI/LLM/自動化": 0.8, "その他": 0.2}},
            ],
            "regime_history": [
                {"date": "2026-01-15", "regime": "normal", "avg_volatility": 0.02,
                 "declining_pct": 0.3, "regime_confidence": 0.9},
            ],
            "period": "過去30日間",
        }

        report = generate_monthly_report(analysis, date="2026-01-30")
        assert "月次ナラティブ分析レポート" in report
        assert "2026-01-30" in report
        assert "ナラティブ・ライフサイクル" in report
        assert "AI/LLM/自動化" in report
        assert "安定支配" in report
        assert "来月の注目ポイント" in report
        assert "前月データ不足" in report  # MoM unavailable fallback
        assert "NVDA" in report

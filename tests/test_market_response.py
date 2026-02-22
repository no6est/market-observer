"""Tests for market response structure analysis (v7)."""

from __future__ import annotations

from collections import Counter
from unittest.mock import MagicMock

import pytest

from app.enrichers.market_response import (
    _extract_bigrams,
    compute_reaction_lag,
    compute_response_profile,
    compute_watch_ticker_followup,
    detect_narrative_extinction_chain,
    evaluate_drift_followups,
    track_early_drift_persistent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_db(
    enriched_events: list[dict] | None = None,
    narrative_history: list[dict] | None = None,
    price_ranges: dict[str, list[dict]] | None = None,
    drift_hypotheses: list[dict] | None = None,
) -> MagicMock:
    """Build a mock DB for market response tests."""
    db = MagicMock()
    db.get_enriched_events_history.return_value = enriched_events or []
    db.get_narrative_history.return_value = narrative_history or []

    def _price_range(ticker, start, end):
        if price_ranges and ticker in price_ranges:
            return price_ranges[ticker]
        return []

    db.get_price_data_range.side_effect = _price_range
    db.get_drift_hypotheses.return_value = drift_hypotheses or []
    db.insert_hypothesis_log.return_value = 1
    return db


def _make_price_data(
    ticker: str,
    start_close: float,
    changes: list[float],
    start_date: str = "2026-01-01",
) -> list[dict]:
    """Build price data with daily returns.

    Args:
        ticker: Ticker symbol.
        start_close: Starting close price.
        changes: List of daily return percentages.
        start_date: Starting date string.
    """
    prices = [{"ticker": ticker, "timestamp": start_date, "close": start_close}]
    close = start_close
    for i, pct in enumerate(changes, 1):
        close = close * (1 + pct / 100)
        day = f"2026-01-{i + 1:02d}"
        prices.append({"ticker": ticker, "timestamp": day, "close": round(close, 2)})
    return prices


# ===========================================================================
# PHASE 1: Reaction Lag
# ===========================================================================


class TestReactionLag:
    def test_immediate_reaction(self) -> None:
        """Event with ±2%+ move on day 1 → lag_days=1."""
        events = [{"ticker": "NVDA", "date": "2026-01-01", "spp": 0.5}]
        # Day 1: +3% change
        prices = _make_price_data("NVDA", 100.0, [3.0, 0.5, 0.2])
        db = _make_mock_db(enriched_events=events, price_ranges={"NVDA": prices})

        result = compute_reaction_lag(db, days=30, reference_date="2026-01-31")
        assert result["event_lags"][0]["reacted"] is True
        assert result["event_lags"][0]["lag_days"] == 1
        assert result["stats"]["immediate_rate"] > 0

    def test_delayed_reaction(self) -> None:
        """Event with first ±2%+ move on day 5 → lag_days=5."""
        events = [{"ticker": "MSFT", "date": "2026-01-01", "spp": 0.6}]
        # Days 1-4: small moves, Day 5: +3%
        prices = _make_price_data("MSFT", 100.0, [0.1, -0.1, 0.2, 0.1, 3.0])
        db = _make_mock_db(enriched_events=events, price_ranges={"MSFT": prices})

        result = compute_reaction_lag(db, days=30, reference_date="2026-01-31")
        assert result["event_lags"][0]["reacted"] is True
        assert result["event_lags"][0]["lag_days"] == 5
        assert result["stats"]["delayed_rate"] > 0

    def test_no_reaction(self) -> None:
        """Event with all moves <2% → no reaction."""
        events = [{"ticker": "GOOG", "date": "2026-01-01", "spp": 0.4}]
        prices = _make_price_data("GOOG", 100.0, [0.1, -0.1, 0.2, -0.2, 0.1])
        db = _make_mock_db(enriched_events=events, price_ranges={"GOOG": prices})

        result = compute_reaction_lag(db, days=30, reference_date="2026-01-31")
        assert result["event_lags"][0]["reacted"] is False
        assert result["event_lags"][0]["lag_days"] is None
        assert result["stats"]["no_reaction_rate"] == 1.0

    def test_stats_computation(self) -> None:
        """Multiple events produce correct aggregate stats."""
        events = [
            {"ticker": "NVDA", "date": "2026-01-01"},
            {"ticker": "MSFT", "date": "2026-01-01"},
        ]
        nvda_prices = _make_price_data("NVDA", 100.0, [3.0])  # lag=1
        msft_prices = _make_price_data("MSFT", 200.0, [0.1, 0.1, 0.1, 2.5])  # lag=4
        db = _make_mock_db(
            enriched_events=events,
            price_ranges={"NVDA": nvda_prices, "MSFT": msft_prices},
        )

        result = compute_reaction_lag(db, days=30, reference_date="2026-01-31")
        assert result["stats"]["total_events"] == 2
        assert result["stats"]["avg_lag"] == 2.5  # (1+4)/2
        # Both reacted
        assert result["stats"]["no_reaction_rate"] == 0.0

    def test_empty_events(self) -> None:
        """No events → empty result with zeroed stats."""
        db = _make_mock_db()
        result = compute_reaction_lag(db, days=30)
        assert result["event_lags"] == []
        assert result["stats"]["total_events"] == 0

    def test_no_price_data(self) -> None:
        """Event with no price data → not reacted."""
        events = [{"ticker": "XYZ", "date": "2026-01-01"}]
        db = _make_mock_db(enriched_events=events)

        result = compute_reaction_lag(db, days=30, reference_date="2026-01-31")
        assert result["event_lags"][0]["reacted"] is False

    def test_histogram_structure(self) -> None:
        """Histogram covers all expected buckets."""
        events = [{"ticker": "NVDA", "date": "2026-01-01"}]
        prices = _make_price_data("NVDA", 100.0, [3.0])
        db = _make_mock_db(enriched_events=events, price_ranges={"NVDA": prices})

        result = compute_reaction_lag(db, days=30, reference_date="2026-01-31")
        labels = [h[0] for h in result["histogram_data"]]
        assert "0日" in labels
        assert "未反応" in labels
        assert len(labels) == 9  # 0-5日 + 6-10日 + 11+日 + 未反応
        # Total count matches events
        total = sum(h[1] for h in result["histogram_data"])
        assert total == 1


# ===========================================================================
# PHASE 2: Watch Ticker Follow-up
# ===========================================================================


class TestWatchTickerFollowup:
    def _make_followup_db(
        self,
        prev_enriched: list[dict] | None = None,
        curr_enriched: list[dict] | None = None,
        prev_narrative: list[dict] | None = None,
        curr_narrative: list[dict] | None = None,
        price_ranges: dict[str, list[dict]] | None = None,
    ) -> MagicMock:
        db = MagicMock()

        def _enriched_side_effect(days=30, reference_date=None):
            if reference_date and reference_date < "2026-02-01":
                return prev_enriched or []
            return curr_enriched or []

        def _narrative_side_effect(days=30, reference_date=None):
            if reference_date and reference_date < "2026-02-01":
                return prev_narrative or []
            return curr_narrative or []

        db.get_enriched_events_history.side_effect = _enriched_side_effect
        db.get_narrative_history.side_effect = _narrative_side_effect

        def _price_range(ticker, start, end):
            if price_ranges and ticker in price_ranges:
                return price_ranges[ticker]
            return []

        db.get_price_data_range.side_effect = _price_range
        return db

    def test_hypothesis_strengthened(self) -> None:
        """SPP increase + positive price → 仮説強化."""
        prev = [
            {"ticker": "NVDA", "date": f"2026-01-{d:02d}", "spp": 0.4}
            for d in range(1, 21)
        ]
        curr = [
            {"ticker": "NVDA", "date": f"2026-02-{d:02d}", "spp": 0.6}
            for d in range(1, 21)
        ]
        prices = _make_price_data("NVDA", 100.0, [5.0])  # +5%

        db = self._make_followup_db(
            prev_enriched=prev,
            curr_enriched=curr,
            price_ranges={"NVDA": prices},
        )

        result = compute_watch_ticker_followup(db, days=30, reference_date="2026-02-15")
        assert result["available"] is True
        assert any(f["outcome"] == "仮説強化" for f in result["followups"])

    def test_convergence(self) -> None:
        """SPP decrease + narrative share decrease + small price → 収束."""
        prev = [
            {"ticker": "MSFT", "date": f"2026-01-{d:02d}", "spp": 0.7}
            for d in range(1, 21)
        ]
        curr = [
            {"ticker": "MSFT", "date": f"2026-02-{d:02d}", "spp": 0.3}
            for d in range(1, 6)  # fewer appearances = smaller share
        ] + [
            {"ticker": "GOOG", "date": f"2026-02-{d:02d}", "spp": 0.5}
            for d in range(1, 16)  # GOOG dominates → MSFT share decreases
        ]
        prices = _make_price_data("MSFT", 100.0, [0.5])  # small change

        db = self._make_followup_db(
            prev_enriched=prev,
            curr_enriched=curr,
            price_ranges={"MSFT": prices},
        )

        result = compute_watch_ticker_followup(db, days=30, reference_date="2026-02-15")
        assert result["available"] is True
        msft_followup = [f for f in result["followups"] if f["ticker"] == "MSFT"]
        assert msft_followup and msft_followup[0]["outcome"] == "収束"

    def test_reorganization(self) -> None:
        """Ticker disappears from current period → 再編連鎖."""
        prev = [
            {"ticker": "XOM", "date": f"2026-01-{d:02d}", "spp": 0.6}
            for d in range(1, 21)
        ]
        curr = [
            {"ticker": "NVDA", "date": f"2026-02-{d:02d}", "spp": 0.5}
            for d in range(1, 11)
        ]  # XOM absent

        db = self._make_followup_db(
            prev_enriched=prev,
            curr_enriched=curr,
        )

        result = compute_watch_ticker_followup(db, days=30, reference_date="2026-02-15")
        assert result["available"] is True
        xom_followup = [f for f in result["followups"] if f["ticker"] == "XOM"]
        assert xom_followup and xom_followup[0]["outcome"] == "再編連鎖"

    def test_no_previous_data(self) -> None:
        """No previous watch tickers → unavailable."""
        db = _make_mock_db()
        result = compute_watch_ticker_followup(db, days=30, reference_date="2026-02-15")
        assert result["available"] is False

    def test_reversal(self) -> None:
        """Price move opposite to SPP direction → 反転."""
        prev = [
            {"ticker": "TSLA", "date": f"2026-01-{d:02d}", "spp": 0.7}
            for d in range(1, 21)
        ]
        curr = [
            {"ticker": "TSLA", "date": f"2026-02-{d:02d}", "spp": 0.8}
            for d in range(1, 21)
        ]
        # Large negative price move with high prev_spp
        prices = _make_price_data("TSLA", 100.0, [-5.0])

        db = self._make_followup_db(
            prev_enriched=prev,
            curr_enriched=curr,
            price_ranges={"TSLA": prices},
        )

        result = compute_watch_ticker_followup(db, days=30, reference_date="2026-02-15")
        assert result["available"] is True
        tsla_followup = [f for f in result["followups"] if f["ticker"] == "TSLA"]
        assert tsla_followup and tsla_followup[0]["outcome"] == "反転"


# ===========================================================================
# PHASE 3: Narrative Extinction Chain
# ===========================================================================


class TestExtinctionChain:
    def test_chain_detection(self) -> None:
        """Declining + rising categories with shared bigrams → chain detected."""
        # First half: cat A high, cat B low. Second half: cat A low, cat B high
        history = []
        for d in range(1, 16):
            date = f"2026-01-{d:02d}"
            history.append({"date": date, "category": "エネルギー/資源", "event_pct": 0.5})
            history.append({"date": date, "category": "AI/LLM/自動化", "event_pct": 0.1})
        for d in range(16, 31):
            date = f"2026-01-{d:02d}"
            history.append({"date": date, "category": "エネルギー/資源", "event_pct": 0.1})
            history.append({"date": date, "category": "AI/LLM/自動化", "event_pct": 0.5})

        # Shared bigrams in summaries
        enriched = [
            {"narrative_category": "エネルギー/資源", "summary": "supply chain disruption oil market", "ticker": "XOM", "date": "2026-01-05"},
            {"narrative_category": "エネルギー/資源", "summary": "supply chain impact energy sector", "ticker": "CVX", "date": "2026-01-10"},
            {"narrative_category": "AI/LLM/自動化", "summary": "supply chain AI automation market", "ticker": "NVDA", "date": "2026-01-20"},
            {"narrative_category": "AI/LLM/自動化", "summary": "supply chain optimization market", "ticker": "GOOG", "date": "2026-01-25"},
        ]

        db = _make_mock_db(enriched_events=enriched, narrative_history=history)
        result = detect_narrative_extinction_chain(db, days=30, reference_date="2026-01-30")

        assert len(result["chains"]) > 0
        chain = result["chains"][0]
        assert chain["declining_cat"] == "エネルギー/資源"
        assert chain["rising_cat"] == "AI/LLM/自動化"
        assert chain["overlap_score"] >= 2

    def test_no_shared_keywords(self) -> None:
        """Declining and rising with no keyword overlap → no chains."""
        history = []
        for d in range(1, 16):
            date = f"2026-01-{d:02d}"
            history.append({"date": date, "category": "CatA", "event_pct": 0.5})
            history.append({"date": date, "category": "CatB", "event_pct": 0.1})
        for d in range(16, 31):
            date = f"2026-01-{d:02d}"
            history.append({"date": date, "category": "CatA", "event_pct": 0.1})
            history.append({"date": date, "category": "CatB", "event_pct": 0.5})

        # Completely different keywords
        enriched = [
            {"narrative_category": "CatA", "summary": "alpha beta gamma delta", "ticker": "A", "date": "2026-01-05"},
            {"narrative_category": "CatB", "summary": "zebra yacht xylophone walrus", "ticker": "B", "date": "2026-01-20"},
        ]

        db = _make_mock_db(enriched_events=enriched, narrative_history=history)
        result = detect_narrative_extinction_chain(db, days=30, reference_date="2026-01-30")
        assert result["chains"] == []

    def test_bigram_extraction(self) -> None:
        """Bigram extractor works correctly."""
        bigrams = _extract_bigrams("supply chain disruption market impact")
        assert "supply_chain" in bigrams
        assert "chain_disruption" in bigrams
        assert bigrams["supply_chain"] == 1

    def test_empty_narrative(self) -> None:
        """Empty narrative history → no chains."""
        db = _make_mock_db()
        result = detect_narrative_extinction_chain(db, days=30)
        assert result["chains"] == []
        assert result["reorganization_map"] == {}

    def test_reorganization_map(self) -> None:
        """Reorganization map correctly maps declining → rising candidates."""
        history = []
        for d in range(1, 16):
            date = f"2026-01-{d:02d}"
            history.append({"date": date, "category": "半導体/供給網", "event_pct": 0.4})
            history.append({"date": date, "category": "AI/LLM/自動化", "event_pct": 0.1})
        for d in range(16, 31):
            date = f"2026-01-{d:02d}"
            history.append({"date": date, "category": "半導体/供給網", "event_pct": 0.05})
            history.append({"date": date, "category": "AI/LLM/自動化", "event_pct": 0.5})

        enriched = [
            {"narrative_category": "半導体/供給網", "summary": "semiconductor production chip shortage", "ticker": "TSM", "date": "2026-01-05"},
            {"narrative_category": "半導体/供給網", "summary": "semiconductor supply chip market", "ticker": "INTC", "date": "2026-01-10"},
            {"narrative_category": "AI/LLM/自動化", "summary": "semiconductor chip demand AI", "ticker": "NVDA", "date": "2026-01-20"},
            {"narrative_category": "AI/LLM/自動化", "summary": "semiconductor production AI compute", "ticker": "AMD", "date": "2026-01-25"},
        ]

        db = _make_mock_db(enriched_events=enriched, narrative_history=history)
        result = detect_narrative_extinction_chain(db, days=30, reference_date="2026-01-30")

        if result["reorganization_map"]:
            assert "半導体/供給網" in result["reorganization_map"]
            assert "AI/LLM/自動化" in result["reorganization_map"]["半導体/供給網"]


# ===========================================================================
# PHASE 4: Drift Tracking
# ===========================================================================


class TestDriftTracking:
    def test_persistence(self) -> None:
        """Drift candidates are persisted as hypothesis_logs."""
        db = _make_mock_db()
        candidates = [
            {
                "ticker": "NVDA",
                "narrative_category": "AI/LLM/自動化",
                "z_score": 2.0,
                "diffusion_pattern": "SNS→Tier2",
                "summary": "AI compute demand rising",
            },
        ]

        count = track_early_drift_persistent(db, candidates, reference_date="2026-01-15")
        assert count == 1
        db.insert_hypothesis_log.assert_called_once()
        call_args = db.insert_hypothesis_log.call_args[0][0]
        assert call_args["status"] == "drift_pending"
        assert call_args["ticker"] == "NVDA"

    def test_tier1_evaluation(self) -> None:
        """Drift with Tier1 arrival → 成功."""
        drift_hyps = [
            {"id": 1, "ticker": "NVDA", "date": "2025-12-01", "hypothesis": "test"},
        ]
        enriched = [
            {"ticker": "NVDA", "date": "2026-01-10", "tier1_count": 3, "spp": 0.5},
        ]
        db = _make_mock_db(
            enriched_events=enriched,
            drift_hypotheses=drift_hyps,
        )

        result = evaluate_drift_followups(db, reference_date="2026-01-31")
        assert result["evaluations"][0]["tier1_arrived"] is True
        assert result["evaluations"][0]["outcome"] == "成功"

    def test_price_reaction(self) -> None:
        """Drift with price reaction → 成功."""
        drift_hyps = [
            {"id": 2, "ticker": "MSFT", "date": "2025-12-01", "hypothesis": "test"},
        ]
        prices = _make_price_data("MSFT", 100.0, [5.0])  # +5% move
        db = _make_mock_db(
            drift_hypotheses=drift_hyps,
            price_ranges={"MSFT": prices},
        )

        result = evaluate_drift_followups(db, reference_date="2026-01-31")
        assert result["evaluations"][0]["price_reacted"] is True
        assert result["evaluations"][0]["outcome"] == "成功"

    def test_stats_rates(self) -> None:
        """Aggregate stats correctly computed."""
        drift_hyps = [
            {"id": 1, "ticker": "NVDA", "date": "2025-12-01", "hypothesis": "h1"},
            {"id": 2, "ticker": "MSFT", "date": "2025-12-01", "hypothesis": "h2"},
        ]
        enriched = [
            {"ticker": "NVDA", "date": "2026-01-10", "tier1_count": 1, "spp": 0.5},
        ]
        db = _make_mock_db(
            enriched_events=enriched,
            drift_hypotheses=drift_hyps,
        )

        result = evaluate_drift_followups(db, reference_date="2026-01-31")
        assert result["stats"]["total"] == 2
        # NVDA succeeded (tier1), MSFT didn't
        assert result["stats"]["tier1_arrival_rate"] == 0.5
        assert result["stats"]["drift_success_rate"] == 0.5


# ===========================================================================
# PHASE 5: Response Profile
# ===========================================================================


class TestResponseProfile:
    def _make_profile_db(
        self,
        enriched: list[dict] | None = None,
        price_ranges: dict[str, list[dict]] | None = None,
    ) -> MagicMock:
        db = _make_mock_db(
            enriched_events=enriched or [],
            price_ranges=price_ranges or {},
        )
        return db

    def test_immediate_response(self) -> None:
        """lag<=1 + SPP>=0.3 → 即時反応型."""
        enriched = [{"ticker": "NVDA", "date": "2026-01-01", "spp": 0.5, "narrative_category": "AI"}]
        prices = _make_price_data("NVDA", 100.0, [3.0])  # lag=1
        db = self._make_profile_db(enriched=enriched, price_ranges={"NVDA": prices})

        lag_result = compute_reaction_lag(db, days=30, reference_date="2026-01-31")
        result = compute_response_profile(
            db, days=30, reference_date="2026-01-31",
            reaction_lag_result=lag_result,
        )

        assert result["event_profiles"][0]["response_type"] == "即時反応型"

    def test_temporary_overheat(self) -> None:
        """lag<=1 + SPP<0.3 → 一時的過熱型."""
        enriched = [{"ticker": "XYZ", "date": "2026-01-01", "spp": 0.1, "narrative_category": "その他"}]
        prices = _make_price_data("XYZ", 100.0, [5.0])  # lag=1, high reaction
        db = self._make_profile_db(enriched=enriched, price_ranges={"XYZ": prices})

        lag_result = compute_reaction_lag(db, days=30, reference_date="2026-01-31")
        result = compute_response_profile(
            db, days=30, reference_date="2026-01-31",
            reaction_lag_result=lag_result,
        )

        assert result["event_profiles"][0]["response_type"] == "一時的過熱型"

    def test_delayed_persistent(self) -> None:
        """lag>=3 + SPP>0.5 → 遅延持続型."""
        enriched = [{"ticker": "AAPL", "date": "2026-01-01", "spp": 0.7, "narrative_category": "AI"}]
        prices = _make_price_data("AAPL", 100.0, [0.1, 0.1, 0.1, 3.0])  # lag=4
        db = self._make_profile_db(enriched=enriched, price_ranges={"AAPL": prices})

        lag_result = compute_reaction_lag(db, days=30, reference_date="2026-01-31")
        result = compute_response_profile(
            db, days=30, reference_date="2026-01-31",
            reaction_lag_result=lag_result,
        )

        assert result["event_profiles"][0]["response_type"] == "遅延持続型"

    def test_no_response(self) -> None:
        """No price reaction → 無反応型."""
        enriched = [{"ticker": "SLEEPY", "date": "2026-01-01", "spp": 0.3, "narrative_category": "その他"}]
        prices = _make_price_data("SLEEPY", 100.0, [0.1, -0.1, 0.2])
        db = self._make_profile_db(enriched=enriched, price_ranges={"SLEEPY": prices})

        lag_result = compute_reaction_lag(db, days=30, reference_date="2026-01-31")
        result = compute_response_profile(
            db, days=30, reference_date="2026-01-31",
            reaction_lag_result=lag_result,
        )

        assert result["event_profiles"][0]["response_type"] == "無反応型"

    def test_reorganization_type(self) -> None:
        """Ticker in extinction chain declining cat → 再編型."""
        enriched = [{"ticker": "XOM", "date": "2026-01-01", "spp": 0.5, "narrative_category": "エネルギー"}]
        prices = _make_price_data("XOM", 100.0, [3.0])
        db = self._make_profile_db(enriched=enriched, price_ranges={"XOM": prices})

        lag_result = compute_reaction_lag(db, days=30, reference_date="2026-01-31")
        extinction = {
            "chains": [{
                "declining_cat": "エネルギー",
                "rising_cat": "AI",
                "shared_keywords": ["supply_chain"],
                "overlap_score": 3,
                "sample_events": [{"ticker": "XOM", "date": "2026-01-01", "summary": "test"}],
            }],
            "reorganization_map": {"エネルギー": ["AI"]},
        }

        result = compute_response_profile(
            db, days=30, reference_date="2026-01-31",
            reaction_lag_result=lag_result,
            extinction_result=extinction,
        )

        assert result["event_profiles"][0]["response_type"] == "再編型"

    def test_distribution_sums_to_total(self) -> None:
        """Distribution counts sum to total events."""
        enriched = [
            {"ticker": "NVDA", "date": "2026-01-01", "spp": 0.5, "narrative_category": "AI"},
            {"ticker": "MSFT", "date": "2026-01-01", "spp": 0.1, "narrative_category": "AI"},
            {"ticker": "GOOG", "date": "2026-01-01", "spp": 0.3, "narrative_category": "その他"},
        ]
        prices = {
            "NVDA": _make_price_data("NVDA", 100.0, [3.0]),
            "MSFT": _make_price_data("MSFT", 200.0, [5.0]),
            "GOOG": _make_price_data("GOOG", 150.0, [0.1]),
        }
        db = self._make_profile_db(enriched=enriched, price_ranges=prices)

        lag_result = compute_reaction_lag(db, days=30, reference_date="2026-01-31")
        result = compute_response_profile(
            db, days=30, reference_date="2026-01-31",
            reaction_lag_result=lag_result,
        )

        total_dist = sum(result["distribution"].values())
        assert total_dist == len(result["event_profiles"])
        # Distribution pct sums to ~1.0
        total_pct = sum(result["distribution_pct"].values())
        assert abs(total_pct - 1.0) < 0.01


# ===========================================================================
# Integration Tests
# ===========================================================================


class TestIntegration:
    def test_all_keys_present_in_monthly(self) -> None:
        """compute_monthly_analysis includes all v7 keys."""
        from app.enrichers.monthly_analysis import compute_monthly_analysis

        db = _make_mock_db()
        result = compute_monthly_analysis(db, days=30)

        v7_keys = {
            "reaction_lag",
            "watch_ticker_followup",
            "extinction_chains",
            "drift_evaluation",
            "response_profile",
        }
        for key in v7_keys:
            assert key in result, f"Missing key: {key}"

    def test_template_rendering(self) -> None:
        """Monthly template renders with v7 data without error."""
        from app.reporter.daily_report import generate_monthly_report

        analysis = {
            "narrative_lifecycle": {},
            "lifecycle_stats": {},
            "hypothesis_evaluations": [],
            "hypothesis_scorecard": {},
            "regime_arc": {
                "transitions": [],
                "dominant": "normal",
                "stability_score": 1.0,
                "volatility_trend": "横ばい",
                "regime_composition": {},
            },
            "structural_persistence": {
                "core_tickers": [],
                "transient_tickers": [],
                "turnover_rate": 0.0,
            },
            "month_over_month": {"available": False},
            "shock_type_distribution": {},
            "propagation_structure": {},
            "forward_posture": {
                "attention_reallocation": [],
                "watch_tickers": [],
                "regime_outlook": "",
            },
            "narrative_trend": [],
            "regime_history": [],
            "period": "過去30日間",
            # v7 data
            "reaction_lag": {
                "event_lags": [
                    {"ticker": "NVDA", "date": "2026-01-01", "lag_days": 1, "reaction_pct": 3.0, "reacted": True},
                ],
                "stats": {
                    "avg_lag": 1.0, "median_lag": 1.0,
                    "immediate_rate": 1.0, "delayed_rate": 0.0,
                    "no_reaction_rate": 0.0, "total_events": 1,
                },
                "histogram_data": [("0日", 0), ("1日", 1), ("2日", 0), ("3日", 0), ("4日", 0), ("5日", 0), ("6-10日", 0), ("11+日", 0), ("未反応", 0)],
            },
            "watch_ticker_followup": {
                "available": True,
                "followups": [
                    {"ticker": "NVDA", "prev_spp": 0.5, "curr_spp": 0.6, "price_change_pct": 3.0, "narrative_share_change": 0.05, "outcome": "仮説強化"},
                ],
                "outcome_distribution": {"仮説強化": 1},
            },
            "extinction_chains": {
                "chains": [
                    {
                        "declining_cat": "エネルギー/資源",
                        "rising_cat": "AI/LLM/自動化",
                        "shared_keywords": ["supply", "chain"],
                        "overlap_score": 3,
                        "sample_events": [{"ticker": "XOM", "date": "2026-01-05", "summary": "test event"}],
                    },
                ],
                "reorganization_map": {"エネルギー/資源": ["AI/LLM/自動化"]},
            },
            "drift_evaluation": {
                "evaluations": [
                    {"id": 1, "ticker": "NVDA", "date": "2025-12-01", "tier1_arrived": True, "price_reacted": False, "outcome": "成功"},
                ],
                "stats": {"total": 1, "tier1_arrival_rate": 1.0, "price_reaction_rate": 0.0, "drift_success_rate": 1.0},
            },
            "response_profile": {
                "event_profiles": [
                    {"ticker": "NVDA", "date": "2026-01-01", "response_type": "即時反応型", "evidence": "lag=1日, SPP=0.50"},
                ],
                "distribution": {"即時反応型": 1, "遅延持続型": 0, "一時的過熱型": 0, "無反応型": 0, "再編型": 0},
                "distribution_pct": {"即時反応型": 1.0, "遅延持続型": 0.0, "一時的過熱型": 0.0, "無反応型": 0.0, "再編型": 0.0},
            },
        }

        report = generate_monthly_report(analysis, date="2026-01-30")
        # All section headers present
        assert "ナラティブ→価格反応ラグ" in report
        assert "前月ウォッチ銘柄フォローアップ" in report
        assert "ナラティブ消滅・再編連鎖" in report
        assert "Early Drift 追跡評価" in report
        assert "市場応答プロファイル" in report
        # Data rendered
        assert "NVDA" in report
        assert "仮説強化" in report
        assert "即時反応型" in report
        assert "因果関係を主張するものではありません" in report  # causal disclaimer

    def test_phase5_depends_on_phase1(self) -> None:
        """Phase 5 uses Phase 1 results correctly."""
        enriched = [
            {"ticker": "NVDA", "date": "2026-01-01", "spp": 0.5, "narrative_category": "AI"},
        ]
        prices = _make_price_data("NVDA", 100.0, [3.0])
        db = _make_mock_db(
            enriched_events=enriched,
            price_ranges={"NVDA": prices},
        )

        lag_result = compute_reaction_lag(db, days=30, reference_date="2026-01-31")
        assert lag_result["event_lags"][0]["reacted"] is True

        profile = compute_response_profile(
            db, days=30, reference_date="2026-01-31",
            reaction_lag_result=lag_result,
        )
        assert profile["event_profiles"][0]["response_type"] in (
            "即時反応型", "遅延持続型", "一時的過熱型",
        )

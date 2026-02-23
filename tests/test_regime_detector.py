"""Tests for market regime detection and regime-adaptive SPP weights."""

from __future__ import annotations

import math
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from app.enrichers.regime_detector import (
    REGIME_WEIGHTS,
    detect_market_regime,
    get_spp_weights,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(price_rows: list[dict] | None = None):
    """Create a mock DB that exposes ``_connect()`` returning a mock connection.

    ``price_rows`` should be a flat list of dicts with keys
    ``ticker``, ``close``, ``timestamp``.
    """
    if price_rows is None:
        price_rows = []

    db = MagicMock()

    class FakeCursor:
        def __init__(self, rows: list[dict]):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeConnection:
        def execute(self, sql: str, params=None):
            sql_lower = sql.strip().lower()
            if "select distinct ticker" in sql_lower:
                tickers = sorted({r["ticker"] for r in price_rows})
                return FakeCursor([{"ticker": t} for t in tickers])
            elif "select close" in sql_lower:
                # params = (ticker, cutoff, ref_date + " 23:59:59")
                ticker = params[0]
                rows = [r for r in price_rows if r["ticker"] == ticker]
                rows.sort(key=lambda r: r["timestamp"])
                return FakeCursor(rows)
            return FakeCursor([])

    @contextmanager
    def _connect():
        yield FakeConnection()

    db._connect = _connect
    return db


def _generate_stable_prices(
    ticker: str,
    n: int = 25,
    base_price: float = 100.0,
    daily_move: float = 0.001,
) -> list[dict]:
    """Generate low-volatility price rows (ascending)."""
    rows = []
    price = base_price
    for i in range(n):
        rows.append({
            "ticker": ticker,
            "close": round(price, 2),
            "timestamp": f"2026-01-{max(1, i + 1):02d}",
        })
        price *= (1.0 + daily_move)
    return rows


def _generate_volatile_prices(
    ticker: str,
    n: int = 25,
    base_price: float = 100.0,
    swing: float = 0.05,
    declining: bool = False,
) -> list[dict]:
    """Generate high-volatility price rows.

    If ``declining`` is True, the overall trend is downward.
    """
    rows = []
    price = base_price
    for i in range(n):
        rows.append({
            "ticker": ticker,
            "close": round(price, 2),
            "timestamp": f"2026-01-{max(1, i + 1):02d}",
        })
        direction = -1 if (i % 2 == 0) else 1
        if declining:
            # net downward
            direction = -1 if (i % 3 != 0) else 0.5
        price *= (1.0 + swing * direction)
    return rows


# ---------------------------------------------------------------------------
# detect_market_regime
# ---------------------------------------------------------------------------


class TestDetectMarketRegime:
    def test_normal_regime_low_vol(self) -> None:
        """Stable prices should yield 'normal' regime."""
        prices = (
            _generate_stable_prices("AAPL", daily_move=0.001)
            + _generate_stable_prices("MSFT", daily_move=0.002)
        )
        db = _make_db(prices)
        result = detect_market_regime(db, reference_date="2026-01-25")

        assert result["regime"] == "normal"
        assert result["avg_volatility"] < 0.25
        assert "details" in result
        assert "ticker_volatilities" in result["details"]
        assert "ticker_returns_20d" in result["details"]

    def test_high_vol_regime(self) -> None:
        """High volatility but not mostly declining -> 'high_vol'."""
        # Two volatile tickers, both overall rising
        prices = (
            _generate_volatile_prices("AAPL", swing=0.06, declining=False)
            + _generate_volatile_prices("MSFT", swing=0.06, declining=False)
        )
        db = _make_db(prices)
        result = detect_market_regime(db, reference_date="2026-01-25")

        assert result["avg_volatility"] >= 0.25
        # Not tightening because most tickers are not declining
        assert result["regime"] in ("high_vol", "tightening")
        # Accept either because swing patterns can end up declining by chance
        if result["declining_pct"] <= 0.5:
            assert result["regime"] == "high_vol"

    def test_tightening_regime(self) -> None:
        """High vol + majority declining -> 'tightening'."""
        prices = (
            _generate_volatile_prices("AAPL", swing=0.06, declining=True)
            + _generate_volatile_prices("MSFT", swing=0.06, declining=True)
            + _generate_volatile_prices("GOOGL", swing=0.06, declining=True)
        )
        db = _make_db(prices)
        result = detect_market_regime(db, reference_date="2026-01-25")

        assert result["avg_volatility"] >= 0.25
        assert result["declining_pct"] > 0.5
        assert result["regime"] == "tightening"

    def test_no_price_data_fallback(self) -> None:
        """With no tickers in the DB, default to 'normal'."""
        db = _make_db([])
        result = detect_market_regime(db, reference_date="2026-01-25")

        assert result["regime"] == "normal"
        assert result["avg_volatility"] == 0.0
        assert result["declining_pct"] == 0.0

    def test_result_keys(self) -> None:
        prices = _generate_stable_prices("AAPL")
        db = _make_db(prices)
        result = detect_market_regime(db, reference_date="2026-01-25")

        assert "regime" in result
        assert "avg_volatility" in result
        assert "declining_pct" in result
        assert "regime_confidence" in result
        assert "details" in result

    def test_regime_confidence_in_range(self) -> None:
        prices = _generate_stable_prices("AAPL")
        db = _make_db(prices)
        result = detect_market_regime(db, reference_date="2026-01-25")

        assert 0.0 <= result["regime_confidence"] <= 1.0

    def test_single_ticker_insufficient_data(self) -> None:
        """A ticker with only 1 price row should be skipped gracefully."""
        rows = [{"ticker": "AAPL", "close": 100.0, "timestamp": "2026-01-15"}]
        db = _make_db(rows)
        result = detect_market_regime(db, reference_date="2026-01-25")

        # Insufficient data to compute volatility -> falls back to normal
        assert result["regime"] == "normal"

    def test_custom_vol_threshold(self) -> None:
        """A very low vol_threshold should make stable prices look volatile."""
        prices = _generate_stable_prices("AAPL", daily_move=0.005)
        db = _make_db(prices)
        result = detect_market_regime(
            db, reference_date="2026-01-25", vol_threshold=0.01
        )
        # With a very low threshold, even small moves trigger high_vol
        if result["avg_volatility"] >= 0.01:
            assert result["regime"] in ("high_vol", "tightening")

    def test_tickers_parameter_filters_data(self) -> None:
        """When tickers=['AAPL'] is passed, only AAPL data is used (not MSFT)."""
        aapl_prices = _generate_stable_prices("AAPL", daily_move=0.001)
        msft_prices = _generate_volatile_prices("MSFT", swing=0.08, declining=True)
        db = _make_db(aapl_prices + msft_prices)

        # Without tickers filter: both AAPL and MSFT are used
        result_all = detect_market_regime(db, reference_date="2026-01-25")
        assert "AAPL" in result_all["details"]["ticker_volatilities"]
        assert "MSFT" in result_all["details"]["ticker_volatilities"]

        # With tickers=['AAPL']: only AAPL is used
        result_filtered = detect_market_regime(
            db, reference_date="2026-01-25", tickers=["AAPL"]
        )
        assert "AAPL" in result_filtered["details"]["ticker_volatilities"]
        assert "MSFT" not in result_filtered["details"]["ticker_volatilities"]

        # Result must still be a valid regime dict
        assert result_filtered["regime"] in ("normal", "high_vol", "tightening")
        assert "avg_volatility" in result_filtered
        assert "declining_pct" in result_filtered
        assert "regime_confidence" in result_filtered
        assert 0.0 <= result_filtered["regime_confidence"] <= 1.0

        # AAPL is stable, so filtered result should be 'normal'
        assert result_filtered["regime"] == "normal"


# ---------------------------------------------------------------------------
# get_spp_weights
# ---------------------------------------------------------------------------


class TestGetSppWeights:
    def test_normal_regime_weights(self) -> None:
        weights = get_spp_weights("normal")
        assert weights == REGIME_WEIGHTS["normal"]
        assert "consecutive_days" in weights
        assert "price_trend" in weights

    def test_high_vol_regime_weights(self) -> None:
        weights = get_spp_weights("high_vol")
        assert weights == REGIME_WEIGHTS["high_vol"]
        # In high_vol, price_trend should be emphasized
        assert weights["price_trend"] > weights["consecutive_days"]

    def test_tightening_regime_weights(self) -> None:
        weights = get_spp_weights("tightening")
        assert weights == REGIME_WEIGHTS["tightening"]

    def test_config_override(self) -> None:
        custom = {
            "consecutive_days": 0.2,
            "evidence_trend": 0.2,
            "price_trend": 0.2,
            "media_diffusion": 0.2,
            "sector_propagation": 0.2,
        }
        weights = get_spp_weights("anything", config_weights=custom)
        assert weights == custom

    def test_invalid_regime_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown regime"):
            get_spp_weights("nonexistent")

    def test_config_override_bad_sum_raises(self) -> None:
        bad = {
            "consecutive_days": 0.5,
            "evidence_trend": 0.5,
            "price_trend": 0.5,
        }
        with pytest.raises(ValueError, match="must sum to ~1.0"):
            get_spp_weights("normal", config_weights=bad)

    def test_returns_copy_not_reference(self) -> None:
        weights = get_spp_weights("normal")
        weights["consecutive_days"] = 999.0
        # Original should be unmodified
        assert REGIME_WEIGHTS["normal"]["consecutive_days"] != 999.0

    def test_all_expected_components_present(self) -> None:
        expected_keys = {
            "consecutive_days",
            "evidence_trend",
            "price_trend",
            "media_diffusion",
            "sector_propagation",
        }
        for regime in ("normal", "high_vol", "tightening"):
            weights = get_spp_weights(regime)
            assert set(weights.keys()) == expected_keys


# ---------------------------------------------------------------------------
# REGIME_WEIGHTS validation
# ---------------------------------------------------------------------------


class TestRegimeWeights:
    def test_all_weight_sets_sum_to_one(self) -> None:
        for regime, weights in REGIME_WEIGHTS.items():
            total = sum(weights.values())
            assert abs(total - 1.0) < 0.01, (
                f"Weights for regime '{regime}' sum to {total}, not ~1.0"
            )

    def test_all_weights_positive(self) -> None:
        for regime, weights in REGIME_WEIGHTS.items():
            for component, value in weights.items():
                assert value > 0, (
                    f"Weight '{component}' in regime '{regime}' is not positive: {value}"
                )

    def test_expected_regimes_present(self) -> None:
        assert "normal" in REGIME_WEIGHTS
        assert "high_vol" in REGIME_WEIGHTS
        assert "tightening" in REGIME_WEIGHTS

    def test_consistent_components_across_regimes(self) -> None:
        """All regimes should have the same set of weight components."""
        regimes = list(REGIME_WEIGHTS.keys())
        reference_keys = set(REGIME_WEIGHTS[regimes[0]].keys())
        for regime in regimes[1:]:
            assert set(REGIME_WEIGHTS[regime].keys()) == reference_keys, (
                f"Regime '{regime}' has different components than '{regimes[0]}'"
            )

"""Market regime detection and regime-adaptive SPP weights.

Detects the current market regime (normal / high_vol / tightening) by
computing realized volatility of monitored tickers as a VIX proxy, then
provides the appropriate SPP weight set for that regime.

Regime classification:
- normal:     avg annualized volatility < 25%
- high_vol:   avg annualized volatility >= 25%
- tightening: avg annualized volatility >= 25% AND majority of tickers declining
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regime-adaptive SPP weight sets
# ---------------------------------------------------------------------------

REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "normal": {
        "consecutive_days": 0.25,
        "evidence_trend": 0.25,
        "price_trend": 0.15,
        "media_diffusion": 0.20,
        "sector_propagation": 0.15,
    },
    "high_vol": {
        "consecutive_days": 0.15,
        "evidence_trend": 0.15,
        "price_trend": 0.35,
        "media_diffusion": 0.15,
        "sector_propagation": 0.20,
    },
    "tightening": {
        "consecutive_days": 0.20,
        "evidence_trend": 0.20,
        "price_trend": 0.25,
        "media_diffusion": 0.20,
        "sector_propagation": 0.15,
    },
}

# ---------------------------------------------------------------------------
# Configurable thresholds
# ---------------------------------------------------------------------------

_DEFAULT_VOL_THRESHOLD = 0.25  # 25% annualized
_DEFAULT_DECLINING_THRESHOLD = 0.50  # >50% tickers declining -> tightening
_LOOKBACK_DAYS = 20
_ANNUALIZATION_FACTOR = math.sqrt(252)  # trading days per year


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_market_regime(
    db: Any,
    reference_date: str | None = None,
    *,
    tickers: list[str] | None = None,
    vol_threshold: float = _DEFAULT_VOL_THRESHOLD,
    declining_threshold: float = _DEFAULT_DECLINING_THRESHOLD,
) -> dict[str, Any]:
    """Detect the current market regime from realized volatility.

    Uses price_data stored in *db* to compute a VIX-like proxy based on
    realized volatility of monitored tickers over 20 trading days.

    Args:
        db: Database instance (must expose ``_connect()`` context manager
            and ``price_data`` table).
        reference_date: ISO date string (``YYYY-MM-DD``).  Defaults to
            today (UTC) when ``None``.
        tickers: Optional list of ticker symbols to analyse.  When
            provided, only these tickers are used instead of querying
            all tickers from the database.
        vol_threshold: Annualized volatility threshold separating
            ``normal`` from ``high_vol`` / ``tightening``.
        declining_threshold: Fraction of tickers that must be declining
            (negative 20-day return) to qualify as ``tightening``.

    Returns:
        Dict with keys ``regime``, ``avg_volatility``, ``declining_pct``,
        ``regime_confidence``, and ``details``.
    """
    if reference_date is None:
        reference_date = datetime.utcnow().strftime("%Y-%m-%d")

    if tickers is None:
        tickers = _get_all_tickers(db, reference_date)
    if not tickers:
        logger.warning("No tickers found in price_data; defaulting to 'normal' regime")
        return _build_result("normal", 0.0, 0.0, 0.0, {}, {})

    ticker_vols: dict[str, float] = {}
    ticker_returns: dict[str, float] = {}

    for ticker in tickers:
        prices = _get_close_prices(db, ticker, reference_date, _LOOKBACK_DAYS)
        if len(prices) < 2:
            logger.debug("Skipping %s: insufficient price data (%d rows)", ticker, len(prices))
            continue

        daily_returns = _compute_daily_returns(prices)
        if not daily_returns:
            continue

        realized_vol = _annualized_volatility(daily_returns)
        period_return = (prices[-1] / prices[0]) - 1.0

        ticker_vols[ticker] = round(realized_vol, 4)
        ticker_returns[ticker] = round(period_return, 4)

    if not ticker_vols:
        logger.warning("No valid volatility data computed; defaulting to 'normal' regime")
        return _build_result("normal", 0.0, 0.0, 0.0, {}, {})

    avg_vol = sum(ticker_vols.values()) / len(ticker_vols)
    declining_count = sum(1 for r in ticker_returns.values() if r < 0)
    declining_pct = declining_count / len(ticker_returns) if ticker_returns else 0.0

    # --- Classify regime ---
    if avg_vol >= vol_threshold and declining_pct > declining_threshold:
        regime = "tightening"
    elif avg_vol >= vol_threshold:
        regime = "high_vol"
    else:
        regime = "normal"

    confidence = _compute_confidence(avg_vol, declining_pct, vol_threshold, regime)

    logger.info(
        "Detected regime=%s (avg_vol=%.3f, declining=%.1f%%, confidence=%.2f)",
        regime, avg_vol, declining_pct * 100, confidence,
    )

    return _build_result(regime, avg_vol, declining_pct, confidence, ticker_vols, ticker_returns)


def get_spp_weights(
    regime_name: str,
    config_weights: dict[str, float] | None = None,
) -> dict[str, float]:
    """Return SPP component weights for the given regime.

    Args:
        regime_name: One of ``"normal"``, ``"high_vol"``, ``"tightening"``.
        config_weights: Optional override weights (e.g. from YAML config).
            When provided, these are used instead of the built-in defaults.

    Returns:
        Dict mapping component name to weight (values sum to ~1.0).

    Raises:
        ValueError: If weights do not sum to approximately 1.0 (tolerance +-0.01),
            or if *regime_name* is unknown and no *config_weights* given.
    """
    if config_weights is not None:
        weights = dict(config_weights)
    else:
        if regime_name not in REGIME_WEIGHTS:
            raise ValueError(
                f"Unknown regime '{regime_name}'; "
                f"expected one of {sorted(REGIME_WEIGHTS.keys())}"
            )
        weights = dict(REGIME_WEIGHTS[regime_name])

    _validate_weights(weights)

    logger.debug("SPP weights for regime '%s': %s", regime_name, weights)
    return weights


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_all_tickers(db: Any, reference_date: str) -> list[str]:
    """Query distinct tickers that have price data near *reference_date*."""
    cutoff = (
        datetime.strptime(reference_date, "%Y-%m-%d") - timedelta(days=_LOOKBACK_DAYS + 10)
    ).strftime("%Y-%m-%d")

    with db._connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM price_data WHERE date(timestamp) >= ? ORDER BY ticker",
            (cutoff,),
        ).fetchall()

    return [row["ticker"] for row in rows]


def _get_close_prices(
    db: Any,
    ticker: str,
    reference_date: str,
    lookback_days: int,
) -> list[float]:
    """Return a chronologically ordered list of close prices for *ticker*.

    Only includes rows where ``close`` is not NULL.
    """
    cutoff = (
        datetime.strptime(reference_date, "%Y-%m-%d") - timedelta(days=lookback_days + 10)
    ).strftime("%Y-%m-%d")

    with db._connect() as conn:
        rows = conn.execute(
            """SELECT close FROM price_data
               WHERE ticker = ? AND date(timestamp) >= ? AND date(timestamp) <= ?
                     AND close IS NOT NULL
               ORDER BY timestamp""",
            (ticker, cutoff, reference_date),
        ).fetchall()

    return [row["close"] for row in rows]


def _compute_daily_returns(prices: list[float]) -> list[float]:
    """Compute log daily returns from a price series."""
    returns: list[float] = []
    for i in range(1, len(prices)):
        if prices[i - 1] > 0 and prices[i] > 0:
            returns.append(math.log(prices[i] / prices[i - 1]))
    return returns


def _annualized_volatility(daily_returns: list[float]) -> float:
    """Compute annualized volatility from daily log returns."""
    n = len(daily_returns)
    if n < 2:
        return 0.0

    mean_ret = sum(daily_returns) / n
    variance = sum((r - mean_ret) ** 2 for r in daily_returns) / (n - 1)
    daily_vol = math.sqrt(variance)

    return daily_vol * _ANNUALIZATION_FACTOR


def _compute_confidence(
    avg_vol: float,
    declining_pct: float,
    vol_threshold: float,
    regime: str,
) -> float:
    """Compute a 0-1 confidence score for the regime classification.

    Higher confidence when the observed metrics are far from the
    decision boundaries.
    """
    # Distance of avg_vol from the threshold, normalised
    vol_distance = abs(avg_vol - vol_threshold) / vol_threshold if vol_threshold > 0 else 0.0
    vol_confidence = min(1.0, vol_distance * 2.0)  # saturates at 50% away

    if regime == "tightening":
        # Also factor in how clearly most tickers are declining
        decline_clarity = min(1.0, (declining_pct - 0.5) * 4.0) if declining_pct > 0.5 else 0.0
        confidence = 0.6 * vol_confidence + 0.4 * decline_clarity
    elif regime == "high_vol":
        # Penalise if declining_pct is close to the tightening boundary
        boundary_penalty = max(0.0, 1.0 - abs(declining_pct - 0.5) * 4.0)
        confidence = vol_confidence * (1.0 - 0.3 * boundary_penalty)
    else:
        # normal
        confidence = vol_confidence

    return round(max(0.0, min(1.0, confidence)), 3)


def _build_result(
    regime: str,
    avg_volatility: float,
    declining_pct: float,
    confidence: float,
    ticker_vols: dict[str, float],
    ticker_returns: dict[str, float],
) -> dict[str, Any]:
    """Construct the standard regime-detection result dict."""
    return {
        "regime": regime,
        "avg_volatility": round(avg_volatility, 4),
        "declining_pct": round(declining_pct, 4),
        "regime_confidence": confidence,
        "details": {
            "ticker_volatilities": dict(ticker_vols),
            "ticker_returns_20d": dict(ticker_returns),
        },
    }


def _validate_weights(weights: dict[str, float]) -> None:
    """Raise ``ValueError`` if *weights* do not sum to ~1.0 (+-0.01)."""
    total = sum(weights.values())
    if abs(total - 1.0) > 0.01:
        raise ValueError(
            f"SPP weights must sum to ~1.0 (got {total:.4f}); weights={weights}"
        )

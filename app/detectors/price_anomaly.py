"""Price change anomaly detection via z-score analysis."""

from __future__ import annotations

import logging
from typing import Any

from app.database import Database
from app.config import DetectionConfig

logger = logging.getLogger(__name__)


def detect_price_anomalies(
    db: Database,
    tickers: list[str],
    config: DetectionConfig,
) -> list[dict[str, Any]]:
    """Detect abnormal daily price returns using z-scores.

    Calculates daily close-to-close returns over the lookback window,
    computes the z-score of the most recent return, and flags tickers
    whose absolute z-score exceeds the configured threshold.

    Args:
        db: Database instance for querying price history and cooldown checks.
        tickers: List of ticker symbols to evaluate.
        config: Detection parameters (lookback_days, z_threshold, cooldown_hours).

    Returns:
        List of anomaly dicts with summary and details fields.
    """
    anomalies: list[dict[str, Any]] = []

    for ticker in tickers:
        if db.has_recent_anomaly(ticker, "price_change", hours=config.cooldown_hours):
            logger.debug("Skipping %s price check (cooldown active)", ticker)
            continue

        history = db.get_price_history(ticker, days=config.lookback_days + 5)
        if len(history) < 3:
            logger.debug("Skipping %s: insufficient price history (%d rows)", ticker, len(history))
            continue

        closes = [row["close"] for row in history if row["close"] is not None]
        if len(closes) < 3:
            continue

        # Daily returns (close-to-close percentage change)
        returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1] != 0
        ]
        if len(returns) < 2:
            continue

        latest_return = returns[-1]
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        std = variance ** 0.5

        if std == 0:
            continue

        z_score = (latest_return - mean) / std

        if abs(z_score) >= config.z_threshold:
            score = min(abs(z_score) / 5.0, 1.0)
            return_pct = round(latest_return * 100, 2)
            sign = "+" if return_pct >= 0 else ""
            anomalies.append({
                "ticker": ticker,
                "signal_type": "price_change",
                "score": round(score, 4),
                "z_score": round(z_score, 4),
                "value": round(latest_return, 6),
                "mean": round(mean, 6),
                "std": round(std, 6),
                "summary": f"前日比{sign}{return_pct}%の価格変動",
                "details": {
                    "latest_close": closes[-1],
                    "prev_close": closes[-2],
                    "return_pct": return_pct,
                    "window_size": len(returns),
                },
            })
            logger.info(
                "Price anomaly: %s z=%.2f return=%.2f%%",
                ticker, z_score, latest_return * 100,
            )

    return anomalies

"""Volume spike anomaly detection via leave-one-out z-score analysis."""

from __future__ import annotations

import logging
from typing import Any

from app.database import Database
from app.config import DetectionConfig

logger = logging.getLogger(__name__)


def detect_volume_anomalies(
    db: Database,
    tickers: list[str],
    config: DetectionConfig,
) -> list[dict[str, Any]]:
    """Detect abnormal trading volume spikes using leave-one-out z-scores.

    Compares the most recent day's volume against the baseline mean and
    standard deviation computed from the remaining lookback window
    (excluding the latest point).

    Args:
        db: Database instance for querying price/volume history and cooldowns.
        tickers: List of ticker symbols to evaluate.
        config: Detection parameters (lookback_days, z_threshold, cooldown_hours).

    Returns:
        List of anomaly dicts with summary and details fields.
    """
    anomalies: list[dict[str, Any]] = []

    for ticker in tickers:
        if db.has_recent_anomaly(ticker, "volume_spike", hours=config.cooldown_hours):
            logger.debug("Skipping %s volume check (cooldown active)", ticker)
            continue

        history = db.get_price_history(ticker, days=config.lookback_days + 5)
        if len(history) < 3:
            logger.debug("Skipping %s: insufficient volume history (%d rows)", ticker, len(history))
            continue

        volumes = [row["volume"] for row in history if row["volume"] is not None and row["volume"] > 0]
        if len(volumes) < 3:
            continue

        # Leave-one-out: baseline excludes the latest data point
        current_volume = volumes[-1]
        baseline = volumes[:-1]

        mean = sum(baseline) / len(baseline)
        variance = sum((v - mean) ** 2 for v in baseline) / len(baseline)
        std = variance ** 0.5

        if std == 0:
            continue

        z_score = (current_volume - mean) / std

        if abs(z_score) >= config.z_threshold:
            score = min(abs(z_score) / 5.0, 1.0)
            volume_ratio = round(current_volume / mean, 2) if mean > 0 else 0
            anomalies.append({
                "ticker": ticker,
                "signal_type": "volume_spike",
                "score": round(score, 4),
                "z_score": round(z_score, 4),
                "value": float(current_volume),
                "mean": round(mean, 2),
                "std": round(std, 2),
                "summary": f"出来高が平均の{volume_ratio}倍",
                "details": {
                    "current_volume": current_volume,
                    "avg_volume": round(mean, 0),
                    "volume_ratio": volume_ratio,
                    "window_size": len(baseline),
                },
            })
            logger.info(
                "Volume anomaly: %s z=%.2f vol=%d avg=%.0f",
                ticker, z_score, current_volume, mean,
            )

    return anomalies

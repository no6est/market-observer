"""Combined anomaly scoring across multiple signal types."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# Weights for each signal type when computing combined score
_SIGNAL_WEIGHTS: dict[str, float] = {
    "price_change": 0.4,
    "volume_spike": 0.3,
    "mention_surge": 0.3,
}

# Bonus multiplier when a ticker has multiple signal types
_MULTI_SIGNAL_BONUS = 0.10


def compute_combined_scores(anomalies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute combined scores for anomalies grouped by ticker.

    For each ticker, calculates a weighted average of its signal scores
    (price=0.4, volume=0.3, mention=0.3). If a ticker has multiple
    distinct signal types, a 10% bonus is applied (capped at 1.0).

    The combined_score is added to each anomaly dict and the list is
    sorted by combined_score descending.

    Args:
        anomalies: List of anomaly dicts from individual detectors.

    Returns:
        The same anomaly dicts with an added combined_score key, sorted
        by combined_score descending.
    """
    if not anomalies:
        return anomalies

    # Group anomalies by ticker
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for anomaly in anomalies:
        by_ticker[anomaly["ticker"]].append(anomaly)

    # Compute combined score per ticker
    ticker_scores: dict[str, float] = {}
    for ticker, ticker_anomalies in by_ticker.items():
        weighted_sum = 0.0
        weight_total = 0.0
        signal_types: set[str] = set()

        for a in ticker_anomalies:
            signal_type = a.get("signal_type", "unknown")
            signal_types.add(signal_type)
            weight = _SIGNAL_WEIGHTS.get(signal_type, 0.2)
            weighted_sum += a.get("score", 0.0) * weight
            weight_total += weight

        combined = weighted_sum / weight_total if weight_total > 0 else 0.0

        # Multi-signal bonus
        if len(signal_types) > 1:
            combined = combined * (1.0 + _MULTI_SIGNAL_BONUS)

        combined = min(round(combined, 4), 1.0)
        ticker_scores[ticker] = combined

        logger.info(
            "Combined score for %s: %.4f (signals: %s)",
            ticker, combined, ", ".join(sorted(signal_types)),
        )

    # Attach combined_score to each anomaly
    for anomaly in anomalies:
        anomaly["combined_score"] = ticker_scores[anomaly["ticker"]]

    # Sort by combined_score descending
    anomalies.sort(key=lambda a: a["combined_score"], reverse=True)

    return anomalies

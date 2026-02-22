"""Structural Persistence Probability (SPP) calculator.

Distinguishes one-time shocks from structural changes by computing
a composite probability score (0.0-1.0) based on five weighted components:

- Consecutive days factor: How persistently this ticker appears in events
- Evidence trend factor: Whether evidence quality is improving over time
- Price trend factor: How strongly market price signals support the event
- Media diffusion factor: Coverage tier and diffusion pattern
- Sector propagation factor: How many propagation targets exist

SPP = consecutive_days_factor * 0.25
    + evidence_trend_factor * 0.20
    + price_trend_factor * 0.20
    + media_diffusion_factor * 0.20
    + sector_propagation_factor * 0.15
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Weights for each SPP component
_WEIGHTS = {
    "consecutive_days": 0.25,
    "evidence_trend": 0.20,
    "price_trend": 0.20,
    "media_diffusion": 0.20,
    "sector_propagation": 0.15,
}

# Media diffusion pattern scores
_DIFFUSION_SCORES: dict[str, float] = {
    "tier1_direct": 1.0,
    "sns_to_tier1": 0.8,
    "sns_to_tier2": 0.4,
    "sns_only": 0.1,
    "no_coverage": 0.0,
}


def _consecutive_days_factor(event: dict[str, Any], db: Any | None) -> float:
    """Compute how many consecutive days this ticker appeared in enriched events.

    Uses db.get_enriched_events_history(days=7) when a database is available.
    Score = min(days_present / 5.0, 1.0).
    Without db, defaults to 0.2 (assuming single-day presence only).

    Args:
        event: Enriched event dict (must contain "ticker").
        db: Optional database instance with get_enriched_events_history().

    Returns:
        Factor value between 0.0 and 1.0.
    """
    if db is None:
        return 0.2

    ticker = event.get("ticker", "")
    try:
        history = db.get_enriched_events_history(days=7)
    except Exception:
        logger.debug("Failed to fetch enriched events history for %s", ticker)
        return 0.2

    if not history:
        return 0.2

    # Count distinct dates where this ticker appeared
    dates_present: set[str] = set()
    for row in history:
        if row.get("ticker") == ticker:
            date = row.get("date", "")
            if date:
                dates_present.add(date)

    days_count = len(dates_present)
    factor = min(days_count / 5.0, 1.0)

    logger.debug(
        "Consecutive days factor for %s: %.2f (%d days in history)",
        ticker, factor, days_count,
    )
    return factor


def _evidence_trend_factor(event: dict[str, Any], db: Any | None) -> float:
    """Compute whether evidence score is improving relative to historical average.

    When db is available, compares the current evidence_score to the average
    of past events for the same ticker. If current >= avg, factor =
    min(current_ev / 0.6, 1.0).

    Without db, falls back to using the current evidence_score directly.

    Args:
        event: Enriched event dict (should contain "evidence_score").
        db: Optional database instance with get_enriched_events_history().

    Returns:
        Factor value between 0.0 and 1.0.
    """
    current_ev = event.get("evidence_score", 0.0) or 0.0

    if db is None:
        return float(current_ev)

    ticker = event.get("ticker", "")
    try:
        history = db.get_enriched_events_history(days=7)
    except Exception:
        logger.debug("Failed to fetch enriched events history for %s", ticker)
        return float(current_ev)

    # Collect past evidence scores for the same ticker
    past_scores = [
        row.get("evidence_score", 0.0) or 0.0
        for row in history
        if row.get("ticker") == ticker
    ]

    if not past_scores:
        return float(current_ev)

    avg_score = sum(past_scores) / len(past_scores)

    if current_ev >= avg_score:
        factor = min(current_ev / 0.6, 1.0)
    else:
        factor = float(current_ev)

    logger.debug(
        "Evidence trend factor for %s: %.3f (current=%.3f, avg=%.3f)",
        ticker, factor, current_ev, avg_score,
    )
    return factor


def _price_trend_factor(event: dict[str, Any]) -> float:
    """Compute how strongly market price signals support this event.

    Scoring rules:
    - signal_type == "price_change": 0.8 base + bonus for high z_score
    - signal_type == "volume_spike": 0.5
    - signal_type == "mention_surge": 0.1

    Args:
        event: Enriched event dict (should contain "signal_type", optionally "z_score").

    Returns:
        Factor value between 0.0 and 1.0.
    """
    signal_type = event.get("signal_type", "")

    if signal_type == "price_change":
        base = 0.8
        z_score = abs(event.get("z_score") or 0)
        bonus = min(0.2, z_score * 0.05) if z_score > 2 else 0.0
        factor = min(1.0, base + bonus)
    elif signal_type == "volume_spike":
        factor = 0.5
    elif signal_type == "mention_surge":
        factor = 0.1
    else:
        factor = 0.0

    logger.debug(
        "Price trend factor for %s: %.2f (signal=%s)",
        event.get("ticker", "?"), factor, signal_type,
    )
    return factor


def _media_diffusion_factor(event: dict[str, Any]) -> float:
    """Compute media diffusion factor from the event's diffusion pattern.

    Maps the diffusion_pattern field to a score:
    - "tier1_direct": 1.0
    - "sns_to_tier1": 0.8
    - "sns_to_tier2": 0.4
    - "sns_only": 0.1
    - "no_coverage": 0.0

    Args:
        event: Enriched event dict (should contain "diffusion_pattern").

    Returns:
        Factor value between 0.0 and 1.0.
    """
    pattern = event.get("diffusion_pattern", "no_coverage")
    factor = _DIFFUSION_SCORES.get(pattern, 0.0)

    logger.debug(
        "Media diffusion factor for %s: %.2f (pattern=%s)",
        event.get("ticker", "?"), factor, pattern,
    )
    return factor


def _sector_propagation_factor(event: dict[str, Any]) -> float:
    """Compute sector propagation factor from propagation targets count.

    factor = min(len(propagation_targets) / 3.0, 1.0)

    Args:
        event: Enriched event dict (should contain "propagation_targets").

    Returns:
        Factor value between 0.0 and 1.0.
    """
    targets = event.get("propagation_targets", [])
    count = len(targets) if targets else 0
    factor = min(count / 3.0, 1.0)

    logger.debug(
        "Sector propagation factor for %s: %.2f (%d targets)",
        event.get("ticker", "?"), factor, count,
    )
    return factor


def compute_spp(event: dict[str, Any], db: Any | None = None, weights: dict[str, float] | None = None) -> float:
    """Compute Structural Persistence Probability for a single event.

    SPP is a composite score (0.0-1.0) that estimates the likelihood
    an observed anomaly represents a structural change rather than a
    one-time shock.

    Args:
        event: Enriched event dict containing at minimum "ticker",
               and ideally "signal_type", "evidence_score",
               "diffusion_pattern", "propagation_targets", and "z_score".
        db: Optional database instance for historical lookups.
            Expected to provide get_enriched_events_history(days=N).

    Returns:
        SPP value as a float rounded to 3 decimal places (0.0-1.0).
    """
    w = weights or _WEIGHTS

    consecutive = _consecutive_days_factor(event, db)
    evidence = _evidence_trend_factor(event, db)
    price = _price_trend_factor(event)
    media = _media_diffusion_factor(event)
    propagation = _sector_propagation_factor(event)

    spp = (
        consecutive * w["consecutive_days"]
        + evidence * w["evidence_trend"]
        + price * w["price_trend"]
        + media * w["media_diffusion"]
        + propagation * w["sector_propagation"]
    )

    spp = round(spp, 3)

    logger.info(
        "SPP for %s: %.3f (consec=%.2f, evid=%.2f, price=%.2f, media=%.2f, prop=%.2f)",
        event.get("ticker", "?"),
        spp,
        consecutive,
        evidence,
        price,
        media,
        propagation,
    )

    return spp


def compute_spp_batch(
    events: list[dict[str, Any]],
    db: Any | None = None,
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Compute SPP for a batch of events, adding the spp field to each.

    Args:
        events: List of enriched event dicts.
        db: Optional database instance for historical lookups.

    Returns:
        The same list of event dicts, each augmented with an "spp" key
        containing the computed SPP value (float, 0.0-1.0, 3 decimals).
    """
    for event in events:
        event["spp"] = compute_spp(event, db=db, weights=weights)

    logger.info("Computed SPP for %d events", len(events))
    return events

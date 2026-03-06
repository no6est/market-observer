"""Narrative Transition: detect category transitions and build outlook."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


def detect_narrative_transitions(
    narrative_momentum: list[dict[str, Any]],
    declining_threshold: float = -0.3,
    rising_threshold: float = 0.3,
) -> list[dict[str, Any]]:
    """Detect transitions from declining to rising narrative categories.

    A transition is every (declining, rising) pair where:
    - declining: momentum < declining_threshold
    - rising: momentum > rising_threshold

    Args:
        narrative_momentum: Output from compute_category_momentum() or
            compute_weighted_category_momentum().
        declining_threshold: Momentum threshold for declining (exclusive).
        rising_threshold: Momentum threshold for rising (exclusive).

    Returns:
        List of transition dicts with from_category, to_category,
        from_momentum, to_momentum.
    """
    if not narrative_momentum:
        return []

    declining = []
    rising = []
    for m in narrative_momentum:
        momentum = m.get("momentum", 0.0)
        cat = m.get("category", "")
        if not cat:
            continue
        if momentum < declining_threshold:
            declining.append(m)
        if momentum > rising_threshold:
            rising.append(m)

    transitions = []
    for d in declining:
        for r in rising:
            transitions.append({
                "from_category": d["category"],
                "to_category": r["category"],
                "from_momentum": d["momentum"],
                "to_momentum": r["momentum"],
            })

    return transitions


def build_transition_outlook(
    today_momentum: list[dict[str, Any]],
    transition_history: list[dict[str, Any]],
    top_n: int = 5,
) -> dict[str, Any]:
    """Build transition outlook based on historical patterns.

    Identifies the dominant category (highest today_count) and
    aggregates historical transitions from that category.

    Args:
        today_momentum: Current momentum data (needs today_count field).
        transition_history: Historical transition records from DB.
        top_n: Maximum number of destination categories to return.

    Returns:
        Dict with dominant_category, historical_transitions, total_observations.
    """
    if not today_momentum:
        return {
            "dominant_category": "",
            "historical_transitions": [],
            "total_observations": 0,
        }

    # Find dominant category by today_count (or today_weight)
    dominant = max(
        today_momentum,
        key=lambda m: m.get("today_count", m.get("today_weight", 0)),
    )
    dominant_cat = dominant.get("category", "")

    if not dominant_cat or not transition_history:
        return {
            "dominant_category": dominant_cat,
            "historical_transitions": [],
            "total_observations": 0,
        }

    # Aggregate transitions from dominant category
    to_counts: dict[str, int] = defaultdict(int)
    for t in transition_history:
        if t.get("from_category") == dominant_cat:
            to_counts[t["to_category"]] += 1

    total = sum(to_counts.values())
    if total == 0:
        return {
            "dominant_category": dominant_cat,
            "historical_transitions": [],
            "total_observations": 0,
        }

    ranked = sorted(to_counts.items(), key=lambda x: x[1], reverse=True)[:top_n]
    historical = [
        {
            "to_category": cat,
            "count": count,
            "pct": round(count / total, 3),
        }
        for cat, count in ranked
    ]

    return {
        "dominant_category": dominant_cat,
        "historical_transitions": historical,
        "total_observations": total,
    }

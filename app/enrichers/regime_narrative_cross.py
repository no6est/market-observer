"""Regime × Narrative Cross Analysis."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


def compute_regime_narrative_cross(
    enriched_events: list[dict[str, Any]],
    regime_info: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Cross-tabulate narrative categories against current regime.

    For each category under the current regime, computes:
    - event_count
    - avg_sis
    - data_sufficient flag (>= 2 events)

    Returns dict with:
        - regime: current regime name
        - categories: list of {category, event_count, avg_sis, data_sufficient}
    """
    if not regime_info:
        return None

    regime = regime_info.get("regime", "unknown")

    category_sis: dict[str, list[float]] = defaultdict(list)
    for e in enriched_events:
        cat = e.get("narrative_category", "")
        sis = e.get("sis", 0.0)
        if cat:
            category_sis[cat].append(sis)

    if not category_sis:
        return None

    categories = []
    for cat in sorted(category_sis, key=lambda c: len(category_sis[c]), reverse=True):
        sis_values = category_sis[cat]
        count = len(sis_values)
        avg_sis = sum(sis_values) / count if count > 0 else 0.0
        categories.append({
            "category": cat,
            "event_count": count,
            "avg_sis": round(avg_sis, 3),
            "data_sufficient": count >= 2,
        })

    return {
        "regime": regime,
        "categories": categories,
    }

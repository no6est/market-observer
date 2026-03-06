"""Narrative Momentum: event count momentum and weak drift detection."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


def compute_category_momentum(
    today_events: list[dict[str, Any]],
    yesterday_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute momentum for each narrative category.

    momentum = (today_count - yesterday_count) / max(yesterday_count, 1)

    Returns list of dicts with: category, today_count, yesterday_count,
    momentum, classification.
    """
    today_counts: dict[str, int] = defaultdict(int)
    yesterday_counts: dict[str, int] = defaultdict(int)

    for e in today_events:
        cat = e.get("narrative_category", "")
        if cat:
            today_counts[cat] += 1
    for e in yesterday_events:
        cat = e.get("narrative_category", "")
        if cat:
            yesterday_counts[cat] += 1

    all_cats = set(today_counts) | set(yesterday_counts)
    results = []
    for cat in sorted(all_cats):
        tc = today_counts.get(cat, 0)
        yc = yesterday_counts.get(cat, 0)

        if yc == 0 and tc > 0:
            classification = "新出"
            momentum = float(tc)
        elif tc == 0 and yc > 0:
            classification = "消滅"
            momentum = -1.0
        else:
            momentum = (tc - yc) / max(yc, 1)
            if momentum > 1.0:
                classification = "急拡大"
            elif momentum >= 0.3:
                classification = "拡大中"
            elif momentum >= -0.3:
                classification = "安定"
            else:
                classification = "縮小"

        results.append({
            "category": cat,
            "today_count": tc,
            "yesterday_count": yc,
            "momentum": round(momentum, 3),
            "classification": classification,
        })

    # Sort by absolute momentum descending
    results.sort(key=lambda x: abs(x["momentum"]), reverse=True)
    return results


def detect_weak_drift(
    enriched_events: list[dict[str, Any]],
    narrative_health: dict[str, Any] | None,
    narrative_index: dict[str, Any] | None,
    z_threshold: float = 1.2,
    category_ratio: float = 0.30,
) -> list[dict[str, Any]]:
    """Detect weak initial drift signals.

    Conditions (all must be met):
    - Category ratio < category_ratio (30%)
    - z-score >= z_threshold (1.2)
    - Mention surge detected (signal_type == 'mention_surge')

    Unlike strong Early Drift, does NOT require:
    - SNS→Tier2 diffusion pattern
    - Price unreacted condition
    """
    if not narrative_health or not narrative_index:
        return []

    cat_scores = narrative_health.get("category_scores", {})
    cat_dist = narrative_index.get("category_distribution", {})

    seen_tickers = set()
    candidates = []

    for e in enriched_events:
        ticker = e.get("ticker", "")
        if ticker in seen_tickers:
            continue

        cat = e.get("narrative_category", "")
        cat_info = cat_dist.get(cat, {})
        cat_pct = cat_info.get("pct", 0.0)
        cat_z = cat_scores.get(cat, {}).get("z_score")

        # Must have mention surge
        has_mention_surge = e.get("signal_type") == "mention_surge"

        if (
            cat_pct < category_ratio
            and cat_z is not None
            and cat_z >= z_threshold
            and has_mention_surge
        ):
            candidates.append({
                "ticker": ticker,
                "narrative_category": cat,
                "category_pct": round(cat_pct, 3),
                "z_score": round(cat_z, 2),
                "summary": e.get("summary", ""),
                "shock_type": e.get("shock_type", ""),
                "signal_type": e.get("signal_type", ""),
                "strength": "weak",
            })
            seen_tickers.add(ticker)

    return candidates

"""Narrative concentration index calculator.

Computes the distribution of narrative categories across events
and tracks bias over time using 7-day moving averages.

Supports narrative_basis filtering to ensure all downstream metrics
(AI ratio, top1 concentration, 7-day delta, overheat) share the
same event population.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Valid basis values
_VALID_BASES = {"all_events", "top_ranked", "social_only"}


def _filter_by_basis(
    events: list[dict[str, Any]],
    basis: str,
) -> list[dict[str, Any]]:
    """Filter events according to narrative_basis.

    - all_events: no filtering (default)
    - top_ranked: only events with SIS >= 0.3
    - social_only: only mention_surge signal_type
    """
    if basis == "all_events":
        return events
    if basis == "top_ranked":
        return [e for e in events if (e.get("sis") or 0) >= 0.3]
    if basis == "social_only":
        return [e for e in events if e.get("signal_type") == "mention_surge"]
    logger.warning("Unknown narrative_basis '%s', using all_events", basis)
    return events


_BASIS_LABEL: dict[str, str] = {
    "all_events": "全イベント",
    "top_ranked": "SIS上位イベント（≥0.3）",
    "social_only": "SNSシグナルのみ",
}


def compute_narrative_concentration(
    events: list[dict[str, Any]],
    db: Any | None = None,
    ai_warning_pct: float = 0.5,
    concentration_warning_pct: float = 0.6,
    adjacent_weight: float = 0.3,
    ai_surge_threshold: float = 0.15,
    narrative_basis: str = "all_events",
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Compute narrative concentration metrics across enriched events.

    Args:
        events: Enriched events with narrative_category field.
        db: Database instance for historical comparison.
        ai_warning_pct: Threshold for AI ratio warning (default 0.5).
        concentration_warning_pct: Threshold for top-1 concentration warning.
        adjacent_weight: Weight for adjacent categories (半導体/供給網) in AI ratio.
        ai_surge_threshold: Threshold for AI surge vs 7-day average warning.
        narrative_basis: Population filter ("all_events", "top_ranked", "social_only").

    Returns:
        Dict with keys:
        - basis: str label of the population filter
        - total_events: int count of all events before filtering
        - basis_events: int count after basis filtering
        - category_distribution: dict[str, dict] with count and pct per category
        - ai_ratio: float (0.0-1.0) of AI-related events
        - top1_concentration: float (0.0-1.0) of most common category
        - historical_avg: dict or None (7-day moving average)
        - warning_flags: list[str] of advisory warnings
    """
    total_all = len(events)
    filtered = _filter_by_basis(events, narrative_basis)
    total = len(filtered)

    empty_result: dict[str, Any] = {
        "basis": _BASIS_LABEL.get(narrative_basis, narrative_basis),
        "total_events": total_all,
        "basis_events": total,
        "category_distribution": {},
        "ai_ratio": 0.0,
        "top1_concentration": 0.0,
        "historical_avg": None,
        "warning_flags": [],
    }

    if total == 0:
        return empty_result

    # Count categories
    category_counts = Counter(
        e.get("narrative_category", "その他") for e in filtered
    )

    # Build distribution
    distribution: dict[str, dict[str, Any]] = {}
    for cat, count in category_counts.most_common():
        distribution[cat] = {
            "count": count,
            "pct": round(count / total, 3),
        }

    # AI ratio: count of AI/LLM/自動化 + partial for 半導体/供給網
    ai_count = category_counts.get("AI/LLM/自動化", 0)
    adjacent_count = category_counts.get("半導体/供給網", 0)
    ai_ratio = round((ai_count + adjacent_count * adjacent_weight) / total, 3)

    # Top-1 concentration
    top1_count = category_counts.most_common(1)[0][1] if category_counts else 0
    top1_concentration = round(top1_count / total, 3)

    # Historical comparison
    historical_avg = None
    if db is not None:
        try:
            history = db.get_narrative_history(days=7, reference_date=reference_date)
            if history:
                historical_avg = _compute_historical_avg(history)
        except Exception:
            logger.debug("Failed to get narrative history")

    # Warning flags
    warning_flags: list[str] = []
    if ai_ratio > ai_warning_pct:
        warning_flags.append(
            f"AI関連ナラティブが全体の{ai_ratio*100:.0f}%を占めています（閾値: {ai_warning_pct*100:.0f}%）"
        )
    if top1_concentration > concentration_warning_pct:
        top1_cat = category_counts.most_common(1)[0][0]
        warning_flags.append(
            f"「{top1_cat}」が全体の{top1_concentration*100:.0f}%を占め、偏りが大きい状態です"
        )

    # Check trend if historical data available
    if historical_avg and "AI/LLM/自動化" in historical_avg:
        hist_ai = historical_avg["AI/LLM/自動化"]
        current_ai_pct = distribution.get("AI/LLM/自動化", {}).get("pct", 0)
        if current_ai_pct > hist_ai + ai_surge_threshold:
            warning_flags.append(
                f"AI比率が7日平均({hist_ai*100:.0f}%)から"
                f"{(current_ai_pct - hist_ai)*100:.0f}ポイント上昇しています"
            )

    # Save snapshot to DB
    if db is not None:
        try:
            today = reference_date or datetime.utcnow().strftime("%Y-%m-%d")
            for cat, info in distribution.items():
                db.insert_narrative_snapshot(
                    date=today,
                    category=cat,
                    event_count=info["count"],
                    event_pct=info["pct"],
                    total_events=total,
                )
        except Exception:
            logger.debug("Failed to save narrative snapshot")

    result = {
        "basis": _BASIS_LABEL.get(narrative_basis, narrative_basis),
        "total_events": total_all,
        "basis_events": total,
        "category_distribution": distribution,
        "ai_ratio": ai_ratio,
        "top1_concentration": top1_concentration,
        "historical_avg": historical_avg,
        "warning_flags": warning_flags,
    }

    logger.info(
        "Narrative concentration: basis=%s, AI=%.1f%%, top1=%.1f%%, warnings=%d",
        narrative_basis, ai_ratio * 100, top1_concentration * 100, len(warning_flags),
    )
    return result


def _compute_historical_avg(
    history: list[dict[str, Any]],
) -> dict[str, float]:
    """Compute average category percentages from historical snapshots."""
    cat_totals: dict[str, list[float]] = {}
    for row in history:
        cat = row["category"]
        pct = row["event_pct"]
        if cat not in cat_totals:
            cat_totals[cat] = []
        cat_totals[cat].append(pct)

    return {
        cat: round(sum(vals) / len(vals), 3)
        for cat, vals in cat_totals.items()
    }

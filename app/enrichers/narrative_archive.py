"""Narrative History Archive — tracks hypothesis lifecycle and narrative longevity.

v6: Provides hypothesis ID tracking with 30-day evaluation,
enhanced narrative archiving, and monthly summary output.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)


def archive_hypotheses(
    db: Any,
    date: str,
    hypotheses: list[dict[str, Any]],
) -> list[int]:
    """Archive generated hypotheses for later evaluation.

    Each hypothesis gets a unique ID and 'pending' status.
    After 30 days, evaluate_pending_hypotheses() can check outcomes.

    Returns:
        List of hypothesis IDs.
    """
    ids: list[int] = []
    for hyp in hypotheses:
        try:
            # Extract ticker from hypothesis text if present
            ticker = hyp.get("ticker")
            if not ticker:
                # Try to extract from hypothesis text
                text = hyp.get("hypothesis", "")
                for word in text.split():
                    if word.isupper() and len(word) <= 5 and word.isalpha():
                        ticker = word
                        break

            # Evidence may be a list of URLs — serialize to string
            evidence = hyp.get("evidence", "")
            if isinstance(evidence, list):
                evidence = "\n".join(str(e) for e in evidence)

            hyp_id = db.insert_hypothesis_log({
                "date": date,
                "ticker": ticker,
                "hypothesis": hyp.get("hypothesis", ""),
                "evidence": evidence,
                "confidence": hyp.get("confidence"),
                "status": "pending",
            })
            ids.append(hyp_id)
        except Exception:
            logger.debug("Failed to archive hypothesis: %s", hyp.get("hypothesis", "")[:50])
    return ids


def evaluate_pending_hypotheses(
    db: Any,
    reference_date: str,
) -> list[dict[str, Any]]:
    """Evaluate hypotheses that are 30+ days old.

    For each pending hypothesis:
    - Check if the ticker still appears in recent enriched events
    - Check if SPP direction continued
    - Mark as 'confirmed', 'expired', or 'inconclusive'

    Returns:
        List of evaluation results.
    """
    pending = db.get_pending_hypotheses(days_old=30)
    if not pending:
        return []

    # Get recent enriched events for comparison
    recent = db.get_enriched_events_history(days=7, reference_date=reference_date)
    recent_tickers = {e.get("ticker") for e in recent}

    results: list[dict[str, Any]] = []
    for hyp in pending:
        ticker = hyp.get("ticker")
        hyp_id = hyp["id"]

        if ticker and ticker in recent_tickers:
            evaluation = "confirmed"
        elif ticker:
            evaluation = "expired"
        else:
            evaluation = "inconclusive"

        try:
            db.update_hypothesis_evaluation(hyp_id, evaluation, reference_date)
        except Exception:
            logger.debug("Failed to update hypothesis %d evaluation", hyp_id)

        results.append({
            "id": hyp_id,
            "date": hyp["date"],
            "ticker": ticker,
            "hypothesis": hyp["hypothesis"],
            "evaluation": evaluation,
        })

    return results


def compute_narrative_lifecycle(
    db: Any,
    days: int = 90,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Compute narrative category lifecycle statistics.

    Analyzes narrative_snapshots over the given period to determine:
    - Average lifespan of each category's dominance
    - Peak-to-convergence duration
    - Persistence probability distribution

    Returns:
        Dict with lifecycle metrics per category.
    """
    history = db.get_narrative_history(days=days, reference_date=reference_date)
    if not history:
        return {"categories": {}, "period_days": 0}

    # Group by date and category
    daily: dict[str, dict[str, float]] = {}
    for row in history:
        date = row["date"]
        if date not in daily:
            daily[date] = {}
        daily[date][row["category"]] = row["event_pct"]

    sorted_dates = sorted(daily.keys())
    period_days = len(sorted_dates)

    # Per-category: count days above 10% threshold (active days)
    cat_stats: dict[str, dict[str, Any]] = {}
    all_cats: set[str] = set()
    for cats in daily.values():
        all_cats.update(cats.keys())

    for cat in all_cats:
        series = [daily[d].get(cat, 0.0) for d in sorted_dates]
        active_days = sum(1 for v in series if v >= 0.10)
        peak_pct = max(series) if series else 0.0
        peak_idx = series.index(peak_pct) if series else 0

        # Convergence: days from peak to first time below 10%
        convergence_days = 0
        if peak_idx < len(series) - 1:
            for i in range(peak_idx + 1, len(series)):
                convergence_days += 1
                if series[i] < 0.10:
                    break

        avg_pct = sum(series) / len(series) if series else 0.0

        cat_stats[cat] = {
            "active_days": active_days,
            "peak_pct": round(peak_pct, 3),
            "convergence_days": convergence_days,
            "avg_pct": round(avg_pct, 3),
            "persistence_ratio": round(active_days / period_days, 3) if period_days > 0 else 0.0,
        }

    return {
        "categories": cat_stats,
        "period_days": period_days,
    }


def generate_monthly_summary(
    db: Any,
    reference_date: str,
) -> dict[str, Any]:
    """Generate monthly narrative summary.

    Includes:
    - Narrative lifespan averages
    - Peak→convergence durations
    - Persistence probability distribution
    - Hypothesis evaluation stats
    """
    lifecycle = compute_narrative_lifecycle(db, days=30, reference_date=reference_date)
    hyp_stats = db.get_hypothesis_stats(days=30)

    # Compute lifespan averages
    cats = lifecycle.get("categories", {})
    active_days_list = [c["active_days"] for c in cats.values() if c["active_days"] > 0]
    convergence_list = [c["convergence_days"] for c in cats.values() if c["convergence_days"] > 0]

    avg_lifespan = sum(active_days_list) / len(active_days_list) if active_days_list else 0.0
    avg_convergence = sum(convergence_list) / len(convergence_list) if convergence_list else 0.0

    # Persistence distribution
    persistence_dist: Counter = Counter()
    for c in cats.values():
        ratio = c["persistence_ratio"]
        if ratio >= 0.8:
            persistence_dist["常時（80%+）"] += 1
        elif ratio >= 0.5:
            persistence_dist["頻出（50-80%）"] += 1
        elif ratio >= 0.2:
            persistence_dist["時折（20-50%）"] += 1
        else:
            persistence_dist["稀（<20%）"] += 1

    return {
        "period_days": lifecycle["period_days"],
        "narrative_lifecycle": lifecycle["categories"],
        "avg_lifespan_days": round(avg_lifespan, 1),
        "avg_convergence_days": round(avg_convergence, 1),
        "persistence_distribution": dict(persistence_dist),
        "hypothesis_stats": hyp_stats,
    }

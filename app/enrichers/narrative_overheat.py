"""Narrative overheat detector.

Detects when AI narratives dominate without sufficient evidence backing,
signaling potential narrative-driven bias.

v2: Uses evidence_score median and 7-day delta (not absolute threshold)
to avoid false alarms when AI events are well-supported by market data.
"""

from __future__ import annotations

import logging
from statistics import median
from typing import Any

logger = logging.getLogger(__name__)


def detect_narrative_overheat(
    events: list[dict[str, Any]],
    narrative_index: dict[str, Any],
    db: Any | None = None,
    ai_pct_threshold: float = 0.5,
    streak_days_threshold: int = 3,
    delta_threshold: float = 0.15,
    evidence_threshold: float = 0.3,
    reference_date: str | None = None,
) -> dict[str, Any] | None:
    """Detect narrative overheat conditions.

    Returns an alert dict when ALL three conditions are met:
    1. AI ratio exceeds 7-day average by delta_threshold or more
    2. Median evidence_score of AI events < evidence_threshold
       (narratives lack backing by market data / official sources)
    3. streak_days_threshold+ consecutive days of AI-dominant snapshots in DB

    If the 7-day average is unavailable, falls back to ai_pct_threshold
    as an absolute threshold for condition 1.

    Args:
        events: Enriched events with ai_centricity, evidence_score.
        narrative_index: Output from compute_narrative_concentration().
        db: Database instance for historical streak check.
        ai_pct_threshold: Fallback absolute AI ratio threshold.
        streak_days_threshold: Consecutive days threshold for condition 3.
        delta_threshold: AI ratio must exceed 7-day avg by this amount.
        evidence_threshold: Median evidence_score below this triggers condition 2.

    Returns:
        Alert dict with severity, message, conditions, and recommendation,
        or None if no overheat detected.
    """
    ai_ratio = narrative_index.get("ai_ratio", 0.0)
    historical_avg = narrative_index.get("historical_avg")

    # Condition 1: AI ratio significantly above recent baseline
    hist_ai = None
    if historical_avg and "AI/LLM/自動化" in historical_avg:
        hist_ai = historical_avg["AI/LLM/自動化"]
        condition_ai_surge = ai_ratio > hist_ai + delta_threshold
    else:
        # Fallback: absolute threshold when no history available
        condition_ai_surge = ai_ratio > ai_pct_threshold

    # Condition 2: AI events have weak evidence backing
    ai_events = [
        e for e in events
        if (e.get("ai_centricity") or 0) > ai_pct_threshold
    ]
    evidence_scores = [
        e.get("evidence_score") or 0.0 for e in ai_events
    ]
    median_evidence = median(evidence_scores) if evidence_scores else 0.0
    condition_weak_evidence = (
        median_evidence < evidence_threshold and len(ai_events) > 0
    )

    # Condition 3: 3+ consecutive days AI-dominant
    condition_streak = False
    consecutive_days = 0
    if db is not None:
        try:
            history = db.get_narrative_history(days=7, reference_date=reference_date)
            consecutive_days = _count_ai_dominant_streak(history)
            condition_streak = consecutive_days >= streak_days_threshold
        except Exception:
            logger.debug("Failed to check AI dominance streak")

    if not (condition_ai_surge and condition_weak_evidence and condition_streak):
        return None

    delta_info = ""
    if hist_ai is not None:
        delta_info = f"（7日平均{hist_ai*100:.0f}%から+{(ai_ratio - hist_ai)*100:.0f}pt）"
    else:
        delta_info = f"（閾値{ai_pct_threshold*100:.0f}%超過）"

    alert = {
        "severity": "warning",
        "message": (
            f"ナラティブ過熱警告: AI関連が{ai_ratio*100:.0f}%{delta_info}、"
            f"裏付けスコア中央値{median_evidence:.2f}（閾値{evidence_threshold}未満）、"
            f"{consecutive_days}日連続でAI優勢"
        ),
        "conditions": {
            "ai_ratio": ai_ratio,
            "historical_ai_avg": hist_ai,
            "median_evidence_score": round(median_evidence, 3),
            "consecutive_ai_dominant_days": consecutive_days,
        },
        "recommendation": (
            "非AI構造変化への注目度を意図的に高めることを推奨します。"
            "AI関連ナラティブが市場の実態以上に増幅されている可能性があります。"
        ),
    }

    logger.warning(
        "Narrative overheat detected: AI=%.0f%%, median_evidence=%.2f, streak=%d days",
        ai_ratio * 100, median_evidence, consecutive_days,
    )
    return alert


def _count_ai_dominant_streak(
    history: list[dict[str, Any]],
) -> int:
    """Count consecutive recent days where AI category was dominant.

    Groups snapshots by date, checks if AI/LLM/自動化 had the highest pct.
    Counts backwards from most recent date.
    """
    if not history:
        return 0

    # Group by date
    daily: dict[str, dict[str, float]] = {}
    for row in history:
        date = row["date"]
        cat = row["category"]
        pct = row["event_pct"]
        if date not in daily:
            daily[date] = {}
        daily[date][cat] = pct

    if not daily:
        return 0

    # Sort dates descending (most recent first)
    sorted_dates = sorted(daily.keys(), reverse=True)

    streak = 0
    for date in sorted_dates:
        cats = daily[date]
        if not cats:
            break
        top_cat = max(cats, key=cats.get)
        if top_cat == "AI/LLM/自動化":
            streak += 1
        else:
            break

    return streak

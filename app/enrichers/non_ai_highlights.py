"""Non-AI structural change highlighter.

Extracts top non-AI events prioritizing "quietly important" signals:
high SIS + low media coverage + market price/volume activity.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def compute_undercovered_score(event: dict[str, Any]) -> float:
    """Compute how "quietly important" an event is.

    High score means: structurally important (high SIS) but under-covered
    by media / community, especially if backed by market signals.

    Components (0-1 each):
    - sis_factor (40%): normalized SIS
    - coverage_deficit (30%): 1 - evidence_score (low coverage = high deficit)
    - market_signal (30%): 1.0 if price_change/volume_spike, else 0.0
    """
    sis = event.get("sis") or 0.0
    evidence_score = event.get("evidence_score") or 0.0
    signal_type = event.get("signal_type", "")

    sis_factor = min(sis / 0.5, 1.0)
    coverage_deficit = max(0.0, 1.0 - evidence_score)
    market_signal = 1.0 if signal_type in ("price_change", "volume_spike") else 0.0

    score = sis_factor * 0.4 + coverage_deficit * 0.3 + market_signal * 0.3
    return round(score, 3)


def extract_non_ai_highlights(
    events: list[dict[str, Any]],
    ai_threshold: float = 0.3,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """Extract top non-AI structural change events.

    Filters events with ai_centricity below the threshold,
    then returns the top-N by undercovered_score (SIS + low coverage + market signal).

    Args:
        events: Enriched events with ai_centricity, sis, evidence_score fields.
        ai_threshold: Maximum ai_centricity to be considered non-AI.
        top_n: Number of highlights to return.

    Returns:
        List of dicts with keys: ticker, summary, sis, narrative_category,
        ai_centricity, shock_type, evidence_titles, evidence_score, undercovered_score.
    """
    non_ai = [
        e for e in events
        if (e.get("ai_centricity") or 0.0) < ai_threshold
    ]

    # Compute undercovered_score for each
    for e in non_ai:
        e["undercovered_score"] = compute_undercovered_score(e)

    # Sort by undercovered_score descending (quietly important first)
    non_ai.sort(key=lambda e: e.get("undercovered_score") or 0, reverse=True)

    highlights = []
    for e in non_ai[:top_n]:
        highlights.append({
            "ticker": e.get("ticker", ""),
            "summary": e.get("summary", "N/A"),
            "sis": e.get("sis", 0),
            "narrative_category": e.get("narrative_category", "その他"),
            "ai_centricity": e.get("ai_centricity", 0.0),
            "shock_type": e.get("shock_type", ""),
            "evidence_titles": e.get("evidence_titles", []),
            "evidence_score": e.get("evidence_score", 0.0),
            "undercovered_score": e.get("undercovered_score", 0.0),
        })

    logger.info(
        "Non-AI highlights: %d candidates, %d selected (threshold=%.1f, by undercovered_score)",
        len(non_ai), len(highlights), ai_threshold,
    )
    return highlights

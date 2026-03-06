"""Narrative Graph: theme→ticker graph construction."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


def _classify_strength(sis: float) -> str:
    """Classify SIS into strength label."""
    if sis >= 0.5:
        return "strong"
    elif sis >= 0.2:
        return "moderate"
    return "weak"


def build_narrative_graph(
    enriched_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build narrative category → ticker graph from enriched events.

    Groups events by narrative_category, lists tickers within each
    category sorted by SIS, with strength classification.

    Returns list of dicts:
        - category: narrative category name
        - tickers: list of {ticker, sis, strength}
        - event_count: total events in category
    """
    category_tickers: dict[str, dict[str, float]] = defaultdict(dict)
    category_counts: dict[str, int] = defaultdict(int)

    for e in enriched_events:
        cat = e.get("narrative_category", "")
        ticker = e.get("ticker", "")
        sis = e.get("sis", 0.0)
        if cat and ticker:
            # Keep highest SIS per ticker per category
            if ticker not in category_tickers[cat] or sis > category_tickers[cat][ticker]:
                category_tickers[cat][ticker] = sis
            category_counts[cat] += 1

    graph = []
    for cat in sorted(category_tickers, key=lambda c: category_counts[c], reverse=True):
        tickers_map = category_tickers[cat]
        tickers_list = sorted(
            tickers_map.items(), key=lambda x: x[1], reverse=True,
        )
        graph.append({
            "category": cat,
            "tickers": [
                {
                    "ticker": ticker,
                    "sis": round(sis, 3),
                    "strength": _classify_strength(sis),
                }
                for ticker, sis in tickers_list
            ],
            "event_count": category_counts[cat],
        })

    return graph


def format_narrative_graph_text(graph: list[dict[str, Any]]) -> str:
    """Format narrative graph as tree-style text for reports."""
    lines = []
    for entry in graph:
        lines.append(entry["category"])
        tickers = entry["tickers"]
        for i, t in enumerate(tickers):
            prefix = "└──" if i == len(tickers) - 1 else "├──"
            lines.append(
                f"{prefix} {t['ticker']} (SIS: {t['sis']:.2f}, {t['strength']})"
            )
        lines.append("")
    return "\n".join(lines)

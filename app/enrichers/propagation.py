"""Sector-based propagation candidate identification."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_SIGNAL_TYPE_JA = {
    "price_change": "価格変動",
    "volume_spike": "出来高急増",
    "mention_surge": "言及急増",
}

_SECTOR_JA = {
    "AI_Infrastructure": "AI基盤",
    "Cloud_Security": "クラウドセキュリティ",
    "Data_Platform": "データプラットフォーム",
    "Enterprise_AI": "エンタープライズAI",
    "Cloud_Networking": "クラウドネットワーキング",
}


def find_propagation(
    anomalies: list[dict[str, Any]],
    sector_map: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Find tickers that may be affected by observed anomalies via sector linkage.

    For each anomaly ticker, looks up which sector(s) it belongs to in the
    sector_map and returns the other tickers in the same sector as
    propagation candidates, with Japanese reason strings.

    Args:
        anomalies: List of anomaly dicts (must include "ticker" key).
        sector_map: Mapping of sector name to list of ticker symbols.

    Returns:
        List of propagation candidate dicts with: source_ticker, related_tickers,
        sector, reason (in Japanese).
    """
    # Build reverse lookup: ticker -> list of sectors
    ticker_to_sectors: dict[str, list[str]] = {}
    for sector, members in sector_map.items():
        for t in members:
            ticker_to_sectors.setdefault(t, []).append(sector)

    results: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for anomaly in anomalies:
        source_ticker = anomaly["ticker"]
        sectors = ticker_to_sectors.get(source_ticker, [])

        if not sectors:
            logger.debug("No sector mapping found for %s", source_ticker)
            continue

        for sector in sectors:
            pair_key = (source_ticker, sector)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            related = [t for t in sector_map.get(sector, []) if t != source_ticker]
            if not related:
                continue

            signal_type = anomaly.get("signal_type", "unknown")
            signal_ja = _SIGNAL_TYPE_JA.get(signal_type, signal_type)
            score = anomaly.get("score", 0)
            related_str = ", ".join(related)

            sector_ja = _SECTOR_JA.get(sector, sector)
            results.append({
                "source_ticker": source_ticker,
                "related_tickers": related,
                "sector": sector_ja,
                "reason": (
                    f"{source_ticker}の{signal_ja}異常（スコア{score:.2f}）により、"
                    f"同セクター{sector_ja}の{related_str}も影響を受ける可能性"
                ),
            })
            logger.info(
                "Propagation: %s -> %s (sector: %s)",
                source_ticker, related, sector,
            )

    return results

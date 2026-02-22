"""Sector-based propagation candidate identification with direction estimation.

v6: Adds propagation direction (positive/negative/mixed) based on
historical reaction patterns from the reaction_patterns DB table.
"""

from __future__ import annotations

import logging
from collections import Counter
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
    "Energy": "エネルギー",
    "Financial": "金融",
    "Healthcare": "ヘルスケア",
    "Defense_Geopolitics": "防衛・地政学",
}


_DIRECTION_JA = {
    "positive": "ポジティブ",
    "negative": "ネガティブ",
    "mixed": "混合",
    "unknown": "不明",
}


def estimate_propagation_direction(
    db: Any | None,
    sector: str,
    shock_type: str,
) -> dict[str, Any]:
    """Estimate propagation direction from historical reaction patterns.

    Looks up past reactions for the same sector + shock_type combination
    and returns the dominant direction with confidence.

    Returns:
        Dict with keys:
        - direction: "positive" | "negative" | "mixed" | "unknown"
        - confidence: float (0-1, based on sample size)
        - sample_count: int
    """
    if db is None:
        return {"direction": "unknown", "confidence": 0.0, "sample_count": 0}

    try:
        patterns = db.get_reaction_patterns(
            sector=sector, shock_type=shock_type, days=90,
        )
    except Exception:
        return {"direction": "unknown", "confidence": 0.0, "sample_count": 0}

    if not patterns:
        return {"direction": "unknown", "confidence": 0.0, "sample_count": 0}

    counts: Counter = Counter()
    for p in patterns:
        counts[p.get("price_direction", "neutral")] += 1

    total = sum(counts.values())
    if total == 0:
        return {"direction": "unknown", "confidence": 0.0, "sample_count": 0}

    pos = counts.get("positive", 0)
    neg = counts.get("negative", 0)

    if pos > neg and pos / total >= 0.6:
        direction = "positive"
    elif neg > pos and neg / total >= 0.6:
        direction = "negative"
    elif total >= 3:
        direction = "mixed"
    else:
        direction = "unknown"

    # Confidence: scales with sample count (min 3 for any confidence)
    confidence = min(total / 10.0, 1.0) if total >= 3 else 0.0

    return {
        "direction": direction,
        "confidence": round(confidence, 2),
        "sample_count": total,
    }


def find_propagation(
    anomalies: list[dict[str, Any]],
    sector_map: dict[str, list[str]],
    db: Any | None = None,
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

            # Estimate direction from historical patterns
            shock_type = anomaly.get("shock_type", "")
            dir_info = estimate_propagation_direction(db, sector, shock_type)
            dir_ja = _DIRECTION_JA.get(dir_info["direction"], "不明")

            direction_note = ""
            if dir_info["direction"] != "unknown":
                direction_note = f"（過去{dir_info['sample_count']}件の類似パターンから{dir_ja}方向、確信度{dir_info['confidence']:.0%}）"

            results.append({
                "source_ticker": source_ticker,
                "related_tickers": related,
                "sector": sector_ja,
                "reason": (
                    f"{source_ticker}の{signal_ja}異常（スコア{score:.2f}）により、"
                    f"同セクター{sector_ja}の{related_str}も影響を受ける可能性"
                    f"{direction_note}"
                ),
                "direction": dir_info["direction"],
                "direction_confidence": dir_info["confidence"],
                "direction_sample_count": dir_info["sample_count"],
            })
            logger.info(
                "Propagation: %s -> %s (sector: %s)",
                source_ticker, related, sector,
            )

    return results

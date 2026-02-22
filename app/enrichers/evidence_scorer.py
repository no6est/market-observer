"""Evidence score calculator.

Computes a 0-1 evidence score that quantifies how well-supported
an event is by market data, media coverage, and official sources.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# --- Source tier classification ---
# Tier1: Major wire services, financial press, regulatory bodies
_TIER1_DOMAINS = frozenset({
    "reuters", "bloomberg", "wsj", "nytimes", "ft",
    "apnews", "bbc", "cnbc", "sec.gov",
})

# Tier2: Reputable specialized / tech media
_TIER2_DOMAINS = frozenset({
    "techcrunch", "arstechnica", "theverge", "wired",
    "forbes", "neowin", "protocol", "semafor", "axios",
})

# Keywords suggesting official announcements
_OFFICIAL_KEYWORDS = frozenset({
    "announce", "announces", "announced", "announcement",
    "launch", "launches", "launched",
    "release", "releases", "released",
    "quarterly", "earnings", "revenue", "guidance",
    "filing", "sec", "10-k", "10-q", "8-k",
    "ceo", "cfo", "cto", "president",
    "official", "press release",
    "partnership", "acquisition", "merger",
})


def compute_evidence_score(
    event: dict[str, Any],
    articles: list[dict[str, Any]],
    posts: list[dict[str, Any]],
) -> dict[str, float]:
    """Compute evidence score with breakdown.

    Args:
        event: Anomaly/enriched event dict.
        articles: Related articles (already filtered for this ticker).
        posts: Related community posts (already filtered for this ticker).

    Returns:
        Dict with keys:
        - evidence_score: float (0.0-1.0) weighted composite
        - market_evidence: float (0.0-1.0) price/volume support
        - media_evidence: float (0.0-1.0) media coverage quality
        - official_evidence: float (0.0-1.0) official announcement presence
    """
    market = _compute_market_evidence(event)
    media = _compute_media_evidence(articles)
    official = _compute_official_evidence(articles, posts)

    score = market * 0.4 + media * 0.35 + official * 0.25

    result = {
        "evidence_score": round(score, 3),
        "market_evidence": round(market, 3),
        "media_evidence": round(media, 3),
        "official_evidence": round(official, 3),
    }

    logger.debug(
        "Evidence score for %s: %.3f (mkt=%.2f, media=%.2f, official=%.2f)",
        event.get("ticker", "?"), score, market, media, official,
    )
    return result


def _compute_market_evidence(event: dict[str, Any]) -> float:
    """Score based on price/volume signal presence and strength."""
    signal_type = event.get("signal_type", "")
    z_score = abs(event.get("z_score") or 0)

    if signal_type == "price_change":
        base = 0.7
    elif signal_type == "volume_spike":
        base = 0.5
    else:
        # mention_surge only — weak market evidence
        return 0.1

    # Bonus for strong statistical significance
    bonus = min(0.3, z_score * 0.1) if z_score > 2 else 0.0
    return min(1.0, base + bonus)


def _compute_media_evidence(articles: list[dict[str, Any]]) -> float:
    """Score based on media coverage quality and breadth."""
    if not articles:
        return 0.0

    tier1_count = 0
    tier2_count = 0
    for a in articles:
        if _is_tier1(a):
            tier1_count += 1
        elif _is_tier2(a):
            tier2_count += 1

    score = tier1_count * 0.4 + tier2_count * 0.2
    return round(min(1.0, score), 3)


def _compute_official_evidence(
    articles: list[dict[str, Any]],
    posts: list[dict[str, Any]],
) -> float:
    """Score based on presence of official announcements."""
    all_texts = []
    for a in articles:
        all_texts.append((a.get("title") or "").lower())
        all_texts.append((a.get("summary") or "").lower())
    for p in posts:
        all_texts.append((p.get("title") or "").lower())

    official_hits = 0
    for text in all_texts:
        if not text:
            continue
        for kw in _OFFICIAL_KEYWORDS:
            if kw in text:
                official_hits += 1
                break  # one hit per text

    if official_hits == 0:
        return 0.0
    return round(min(1.0, official_hits * 0.35), 3)


def _is_tier1(article: dict[str, Any]) -> bool:
    """Check if article is from a Tier1 source."""
    source = (article.get("source") or "").lower()
    url = (article.get("url") or "").lower()
    return any(domain in source or domain in url for domain in _TIER1_DOMAINS)


def _is_tier2(article: dict[str, Any]) -> bool:
    """Check if article is from a Tier2 source."""
    source = (article.get("source") or "").lower()
    url = (article.get("url") or "").lower()
    return any(domain in source or domain in url for domain in _TIER2_DOMAINS)

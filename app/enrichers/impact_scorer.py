"""Structure Impact Score (SIS) calculator.

Evaluates the structural significance of each detected event based on:
- Multi-media coverage breadth (RSS + Reddit + HackerNews)
- Official source presence (press releases, SEC filings)
- Competitor involvement (multiple tickers in same sector affected)
- SNS noise penalty (single social media mention without corroboration)
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_OFFICIAL_PATTERN = re.compile(
    r"\b(press\s+release|official|SEC\s+filing|investor\s+relations|"
    r"earnings\s+call|annual\s+report|quarterly\s+report|10-[KQ]|8-K|"
    r"announce|statement)\b",
    re.IGNORECASE,
)


def _count_by_source(
    ticker: str,
    articles: list[dict[str, Any]],
    posts: list[dict[str, Any]],
) -> dict[str, int]:
    """Count mentions of ticker across different source types."""
    pattern = re.compile(r"\b" + re.escape(ticker) + r"\b", re.IGNORECASE)

    rss = sum(
        1 for a in articles
        if pattern.search((a.get("title", "") or "") + " " + (a.get("summary", "") or ""))
    )
    reddit = sum(
        1 for p in posts
        if p.get("source") == "reddit"
        and pattern.search((p.get("title", "") or "") + " " + (p.get("body", "") or ""))
    )
    hackernews = sum(
        1 for p in posts
        if p.get("source") == "hackernews"
        and pattern.search((p.get("title", "") or "") + " " + (p.get("body", "") or ""))
    )

    return {"rss": rss, "reddit": reddit, "hackernews": hackernews}


def compute_structure_impact_score(
    anomaly: dict[str, Any],
    related_articles: list[dict[str, Any]],
    related_posts: list[dict[str, Any]],
    sector_anomaly_count: int = 0,
) -> dict[str, Any]:
    """Compute the Structure Impact Score for an anomaly event.

    Uses pre-filtered related articles/posts (already matched to ticker)
    for more accurate scoring.

    Returns a dict with the SIS score and component breakdown.
    """
    ticker = anomaly["ticker"]

    # 1. Multi-media coverage: how many different source types?
    has_rss = len(related_articles) > 0
    reddit_posts = [p for p in related_posts if p.get("source") == "reddit"]
    hn_posts = [p for p in related_posts if p.get("source") == "hackernews"]
    has_reddit = len(reddit_posts) > 0
    has_hn = len(hn_posts) > 0

    source_types = sum([has_rss, has_reddit, has_hn])
    multi_media = min(source_types / 3.0, 1.0)

    # 2. Official source presence
    has_official = any(
        _OFFICIAL_PATTERN.search(
            (a.get("title", "") or "") + " " + (a.get("summary", "") or "")
        )
        for a in related_articles
    )
    official_source = 1.0 if has_official else 0.0

    # 3. Competitor involvement (multiple tickers in same sector affected)
    competitor_involvement = min(sector_anomaly_count / 3.0, 1.0)

    # 4. SNS noise penalty (only if single low-quality mention)
    total_evidence = len(related_articles) + len(related_posts)
    if total_evidence <= 1 and not has_rss:
        sns_penalty = -0.2
    elif total_evidence == 0:
        sns_penalty = -0.3
    else:
        sns_penalty = 0.0

    # 5. Anomaly strength from z-score
    anomaly_score = anomaly.get("score", 0)

    # Compute SIS with balanced weights
    raw = (
        multi_media * 0.25
        + official_source * 0.2
        + competitor_involvement * 0.2
        + anomaly_score * 0.35
    )
    sis = max(0, min(1.0, raw + sns_penalty * 0.3))

    result = {
        "sis": round(sis, 3),
        "multi_media": round(multi_media, 2),
        "official_source": official_source,
        "competitor_involvement": round(competitor_involvement, 2),
        "sns_penalty": round(sns_penalty, 2),
        "source_counts": {
            "rss": len(related_articles),
            "reddit": len(reddit_posts),
            "hackernews": len(hn_posts),
        },
    }

    logger.info(
        "SIS for %s: %.3f (media=%.2f, official=%.0f, competitor=%.2f, evidence=%d)",
        ticker, sis, multi_media, official_source, competitor_involvement, total_evidence,
    )

    return result

"""Shared ticker-to-company-name aliases for content matching.

Used by hypothesis generation, event enrichment, and impact scoring
to match articles/posts that use company names instead of ticker symbols.
"""

from __future__ import annotations

import re
from typing import Any

# Ticker to company name aliases for broader matching
TICKER_ALIASES: dict[str, list[str]] = {
    "NVDA": ["Nvidia", "NVDA"],
    "MSFT": ["Microsoft", "MSFT"],
    "GOOGL": ["Google", "Alphabet", "GOOGL"],
    "SNOW": ["Snowflake", "SNOW"],
    "CRWD": ["CrowdStrike", "CRWD"],
    "DDOG": ["Datadog", "DDOG"],
    "PLTR": ["Palantir", "PLTR"],
    "NET": ["Cloudflare"],  # "NET" alone is ambiguous
    "MDB": ["MongoDB", "MDB"],
    "PATH": ["UiPath"],  # "PATH" alone is ambiguous
    # 非AI銘柄
    "XOM": ["Exxon", "ExxonMobil", "XOM"],
    "JPM": ["JPMorgan", "JP Morgan", "Chase", "JPM"],
    "UNH": ["UnitedHealth", "United Health", "UNH"],
    "LMT": ["Lockheed", "Lockheed Martin", "LMT"],
    "NEE": ["NextEra", "NEE"],
}


def find_related_content(
    ticker: str,
    articles: list[dict[str, Any]],
    posts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Find articles and posts mentioning a ticker or its company name.

    For articles: matches in title only (higher relevance).
    For posts: matches in title + body, sorted with title-matches first.

    Returns:
        Tuple of (matched_articles, matched_posts) where posts are
        ordered by relevance (title-match before body-only-match).
    """
    aliases = TICKER_ALIASES.get(ticker, [ticker])
    alt = "|".join(re.escape(a) for a in aliases)
    pattern = re.compile(r"\b(?:" + alt + r")\b", re.IGNORECASE)

    # Articles: title-only matching for higher relevance
    matched_articles = [
        a for a in articles
        if pattern.search(a.get("title", "") or "")
    ]

    # Posts: match in title + body
    matched_posts = [
        p for p in posts
        if pattern.search((p.get("title", "") or "") + " " + (p.get("body", "") or ""))
    ]

    # Prioritize posts where ticker/company appears in the title
    title_match = [p for p in matched_posts if pattern.search(p.get("title", "") or "")]
    body_only = [p for p in matched_posts if not pattern.search(p.get("title", "") or "")]
    matched_posts = title_match + body_only

    return matched_articles, matched_posts

"""Shared ticker-to-company-name aliases for content matching.

Used by hypothesis generation, event enrichment, and impact scoring
to match articles/posts that use company names instead of ticker symbols.
"""

from __future__ import annotations

import re
from typing import Any

_CJK_RANGE = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]')


def _has_cjk(text: str) -> bool:
    """Return True if *text* contains any CJK character."""
    return bool(_CJK_RANGE.search(text))


def _build_alias_pattern(aliases: list[str]) -> re.Pattern:
    """Build a regex pattern that handles CJK and ASCII aliases differently.

    ASCII aliases use ``\\b`` word boundaries (existing behaviour).
    CJK aliases use boundary-free substring matching because ``\\b``
    does not work with CJK characters.
    """
    cjk = [a for a in aliases if _has_cjk(a)]
    ascii_ = [a for a in aliases if not _has_cjk(a)]
    parts: list[str] = []
    if ascii_:
        parts.append(r"\b(?:" + "|".join(re.escape(a) for a in ascii_) + r")\b")
    if cjk:
        parts.append(r"(?:" + "|".join(re.escape(a) for a in cjk) + r")")
    return re.compile("|".join(parts), re.IGNORECASE)


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
    # JP銘柄
    "7203.T": ["トヨタ", "Toyota", "7203.T"],
    "6758.T": ["ソニー", "Sony", "6758.T"],
    "9984.T": ["ソフトバンク", "SoftBank", "9984.T"],
    "8035.T": ["東京エレクトロン", "Tokyo Electron", "8035.T"],
    "9432.T": ["NTT", "日本電信電話", "9432.T"],
    "6098.T": ["リクルート", "Recruit", "6098.T"],
    "6861.T": ["キーエンス", "Keyence", "6861.T"],
    "6501.T": ["日立", "Hitachi", "6501.T"],
    "8306.T": ["三菱UFJ", "MUFG", "8306.T"],
    "2914.T": ["JT", "日本たばこ", "Japan Tobacco", "2914.T"],
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
    pattern = _build_alias_pattern(aliases)

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

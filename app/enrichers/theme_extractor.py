"""Theme extraction using TF-IDF keyword analysis with novelty scoring.

Includes both word-level extraction (extract_themes) and
theme-level abstraction (abstract_structural_themes) for structural
change observation.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from app.database import Database

logger = logging.getLogger(__name__)

# Expanded stop words list including URL fragments, pronouns, and common web/forum words
_STOP_WORDS = frozenset({
    # Standard English stop words
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "its", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "can", "shall",
    "this", "that", "these", "those", "not", "no", "nor", "so", "if",
    "as", "up", "out", "about", "into", "over", "after", "before",
    "between", "under", "above", "such", "each", "which", "their",
    "than", "other", "some", "very", "just", "also", "more", "how",
    "what", "when", "where", "who", "why", "all", "any", "both", "few",
    "most", "own", "same", "too", "only", "new", "now", "says", "said",
    "one", "two", "like", "get", "got", "make", "made", "via", "per",
    # URL fragments and HTML entities
    "https", "http", "www", "com", "org", "net", "html",
    "quot", "amp", "nbsp", "ndash", "mdash", "rsquo", "lsquo",
    "rdquo", "ldquo", "hellip",
    # Pronouns
    "you", "they", "your", "them", "their", "its", "our",
    "she", "her", "him", "his",
    # Common web/forum words
    "reddit", "post", "comment", "comments", "link", "edit",
    "deleted", "removed", "think", "going", "people", "want",
    "even", "still", "really", "know", "right", "much",
    "year", "years", "time", "don", "doesn", "didn",
    "can", "could", "would", "there", "here", "things",
    "something", "anything", "been", "back", "well", "good", "way",
    # Financial / market generic terms (too broad to be themes)
    "stock", "stocks", "market", "markets", "share", "shares",
    "trading", "trade", "trades", "investor", "investors",
    "earnings", "revenue", "price", "prices", "company",
    "companies", "business", "report", "quarter", "quarterly",
    "growth", "billion", "million", "percent", "investment",
    "financial", "fund", "funds", "index", "sector",
    "nasdaq", "dow", "futures", "portfolio", "dividend",
    "bull", "bear", "rally", "sell", "buy", "hold",
    "analysis", "analyst", "analysts", "forecast", "data",
    "news", "update", "updates", "today", "yesterday",
    "morning", "week", "month", "daily", "annual",
})


def _tokenize(text: str) -> list[str]:
    """Lowercase tokenization, filtering short tokens and stop words."""
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return [w for w in words if w not in _STOP_WORDS]


def _compute_tfidf(documents: list[list[str]], top_n: int = 20) -> list[tuple[str, float]]:
    """Compute TF-IDF scores across a set of tokenized documents.

    Returns the top_n terms by TF-IDF score.
    """
    if not documents:
        return []

    # Term frequency across all documents combined
    tf_counter: Counter[str] = Counter()
    for doc in documents:
        tf_counter.update(doc)

    total_terms = sum(tf_counter.values())
    if total_terms == 0:
        return []

    # Document frequency: in how many docs does each term appear?
    df_counter: Counter[str] = Counter()
    for doc in documents:
        df_counter.update(set(doc))

    num_docs = len(documents)
    tfidf: dict[str, float] = {}
    for term, tf in tf_counter.items():
        df = df_counter.get(term, 1)
        idf = math.log(1 + num_docs / df)
        tfidf[term] = (tf / total_terms) * idf

    ranked = sorted(tfidf.items(), key=lambda x: x[1], reverse=True)
    return ranked[:top_n]


def extract_themes(
    db: Database,
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """Extract emerging themes from recent articles and community posts.

    Uses TF-IDF to identify important keywords in the last 24h of content,
    then compares frequencies against a 7-day baseline to compute a novelty
    score (momentum).

    Args:
        db: Database instance for querying articles and posts.
        top_n: Number of top themes to return.

    Returns:
        List of theme dicts with: name, keywords, mention_count, momentum, first_seen.
    """
    # Recent window (24h) and baseline window (7 days)
    recent_articles = db.get_recent_articles(hours=24)
    recent_posts = db.get_recent_posts(hours=24)
    baseline_articles = db.get_recent_articles(hours=7 * 24)
    baseline_posts = db.get_recent_posts(hours=7 * 24)

    # Build document lists
    recent_docs = [
        _tokenize((a.get("title", "") or "") + " " + (a.get("summary", "") or ""))
        for a in recent_articles
    ] + [
        _tokenize((p.get("title", "") or "") + " " + (p.get("body", "") or ""))
        for p in recent_posts
    ]

    baseline_docs = [
        _tokenize((a.get("title", "") or "") + " " + (a.get("summary", "") or ""))
        for a in baseline_articles
    ] + [
        _tokenize((p.get("title", "") or "") + " " + (p.get("body", "") or ""))
        for p in baseline_posts
    ]

    if not recent_docs:
        logger.info("No recent content for theme extraction")
        return []

    # TF-IDF on recent content
    recent_tfidf = _compute_tfidf(recent_docs, top_n=top_n * 4)
    if not recent_tfidf:
        return []

    # Baseline term frequencies for novelty comparison
    baseline_tf: Counter[str] = Counter()
    for doc in baseline_docs:
        baseline_tf.update(doc)
    baseline_total = max(sum(baseline_tf.values()), 1)

    recent_tf: Counter[str] = Counter()
    for doc in recent_docs:
        recent_tf.update(doc)
    recent_total = max(sum(recent_tf.values()), 1)

    # Score each top keyword by novelty (rate of change vs baseline)
    theme_candidates: list[dict[str, Any]] = []
    for term, tfidf_score in recent_tfidf:
        recent_rate = recent_tf[term] / recent_total
        baseline_rate = baseline_tf.get(term, 0) / baseline_total

        # Momentum: how much the rate increased relative to baseline
        if baseline_rate > 0:
            momentum = (recent_rate - baseline_rate) / baseline_rate
        else:
            # New term not in baseline -- high novelty
            momentum = recent_rate * 100

        theme_candidates.append({
            "name": term,
            "keywords": [term],
            "mention_count": recent_tf[term],
            "momentum": round(momentum, 4),
            "tfidf_score": round(tfidf_score, 6),
            "first_seen": datetime.utcnow().isoformat(),
        })

    # When recent and baseline windows overlap heavily (e.g. first run),
    # momentum is near-zero for all terms. Fall back to TF-IDF score ranking.
    has_meaningful_momentum = any(abs(t["momentum"]) > 0.01 for t in theme_candidates)
    if has_meaningful_momentum:
        theme_candidates.sort(key=lambda t: t["momentum"], reverse=True)
    else:
        theme_candidates.sort(key=lambda t: t["tfidf_score"], reverse=True)
    themes = theme_candidates[:top_n]

    # Group nearby keywords into theme clusters via co-occurrence
    if len(recent_tfidf) > top_n:
        all_terms = [t for t, _ in recent_tfidf]
        for theme in themes:
            primary = theme["name"]
            cooccur: Counter[str] = Counter()
            for doc in recent_docs:
                if primary in doc:
                    cooccur.update(doc)
            cooccur.pop(primary, None)
            related = [t for t, _ in cooccur.most_common(4) if t in all_terms]
            theme["keywords"] = [primary] + related

    for theme in themes:
        if not has_meaningful_momentum:
            # On first run, use TF-IDF score as relevance indicator
            theme["relevance_score"] = theme.pop("tfidf_score", 0)
        else:
            theme.pop("tfidf_score", None)
        logger.info(
            "Theme: %s (momentum=%.2f, mentions=%d)",
            theme["name"], theme["momentum"], theme["mention_count"],
        )

    return themes


# ---- Theme-level abstraction for structural change reports ----

_SHOCK_THEME_PATTERNS: dict[str, str] = {
    "Tech shock": "{sector}セクターにおけるテクノロジーショック",
    "Business model shock": "{sector}セクターのビジネスモデル変革",
    "Regulation shock": "{sector}セクターに影響する規制動向",
    "Narrative shift": "{sector}セクターの市場ナラティブ転換",
    "Execution signal": "{sector}セクターの業績・経営動向",
}

# Map sector names to more readable Japanese
_SECTOR_JA: dict[str, str] = {
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


def abstract_structural_themes(
    enriched_events: list[dict[str, Any]],
    db: Database | None = None,
) -> list[dict[str, Any]]:
    """Generate theme-level abstractions from enriched events.

    Groups events by sector to create higher-level structural themes.
    When multiple shock types exist in the same sector, uses the dominant one.

    Args:
        enriched_events: Anomaly events enriched with shock_type, sector,
            evidence_titles, etc.
        db: Optional database for additional context.

    Returns:
        List of structural theme dicts.
    """
    if not enriched_events:
        return []

    # Group events primarily by sector (higher-level abstraction)
    sector_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in enriched_events:
        sector = event.get("sector", "Other")
        sector_groups[sector].append(event)

    themes: list[dict[str, Any]] = []
    for sector, events in sector_groups.items():
        tickers = list(dict.fromkeys(e["ticker"] for e in events))

        # Determine dominant shock type
        shock_counts: Counter[str] = Counter()
        for e in events:
            shock_counts[e.get("shock_type", "Narrative shift")] += 1
        dominant_shock = shock_counts.most_common(1)[0][0]

        # Collect all evidence titles for this cluster
        all_titles: list[str] = []
        for e in events:
            all_titles.extend(e.get("evidence_titles", []))

        # Extract key phrases from evidence titles
        all_words: list[str] = []
        for title in all_titles:
            all_words.extend(_tokenize(title))
        keyword_counts = Counter(all_words)
        top_keywords = [w for w, _ in keyword_counts.most_common(5)]

        # Generate theme name at sector level
        sector_ja = _SECTOR_JA.get(sector, sector)
        pattern = _SHOCK_THEME_PATTERNS.get(dominant_shock, "{sector}セクターの構造変化")
        theme_name = pattern.format(sector=sector_ja)

        # Build description from evidence
        if all_titles:
            # Deduplicate and take top 3
            seen: set[str] = set()
            unique_titles: list[str] = []
            for t in all_titles:
                if t not in seen:
                    seen.add(t)
                    unique_titles.append(t)
            description = "; ".join(unique_titles[:3])
        else:
            description = "直接的な関連ニュース/投稿は未特定"

        # Average SIS across events in cluster
        sis_values = [e.get("sis", 0) for e in events]
        sis_avg = sum(sis_values) / len(sis_values) if sis_values else 0

        themes.append({
            "name": theme_name,
            "shock_type": dominant_shock,
            "tickers": tickers,
            "sector": sector,
            "keywords": top_keywords,
            "description": description,
            "sis_avg": round(sis_avg, 3),
            "event_count": len(events),
        })

    # Sort by average SIS
    themes.sort(key=lambda t: t["sis_avg"], reverse=True)

    for theme in themes:
        logger.info(
            "Structural theme: %s (SIS=%.3f, events=%d, tickers=%s)",
            theme["name"], theme["sis_avg"], theme["event_count"],
            ", ".join(theme["tickers"]),
        )

    return themes

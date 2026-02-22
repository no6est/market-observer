"""Media echo chamber detection and correction.

Detects when multiple media sources are echoing the same story
(reducing information diversity) and applies a correction factor
to media_evidence scores.  This prevents inflated confidence from
what is actually a single narrative repeated across outlets.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Simple English stopwords for title similarity filtering
_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "in", "on", "at", "to", "for", "of", "and", "or", "but", "with",
    "by", "from", "as", "into", "through", "during", "before", "after",
    "above", "below", "between", "about", "against", "over", "under",
    "it", "its", "this", "that", "these", "those", "he", "she", "they",
    "we", "i", "me", "my", "his", "her", "our", "their", "you", "your",
    "will", "would", "could", "should", "may", "might", "can", "shall",
    "has", "have", "had", "do", "does", "did", "not", "no", "nor",
    "so", "if", "then", "than", "too", "very", "just", "also",
    "how", "what", "when", "where", "who", "which", "why",
    "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "only", "own", "same", "new", "s", "t",
})


def _title_similarity(title_a: str, title_b: str) -> float:
    """Compute Jaccard similarity on lowercased word sets after removing stopwords.

    Args:
        title_a: First title string.
        title_b: Second title string.

    Returns:
        Float between 0.0 and 1.0.  1.0 means identical word sets,
        0.0 means no overlap at all.
    """
    words_a = {w for w in title_a.lower().split() if w not in _STOPWORDS}
    words_b = {w for w in title_b.lower().split() if w not in _STOPWORDS}

    if not words_a and not words_b:
        return 1.0
    if not words_a or not words_b:
        return 0.0

    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _find_url_references(articles: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Find cross-references between articles by checking URL appearances.

    For each article, checks whether any other article's URL appears in
    its summary or body text, indicating the article references (echoes)
    that other source.

    Args:
        articles: List of article dicts, each expected to have at least
            a ``url`` key and optionally ``summary`` and ``body`` keys.

    Returns:
        Mapping of article URL to set of other article URLs that appear
        in its summary/body.
    """
    references: dict[str, set[str]] = {}

    # Collect all article URLs
    article_urls: list[str] = []
    for article in articles:
        url = article.get("url") or ""
        if url:
            article_urls.append(url)

    for article in articles:
        url = article.get("url") or ""
        if not url:
            continue

        text = " ".join([
            article.get("summary") or "",
            article.get("body") or "",
        ]).lower()

        if not text.strip():
            references[url] = set()
            continue

        refs: set[str] = set()
        for other_url in article_urls:
            if other_url == url:
                continue
            if other_url.lower() in text:
                refs.add(other_url)

        references[url] = refs

    return references


def detect_echo_chamber(
    articles: list[dict[str, Any]],
    posts: list[dict[str, Any]],
    similarity_threshold: float = 0.7,
) -> dict[str, Any]:
    """Detect media echo chambers among articles and posts.

    Groups articles into clusters that represent the same underlying story
    by looking at shared URL references and title similarity.  Returns
    echo metrics and a correction factor for media_evidence scores.

    Args:
        articles: List of article dicts (each with ``url``, ``title``,
            ``summary``, optionally ``body`` and ``source``).
        posts: List of community post dicts (each with ``title`` and
            optionally ``source``).
        similarity_threshold: Minimum Jaccard similarity on title words
            to consider two articles as echoing the same story.
            Defaults to 0.7.

    Returns:
        Dict with keys:
        - total_sources: int total number of articles + posts considered
        - independent_sources: int number of distinct story clusters
        - echo_ratio: float 0.0-1.0 (0 = no echo, 1 = all echo)
        - echo_clusters: list of cluster dicts, each with
          representative_title, source_count, and sources list
        - correction_factor: float 0.5-1.0 multiplier for media_evidence
    """
    # Combine all sources for clustering
    all_items: list[dict[str, Any]] = []
    for a in articles:
        all_items.append({
            "title": a.get("title") or "",
            "url": a.get("url") or "",
            "source": a.get("source") or "",
            "summary": a.get("summary") or "",
            "body": a.get("body") or "",
        })
    for p in posts:
        all_items.append({
            "title": p.get("title") or "",
            "url": p.get("url") or "",
            "source": p.get("source") or "",
            "summary": "",
            "body": "",
        })

    total_sources = len(all_items)

    # Edge case: 0 or 1 sources -- no echo possible
    if total_sources <= 1:
        return {
            "total_sources": total_sources,
            "independent_sources": total_sources,
            "echo_ratio": 0.0,
            "echo_clusters": [],
            "correction_factor": 1.0,
        }

    # Build URL reference graph (articles only; posts rarely have body)
    url_refs = _find_url_references(articles)

    # Build adjacency: two items are "linked" if they share a URL ref
    # or if their titles exceed the similarity threshold.
    # We use Union-Find to cluster them.
    parent: list[int] = list(range(total_sources))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    # Index items by URL for fast lookup
    url_to_idx: dict[str, int] = {}
    for idx, item in enumerate(all_items):
        url = item["url"]
        if url:
            url_to_idx[url] = idx

    # Link via URL references
    for url, refs in url_refs.items():
        src_idx = url_to_idx.get(url)
        if src_idx is None:
            continue
        for ref_url in refs:
            tgt_idx = url_to_idx.get(ref_url)
            if tgt_idx is not None:
                union(src_idx, tgt_idx)

    # Link via title similarity
    for i in range(total_sources):
        title_i = all_items[i]["title"]
        if not title_i:
            continue
        for j in range(i + 1, total_sources):
            title_j = all_items[j]["title"]
            if not title_j:
                continue
            if _title_similarity(title_i, title_j) >= similarity_threshold:
                union(i, j)

    # Gather clusters
    clusters_map: dict[int, list[int]] = {}
    for idx in range(total_sources):
        root = find(idx)
        if root not in clusters_map:
            clusters_map[root] = []
        clusters_map[root].append(idx)

    # Build echo_clusters output
    echo_clusters: list[dict[str, Any]] = []
    for member_indices in clusters_map.values():
        # Pick the first item's title as representative
        rep_title = all_items[member_indices[0]]["title"]
        sources = [
            all_items[i]["source"] or all_items[i]["url"] or f"item_{i}"
            for i in member_indices
        ]
        echo_clusters.append({
            "representative_title": rep_title,
            "source_count": len(member_indices),
            "sources": sources,
        })

    # Sort clusters by size descending for readability
    echo_clusters.sort(key=lambda c: c["source_count"], reverse=True)

    independent_sources = len(echo_clusters)
    echo_ratio = round(1.0 - (independent_sources / total_sources), 3)
    correction_factor = round(max(0.5, independent_sources / total_sources), 3)

    logger.info(
        "Echo chamber: total=%d, independent=%d, echo_ratio=%.3f, "
        "correction=%.3f, clusters=%d",
        total_sources, independent_sources, echo_ratio,
        correction_factor, len(echo_clusters),
    )

    return {
        "total_sources": total_sources,
        "independent_sources": independent_sources,
        "echo_ratio": echo_ratio,
        "echo_clusters": echo_clusters,
        "correction_factor": correction_factor,
    }


def apply_echo_correction(
    event: dict[str, Any],
    echo_info: dict[str, Any],
) -> dict[str, Any]:
    """Apply echo chamber correction to an enriched event.

    Adjusts the ``media_evidence`` score by the echo correction factor
    and annotates the event with echo chamber metadata.

    Args:
        event: Enriched event dict.  Expected to contain a
            ``media_evidence`` key (float).
        echo_info: Dict returned by :func:`detect_echo_chamber`.

    Returns:
        The modified event dict with adjusted media_evidence and
        added echo_chamber_ratio / independent_source_count fields.
    """
    correction = echo_info.get("correction_factor", 1.0)
    original_media = event.get("media_evidence", 0.0)
    adjusted_media = round(original_media * correction, 3)

    event["media_evidence"] = adjusted_media
    event["echo_chamber_ratio"] = echo_info.get("echo_ratio", 0.0)
    event["independent_source_count"] = echo_info.get("independent_sources", 0)

    logger.debug(
        "Echo correction for %s: media_evidence %.3f -> %.3f "
        "(factor=%.3f, echo_ratio=%.3f)",
        event.get("ticker", "?"), original_media, adjusted_media,
        correction, echo_info.get("echo_ratio", 0.0),
    )

    return event

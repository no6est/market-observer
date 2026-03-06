"""Narrative Track: continuity tracking, lifecycle detection, and cooling."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# Stop words for keyword extraction (shared with theme_extractor pattern)
_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "and", "but", "or", "yet", "if", "this", "that", "these", "those",
    "it", "its", "new", "also", "just", "about", "up",
    "https", "http", "www", "com", "org",
    "stock", "market", "trading", "investor", "earnings", "shares",
    "reddit", "post", "comment", "link", "edit", "says", "said",
})

# Optional embedding support
_EMBEDDING_AVAILABLE = False
try:
    from sentence_transformers import SentenceTransformer
    _EMBEDDING_AVAILABLE = True
except ImportError:
    pass


def _tokenize(text: str) -> list[str]:
    """Extract lowercase tokens (3+ chars) excluding stop words."""
    tokens = re.findall(r"[a-zA-Z\u3040-\u9fff]{3,}", text.lower())
    return [t for t in tokens if t not in _STOP_WORDS]


def _extract_keywords_from_events(events: list[dict[str, Any]], top_n: int = 10) -> list[str]:
    """Extract top keywords from event summaries and evidence titles."""
    counter: Counter = Counter()
    for e in events:
        text_parts = []
        if e.get("summary"):
            text_parts.append(e["summary"])
        for title in e.get("evidence_titles", []):
            if title:
                text_parts.append(title)
        tokens = _tokenize(" ".join(text_parts))
        counter.update(tokens)
    return [word for word, _ in counter.most_common(top_n)]


def _extract_tickers_from_events(events: list[dict[str, Any]]) -> list[str]:
    """Extract unique tickers from events, ordered by SIS."""
    seen = {}
    for e in events:
        ticker = e.get("ticker", "")
        if ticker and ticker not in seen:
            seen[ticker] = e.get("sis", 0.0)
    return sorted(seen, key=lambda t: seen[t], reverse=True)


def generate_narrative_id(category: str, keywords: list[str]) -> str:
    """Generate deterministic narrative_id from category + sorted top keywords."""
    top5 = sorted(keywords[:5])
    keyword_hash = hashlib.md5("::".join(top5).encode()).hexdigest()[:12]
    return f"{category}::{keyword_hash}"


def _compute_jaccard(set_a: set, set_b: set) -> float:
    """Compute Jaccard similarity between two sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _compute_embedding_similarity(
    text_a: str, text_b: str, model: Any = None,
) -> float | None:
    """Compute cosine similarity using sentence-transformers (optional)."""
    if not _EMBEDDING_AVAILABLE or model is None:
        return None
    try:
        embeddings = model.encode([text_a, text_b])
        from numpy import dot
        from numpy.linalg import norm
        cos_sim = dot(embeddings[0], embeddings[1]) / (
            norm(embeddings[0]) * norm(embeddings[1])
        )
        return float(cos_sim)
    except Exception:
        return None


def match_to_existing_tracks(
    category: str,
    keywords: list[str],
    tickers: list[str],
    existing_tracks: list[dict[str, Any]],
    keyword_threshold: float = 0.5,
    ticker_threshold: float = 0.3,
    use_embeddings: bool = False,
) -> dict[str, Any] | None:
    """Find the best matching existing track for a category group.

    Returns the matched track dict or None if no match found.
    """
    best_match = None
    best_score = 0.0
    keyword_set = set(keywords)
    ticker_set = set(tickers)

    for track in existing_tracks:
        if track.get("category") != category:
            continue

        track_keywords = track.get("keywords", [])
        if isinstance(track_keywords, str):
            try:
                track_keywords = json.loads(track_keywords)
            except (json.JSONDecodeError, TypeError):
                track_keywords = []

        track_tickers = track.get("primary_tickers", [])
        if isinstance(track_tickers, str):
            try:
                track_tickers = json.loads(track_tickers)
            except (json.JSONDecodeError, TypeError):
                track_tickers = []

        kw_overlap = _compute_jaccard(keyword_set, set(track_keywords))
        tk_overlap = _compute_jaccard(ticker_set, set(track_tickers))

        # Use embeddings for ambiguous keyword overlap range
        if use_embeddings and 0.3 <= kw_overlap <= 0.6:
            kw_text = " ".join(keywords)
            track_kw_text = " ".join(track_keywords)
            emb_sim = _compute_embedding_similarity(kw_text, track_kw_text)
            if emb_sim is not None:
                kw_overlap = max(kw_overlap, emb_sim)

        composite = 0.6 * kw_overlap + 0.4 * tk_overlap

        if kw_overlap >= keyword_threshold or composite >= keyword_threshold:
            if composite > best_score:
                best_score = composite
                best_match = track

    return best_match


def determine_lifecycle_status(
    active_days: int,
    sis_history: list[float],
    avg_spp: float,
    today_event_count: int,
) -> str:
    """Determine lifecycle status based on track state.

    Returns: 'emerging', 'expanding', 'peak', 'cooling', or current status.
    """
    if today_event_count == 0:
        return "cooling"

    if active_days == 1:
        return "emerging"

    # Check SIS trend from history
    if len(sis_history) >= 3:
        recent = sis_history[-3:]
        trend_up = recent[-1] > recent[-2] > recent[0] or recent[-1] > recent[0]
    elif len(sis_history) >= 2:
        trend_up = sis_history[-1] >= sis_history[-2]
    else:
        trend_up = False

    # Peak detection: SIS near max and SPP > 0.5
    if sis_history:
        peak_sis = max(sis_history)
        current_sis = sis_history[-1]
        near_peak = current_sis >= peak_sis * 0.9 if peak_sis > 0 else False
        if near_peak and avg_spp > 0.5 and active_days >= 2:
            return "peak"

    # Expanding: trend up and active >= 2 days
    if active_days >= 2 and trend_up:
        return "expanding"

    # Default to expanding if active >= 2 but no clear trend
    if active_days >= 2:
        return "expanding"

    return "emerging"


def detect_cooling_tracks(
    active_tracks: list[dict[str, Any]],
    today_categories: set[str],
    reference_date: str,
) -> list[dict[str, Any]]:
    """Detect tracks that were active but have no events today.

    Only reports tracks with active_days >= 2 (meaningful cooling).
    """
    cooling = []
    for track in active_tracks:
        if track.get("status") == "inactive":
            continue
        category = track.get("category", "")
        active_days = track.get("active_days", 0)
        if active_days >= 2 and category not in today_categories:
            cooling.append({
                "narrative_id": track.get("narrative_id", ""),
                "category": category,
                "active_days": active_days,
                "last_seen": track.get("last_seen", ""),
                "peak_sis": track.get("peak_sis", 0.0),
                "primary_tickers": track.get("primary_tickers", []),
                "status": "cooling",
            })
    return cooling


def update_narrative_tracks(
    enriched_events: list[dict[str, Any]],
    db: Any,
    reference_date: str,
    keyword_overlap_threshold: float = 0.5,
    ticker_overlap_threshold: float = 0.3,
    cooling_inactive_days: int = 3,
    use_embeddings: bool = False,
) -> dict[str, Any]:
    """Main entry point: update narrative tracks from today's enriched events.

    Returns dict with keys:
        - active_tracks: list of updated/new tracks
        - cooling_tracks: list of cooling tracks
        - new_count: number of new tracks created
        - updated_count: number of existing tracks updated
    """
    # Group events by narrative_category
    category_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in enriched_events:
        cat = e.get("narrative_category", "")
        if cat:
            category_groups[cat].append(e)

    # Get existing active tracks from DB
    existing_tracks = db.get_active_narrative_tracks(reference_date=reference_date)

    today_categories = set(category_groups.keys())
    active_tracks = []
    new_count = 0
    updated_count = 0

    for category, events in category_groups.items():
        keywords = _extract_keywords_from_events(events)
        tickers = _extract_tickers_from_events(events)
        today_sis = max((e.get("sis", 0.0) for e in events), default=0.0)
        today_spp_values = [e.get("spp", 0.0) for e in events if e.get("spp") is not None]
        today_avg_spp = sum(today_spp_values) / len(today_spp_values) if today_spp_values else 0.0

        # Try to match existing track
        matched = match_to_existing_tracks(
            category, keywords, tickers, existing_tracks,
            keyword_threshold=keyword_overlap_threshold,
            ticker_threshold=ticker_overlap_threshold,
            use_embeddings=use_embeddings,
        )

        if matched:
            # Update existing track
            active_days = matched.get("active_days", 1) + 1
            old_sis_history = matched.get("sis_history", [])
            if isinstance(old_sis_history, str):
                try:
                    old_sis_history = json.loads(old_sis_history)
                except (json.JSONDecodeError, TypeError):
                    old_sis_history = []
            sis_history = old_sis_history + [today_sis]

            # Running average for SPP
            old_avg_spp = matched.get("avg_spp", 0.0)
            old_days = matched.get("active_days", 1)
            new_avg_spp = (old_avg_spp * old_days + today_avg_spp) / (old_days + 1)

            status = determine_lifecycle_status(
                active_days, sis_history, new_avg_spp, len(events),
            )

            track = {
                "narrative_id": matched["narrative_id"],
                "category": category,
                "keywords": keywords,
                "primary_tickers": tickers,
                "start_date": matched["start_date"],
                "last_seen": reference_date,
                "active_days": active_days,
                "peak_sis": max(matched.get("peak_sis", 0.0), today_sis),
                "avg_spp": round(new_avg_spp, 4),
                "status": status,
                "sis_history": sis_history,
            }
            db.upsert_narrative_track(track)
            active_tracks.append(track)
            updated_count += 1
        else:
            # New track
            narrative_id = generate_narrative_id(category, keywords)
            track = {
                "narrative_id": narrative_id,
                "category": category,
                "keywords": keywords,
                "primary_tickers": tickers,
                "start_date": reference_date,
                "last_seen": reference_date,
                "active_days": 1,
                "peak_sis": today_sis,
                "avg_spp": round(today_avg_spp, 4),
                "status": "emerging",
                "sis_history": [today_sis],
            }
            db.upsert_narrative_track(track)
            active_tracks.append(track)
            new_count += 1

    # Detect cooling tracks
    cooling_tracks = detect_cooling_tracks(
        existing_tracks, today_categories, reference_date,
    )
    # Update cooling tracks in DB
    for ct in cooling_tracks:
        for et in existing_tracks:
            if et.get("narrative_id") == ct["narrative_id"]:
                et_copy = dict(et)
                et_copy["status"] = "cooling"
                db.upsert_narrative_track(et_copy)
                break

    # Mark old tracks as inactive
    db.mark_tracks_inactive(reference_date, inactive_days=cooling_inactive_days)

    return {
        "active_tracks": active_tracks,
        "cooling_tracks": cooling_tracks,
        "new_count": new_count,
        "updated_count": updated_count,
    }

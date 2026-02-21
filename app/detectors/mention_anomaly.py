"""Mention surge anomaly detection in articles and community posts."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.database import Database
from app.config import DetectionConfig

logger = logging.getLogger(__name__)


# Tickers that are common English words -- require case-sensitive matching
_AMBIGUOUS_TICKERS = frozenset({
    "PATH", "NET", "AI", "ON", "IT", "ALL", "GO", "A", "NOW",
    "REAL", "CAN", "DO", "BIG", "LOW", "HAS", "ARE", "SO", "TRUE",
})


def _count_mentions(ticker: str, texts: list[str]) -> int:
    """Count occurrences of a ticker symbol in a list of text strings.

    Uses word-boundary matching to avoid partial matches. For ambiguous
    tickers (common English words like PATH, NET), uses case-sensitive
    matching to reduce false positives.
    """
    flags = 0 if ticker.upper() in _AMBIGUOUS_TICKERS else re.IGNORECASE
    pattern = re.compile(r"\b" + re.escape(ticker) + r"\b", flags)
    return sum(len(pattern.findall(text)) for text in texts)


def detect_mention_anomalies(
    db: Database,
    tickers: list[str],
    config: DetectionConfig,
) -> list[dict[str, Any]]:
    """Detect surges in ticker mentions across articles and community posts.

    Compares the mention count in the recent window (last 24h) against
    a historical baseline derived from the lookback period, using Poisson
    std approximation for z-score computation.

    Args:
        db: Database instance for querying articles, posts, and cooldowns.
        tickers: List of ticker symbols to evaluate.
        config: Detection parameters (lookback_days, z_threshold, cooldown_hours).

    Returns:
        List of anomaly dicts with summary and details fields.
    """
    anomalies: list[dict[str, Any]] = []

    # Gather recent content (last 24h) and baseline content (lookback window)
    recent_articles = db.get_recent_articles(hours=24)
    recent_posts = db.get_recent_posts(hours=24)
    baseline_articles = db.get_recent_articles(hours=config.lookback_days * 24)
    baseline_posts = db.get_recent_posts(hours=config.lookback_days * 24)

    recent_texts = [
        (a.get("title", "") or "") + " " + (a.get("summary", "") or "")
        for a in recent_articles
    ] + [
        (p.get("title", "") or "") + " " + (p.get("body", "") or "")
        for p in recent_posts
    ]

    baseline_texts = [
        (a.get("title", "") or "") + " " + (a.get("summary", "") or "")
        for a in baseline_articles
    ] + [
        (p.get("title", "") or "") + " " + (p.get("body", "") or "")
        for p in baseline_posts
    ]

    baseline_days = max(config.lookback_days, 1)

    for ticker in tickers:
        if db.has_recent_anomaly(ticker, "mention_surge", hours=config.cooldown_hours):
            logger.debug("Skipping %s mention check (cooldown active)", ticker)
            continue

        current_count = _count_mentions(ticker, recent_texts)
        baseline_count = _count_mentions(ticker, baseline_texts)

        daily_avg = baseline_count / baseline_days
        if daily_avg == 0 and current_count == 0:
            continue

        # Poisson-like std approximation with floor of 1.0
        estimated_std = max(daily_avg ** 0.5, 1.0)
        z_score = (current_count - daily_avg) / estimated_std

        if z_score >= config.z_threshold:
            score = min(abs(z_score) / 5.0, 1.0)
            mention_ratio = round(current_count / daily_avg, 1) if daily_avg > 0 else 0
            anomalies.append({
                "ticker": ticker,
                "signal_type": "mention_surge",
                "score": round(score, 4),
                "z_score": round(z_score, 4),
                "value": float(current_count),
                "mean": round(daily_avg, 4),
                "std": round(estimated_std, 4),
                "summary": f"{current_count}件の言及（通常の{mention_ratio}倍）",
                "details": {
                    "current_mentions": current_count,
                    "daily_avg_mentions": round(daily_avg, 2),
                    "baseline_total": baseline_count,
                    "baseline_days": baseline_days,
                    "recent_articles": len(recent_articles),
                    "recent_posts": len(recent_posts),
                },
            })
            logger.info(
                "Mention anomaly: %s z=%.2f current=%d avg=%.1f/day",
                ticker, z_score, current_count, daily_avg,
            )

    return anomalies

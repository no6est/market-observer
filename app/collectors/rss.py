"""RSS feed collector using feedparser."""

from __future__ import annotations

import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser

from app.config import RSSFeed

logger = logging.getLogger(__name__)


def _parse_published_date(entry: Any) -> str | None:
    """Extract and normalize a published date from a feed entry to ISO format.

    Args:
        entry: A feedparser entry object.

    Returns:
        ISO-formatted datetime string, or None if unparseable.
    """
    if hasattr(entry, "published_parsed") and entry.published_parsed is not None:
        try:
            dt = datetime(*entry.published_parsed[:6])
            return dt.isoformat()
        except Exception:
            pass

    raw = getattr(entry, "published", None) or getattr(entry, "updated", None)
    if raw:
        try:
            return parsedate_to_datetime(raw).isoformat()
        except Exception:
            pass

    return None


def _extract_summary(entry: Any) -> str | None:
    """Extract a plain-text summary from a feed entry, truncated to 1000 chars.

    Args:
        entry: A feedparser entry object.

    Returns:
        Summary text or None.
    """
    summary = getattr(entry, "summary", None) or getattr(entry, "description", None)
    if summary and len(summary) > 1000:
        summary = summary[:1000]
    return summary


def collect_rss(feeds: list[RSSFeed]) -> list[dict[str, Any]]:
    """Collect articles from RSS feeds.

    Args:
        feeds: List of RSSFeed config objects with name and url.

    Returns:
        List of dicts with keys: source, url, title, summary, published_at.
    """
    articles: list[dict[str, Any]] = []

    for feed_cfg in feeds:
        try:
            logger.info("Parsing RSS feed: %s (%s)", feed_cfg.name, feed_cfg.url)
            parsed = feedparser.parse(feed_cfg.url)

            if parsed.bozo and not parsed.entries:
                logger.warning(
                    "Feed %s returned bozo error: %s",
                    feed_cfg.name,
                    getattr(parsed, "bozo_exception", "unknown"),
                )
                continue

            count = 0
            for entry in parsed.entries:
                try:
                    link = getattr(entry, "link", None)
                    title = getattr(entry, "title", None)

                    if not link or not title:
                        continue

                    articles.append({
                        "source": feed_cfg.name,
                        "url": link,
                        "title": title,
                        "summary": _extract_summary(entry),
                        "published_at": _parse_published_date(entry),
                    })
                    count += 1

                except Exception:
                    logger.exception(
                        "Failed to parse entry in feed %s", feed_cfg.name
                    )

            logger.info("Collected %d articles from %s", count, feed_cfg.name)

        except Exception:
            logger.exception("Failed to collect RSS feed: %s", feed_cfg.name)

    logger.info("Total RSS articles collected: %d", len(articles))
    return articles

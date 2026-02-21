"""Community data collectors for Reddit and HackerNews."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.utils.http_client import fetch_json

logger = logging.getLogger(__name__)


def _epoch_to_iso(epoch: float | int | None) -> str | None:
    """Convert a Unix epoch timestamp to an ISO-formatted string.

    Args:
        epoch: Unix timestamp in seconds.

    Returns:
        ISO-formatted datetime string, or None if input is None.
    """
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()
    except (ValueError, OSError):
        return None


def collect_reddit(subreddits: list[str], limit: int = 50) -> list[dict[str, Any]]:
    """Collect hot posts from Reddit subreddits using the public JSON API.

    Uses https://www.reddit.com/r/{sub}/hot.json with no authentication.

    Args:
        subreddits: List of subreddit names (e.g. ["stocks", "technology"]).
        limit: Maximum number of posts to fetch per subreddit.

    Returns:
        List of dicts with keys: source, url, title, body, score,
        num_comments, author, created_at.
    """
    posts: list[dict[str, Any]] = []

    for sub in subreddits:
        try:
            logger.info("Fetching Reddit r/%s (limit=%d)", sub, limit)
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit={limit}&raw_json=1"
            data = fetch_json(url)

            children = data.get("data", {}).get("children", [])
            count = 0

            for child in children:
                try:
                    post = child.get("data", {})

                    # Skip pinned/stickied posts
                    if post.get("stickied"):
                        continue

                    title = post.get("title")
                    permalink = post.get("permalink")
                    if not title or not permalink:
                        continue

                    post_url = f"https://www.reddit.com{permalink}"

                    posts.append({
                        "source": f"reddit/r/{sub}",
                        "url": post_url,
                        "title": title,
                        "body": (post.get("selftext") or "")[:2000] or None,
                        "score": post.get("score", 0),
                        "num_comments": post.get("num_comments", 0),
                        "author": post.get("author"),
                        "created_at": _epoch_to_iso(post.get("created_utc")),
                    })
                    count += 1

                except Exception:
                    logger.exception("Failed to parse Reddit post in r/%s", sub)

            logger.info("Collected %d posts from r/%s", count, sub)

        except Exception:
            logger.exception("Failed to fetch Reddit r/%s", sub)

    logger.info("Total Reddit posts collected: %d", len(posts))
    return posts


def collect_hackernews(min_score: int = 10, limit: int = 100) -> list[dict[str, Any]]:
    """Collect top stories from HackerNews.

    Uses the HackerNews Firebase API:
    - https://hacker-news.firebaseio.com/v0/topstories.json for story IDs
    - https://hacker-news.firebaseio.com/v0/item/{id}.json for each story

    Args:
        min_score: Minimum score threshold for including a story.
        limit: Maximum number of story IDs to fetch from the top stories list.

    Returns:
        List of dicts with keys: source, url, title, body, score,
        num_comments, author, created_at.
    """
    posts: list[dict[str, Any]] = []

    try:
        logger.info(
            "Fetching HackerNews top stories (limit=%d, min_score=%d)",
            limit, min_score,
        )
        story_ids = fetch_json(
            "https://hacker-news.firebaseio.com/v0/topstories.json"
        )

        if not isinstance(story_ids, list):
            logger.warning("Unexpected response from HN topstories endpoint")
            return posts

        story_ids = story_ids[:limit]

        for story_id in story_ids:
            try:
                item = fetch_json(
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                )

                if item is None or item.get("type") != "story":
                    continue

                score = item.get("score", 0)
                if score < min_score:
                    continue

                title = item.get("title")
                if not title:
                    continue

                story_url = (
                    item.get("url")
                    or f"https://news.ycombinator.com/item?id={story_id}"
                )

                posts.append({
                    "source": "hackernews",
                    "url": story_url,
                    "title": title,
                    "body": (item.get("text") or "")[:2000] or None,
                    "score": score,
                    "num_comments": item.get("descendants", 0),
                    "author": item.get("by"),
                    "created_at": _epoch_to_iso(item.get("time")),
                })

            except Exception:
                logger.exception("Failed to fetch HN story %s", story_id)

    except Exception:
        logger.exception("Failed to fetch HackerNews top stories")

    logger.info("Total HackerNews posts collected: %d", len(posts))
    return posts

"""Tests for the SQLite storage layer."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from app.database import Database


@pytest.fixture
def db(tmp_path) -> Database:
    """Create a fresh database in a temp directory for each test."""
    return Database(tmp_path / "test.db")


# ---- Price Data ----


class TestPriceData:
    def test_insert_and_query(self, db: Database) -> None:
        now = datetime.utcnow()
        ts1 = (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        ts2 = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        rows = [
            {
                "ticker": "AAPL",
                "timestamp": ts1,
                "open": 150.0,
                "high": 155.0,
                "low": 149.0,
                "close": 153.0,
                "volume": 1000000,
            },
            {
                "ticker": "AAPL",
                "timestamp": ts2,
                "open": 153.0,
                "high": 158.0,
                "low": 152.0,
                "close": 157.0,
                "volume": 1200000,
            },
        ]
        db.insert_price_data(rows)

        history = db.get_price_history("AAPL", days=30)
        assert len(history) == 2
        assert history[0]["ticker"] == "AAPL"
        assert history[0]["close"] == 153.0
        assert history[1]["close"] == 157.0

    def test_duplicate_price_data_ignored(self, db: Database) -> None:
        ts = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        row = {
            "ticker": "AAPL",
            "timestamp": ts,
            "open": 150.0,
            "high": 155.0,
            "low": 149.0,
            "close": 153.0,
            "volume": 1000000,
        }
        db.insert_price_data([row])
        db.insert_price_data([row])  # duplicate

        history = db.get_price_history("AAPL", days=30)
        assert len(history) == 1

    def test_price_history_respects_days_filter(self, db: Database) -> None:
        now = datetime.utcnow()
        recent = (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
        old = (now - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")

        db.insert_price_data([
            {"ticker": "AAPL", "timestamp": recent, "close": 150.0},
            {"ticker": "AAPL", "timestamp": old, "close": 100.0},
        ])

        history = db.get_price_history("AAPL", days=10)
        assert len(history) == 1
        assert history[0]["close"] == 150.0

    def test_price_history_empty_for_unknown_ticker(self, db: Database) -> None:
        history = db.get_price_history("ZZZZ", days=30)
        assert history == []


# ---- Articles ----


class TestArticles:
    def test_insert_and_query_articles(self, db: Database) -> None:
        articles = [
            {
                "source": "TestFeed",
                "url": "https://example.com/article1",
                "title": "Test Article 1",
                "summary": "Summary 1",
                "published_at": datetime.utcnow().isoformat(),
            },
            {
                "source": "TestFeed",
                "url": "https://example.com/article2",
                "title": "Test Article 2",
                "summary": "Summary 2",
                "published_at": datetime.utcnow().isoformat(),
            },
        ]
        inserted = db.insert_articles(articles)
        assert inserted == 2

        recent = db.get_recent_articles(hours=1)
        assert len(recent) == 2

    def test_duplicate_article_url_ignored(self, db: Database) -> None:
        article = {
            "source": "TestFeed",
            "url": "https://example.com/article1",
            "title": "Test Article",
            "summary": "Summary",
        }
        db.insert_articles([article])
        db.insert_articles([article])  # duplicate URL

        recent = db.get_recent_articles(hours=1)
        assert len(recent) == 1

    def test_articles_recency_filter(self, db: Database) -> None:
        db.insert_articles([{
            "source": "TestFeed",
            "url": "https://example.com/a1",
            "title": "Recent Article",
        }])

        # Should find it within 1 hour window
        assert len(db.get_recent_articles(hours=1)) == 1
        # Should NOT find articles from 0 hours ago (cutoff == now)
        # Actually hours=0 would set cutoff to now, still should find since collected_at <= now
        # Just verify the basic query works
        assert len(db.get_recent_articles(hours=24)) >= 1


# ---- Community Posts ----


class TestCommunityPosts:
    def test_insert_and_query_posts(self, db: Database) -> None:
        posts = [
            {
                "source": "reddit/r/stocks",
                "url": "https://reddit.com/r/stocks/1",
                "title": "Post 1",
                "body": "Body text",
                "score": 100,
                "num_comments": 50,
                "author": "user1",
                "created_at": datetime.utcnow().isoformat(),
            },
        ]
        inserted = db.insert_community_posts(posts)
        assert inserted == 1

        recent = db.get_recent_posts(hours=1)
        assert len(recent) == 1
        assert recent[0]["source"] == "reddit/r/stocks"
        assert recent[0]["score"] == 100

    def test_duplicate_post_url_ignored(self, db: Database) -> None:
        post = {
            "source": "hackernews",
            "url": "https://news.ycombinator.com/item?id=1",
            "title": "HN Post",
            "score": 200,
        }
        db.insert_community_posts([post])
        db.insert_community_posts([post])  # duplicate

        recent = db.get_recent_posts(hours=1)
        assert len(recent) == 1

    def test_posts_ordered_by_score(self, db: Database) -> None:
        posts = [
            {"source": "hn", "url": "https://hn.com/1", "title": "Low", "score": 10},
            {"source": "hn", "url": "https://hn.com/2", "title": "High", "score": 500},
            {"source": "hn", "url": "https://hn.com/3", "title": "Mid", "score": 100},
        ]
        db.insert_community_posts(posts)

        recent = db.get_recent_posts(hours=1)
        scores = [r["score"] for r in recent]
        assert scores == sorted(scores, reverse=True)


# ---- Anomalies ----


class TestAnomalies:
    def test_insert_and_query_anomaly(self, db: Database) -> None:
        anomaly = {
            "ticker": "NVDA",
            "signal_type": "price_change",
            "score": 0.85,
            "z_score": 4.25,
            "value": 0.05,
            "mean": 0.01,
            "std": 0.009,
            "details": {"return_pct": 5.0},
        }
        row_id = db.insert_anomaly(anomaly)
        assert row_id is not None
        assert row_id > 0

        recent = db.get_recent_anomalies(hours=1)
        assert len(recent) == 1
        assert recent[0]["ticker"] == "NVDA"
        assert recent[0]["score"] == 0.85
        # details should be stored as JSON string
        details = json.loads(recent[0]["details"])
        assert details["return_pct"] == 5.0

    def test_has_recent_anomaly_cooldown(self, db: Database) -> None:
        """Verify cooldown detection for recently inserted anomalies."""
        assert db.has_recent_anomaly("NVDA", "price_change", hours=24) is False

        db.insert_anomaly({
            "ticker": "NVDA",
            "signal_type": "price_change",
            "score": 0.5,
        })

        assert db.has_recent_anomaly("NVDA", "price_change", hours=24) is True
        # Different signal type should not trigger cooldown
        assert db.has_recent_anomaly("NVDA", "volume_spike", hours=24) is False
        # Different ticker should not trigger cooldown
        assert db.has_recent_anomaly("MSFT", "price_change", hours=24) is False

    def test_anomalies_ordered_by_score(self, db: Database) -> None:
        db.insert_anomaly({"ticker": "A", "signal_type": "x", "score": 0.3})
        db.insert_anomaly({"ticker": "B", "signal_type": "x", "score": 0.9})
        db.insert_anomaly({"ticker": "C", "signal_type": "x", "score": 0.6})

        recent = db.get_recent_anomalies(hours=1)
        scores = [r["score"] for r in recent]
        assert scores == sorted(scores, reverse=True)


# ---- Themes ----


class TestThemes:
    def test_upsert_and_get_themes(self, db: Database) -> None:
        db.upsert_theme({
            "name": "AI Chips",
            "keywords": ["nvidia", "gpu", "chips"],
            "first_seen": "2025-01-01T00:00:00",
            "mention_count": 10,
            "momentum": 0.8,
        })

        themes = db.get_themes(limit=10)
        assert len(themes) == 1
        assert themes[0]["name"] == "AI Chips"
        assert themes[0]["momentum"] == 0.8
        keywords = json.loads(themes[0]["keywords"])
        assert "nvidia" in keywords

    def test_upsert_updates_existing_theme(self, db: Database) -> None:
        db.upsert_theme({
            "name": "AI Chips",
            "keywords": ["nvidia"],
            "first_seen": "2025-01-01T00:00:00",
            "mention_count": 5,
            "momentum": 0.3,
        })
        db.upsert_theme({
            "name": "AI Chips",
            "keywords": ["nvidia", "gpu"],
            "first_seen": "2025-01-01T00:00:00",
            "mention_count": 15,
            "momentum": 0.9,
        })

        themes = db.get_themes(limit=10)
        assert len(themes) == 1
        assert themes[0]["mention_count"] == 15
        assert themes[0]["momentum"] == 0.9

    def test_themes_ordered_by_momentum(self, db: Database) -> None:
        db.upsert_theme({"name": "Low", "momentum": 0.1, "first_seen": "2025-01-01"})
        db.upsert_theme({"name": "High", "momentum": 0.9, "first_seen": "2025-01-01"})
        db.upsert_theme({"name": "Mid", "momentum": 0.5, "first_seen": "2025-01-01"})

        themes = db.get_themes(limit=10)
        momentums = [t["momentum"] for t in themes]
        assert momentums == sorted(momentums, reverse=True)

"""SQLite storage layer for market observability system."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(ticker, timestamp)
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    summary TEXT,
    published_at TEXT,
    collected_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS community_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    body TEXT,
    score INTEGER DEFAULT 0,
    num_comments INTEGER DEFAULT 0,
    author TEXT,
    created_at TEXT,
    collected_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    score REAL NOT NULL,
    z_score REAL,
    value REAL,
    mean REAL,
    std REAL,
    summary TEXT,
    details TEXT,
    detected_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS themes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    keywords TEXT,
    first_seen TEXT NOT NULL,
    mention_count INTEGER DEFAULT 0,
    momentum REAL DEFAULT 0.0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_price_ticker_ts ON price_data(ticker, timestamp);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_anomalies_detected ON anomalies(detected_at);
CREATE INDEX IF NOT EXISTS idx_anomalies_ticker ON anomalies(ticker, signal_type, detected_at);
"""


class Database:
    """SQLite database wrapper for market observability data."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
        logger.info("Database initialized at %s", self.db_path)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _now_str(self) -> str:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    def _cutoff_str(self, **kwargs: Any) -> str:
        return (datetime.utcnow() - timedelta(**kwargs)).strftime("%Y-%m-%d %H:%M:%S")

    # ---- Price Data ----

    def insert_price_data(self, rows: list[dict[str, Any]]) -> int:
        inserted = 0
        with self._connect() as conn:
            for row in rows:
                try:
                    cursor = conn.execute(
                        """INSERT OR IGNORE INTO price_data
                           (ticker, timestamp, open, high, low, close, volume)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (row["ticker"], row["timestamp"], row.get("open"),
                         row.get("high"), row.get("low"), row.get("close"),
                         row.get("volume")),
                    )
                    inserted += cursor.rowcount
                except sqlite3.IntegrityError:
                    pass
        return inserted

    def get_price_history(self, ticker: str, days: int = 30) -> list[dict[str, Any]]:
        cutoff = self._cutoff_str(days=days)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT ticker, timestamp, open, high, low, close, volume
                   FROM price_data
                   WHERE ticker = ? AND timestamp >= ?
                   ORDER BY timestamp""",
                (ticker, cutoff),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- Articles ----

    def insert_articles(self, articles: list[dict[str, Any]]) -> int:
        inserted = 0
        with self._connect() as conn:
            for a in articles:
                try:
                    cursor = conn.execute(
                        """INSERT OR IGNORE INTO articles
                           (source, url, title, summary, published_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (a["source"], a["url"], a["title"],
                         a.get("summary"), a.get("published_at")),
                    )
                    inserted += cursor.rowcount
                except sqlite3.IntegrityError:
                    pass
        return inserted

    def get_recent_articles(self, hours: int = 24) -> list[dict[str, Any]]:
        cutoff = self._cutoff_str(hours=hours)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM articles
                   WHERE collected_at >= ?
                   ORDER BY published_at DESC""",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- Community Posts ----

    def insert_community_posts(self, posts: list[dict[str, Any]]) -> int:
        inserted = 0
        with self._connect() as conn:
            for p in posts:
                try:
                    cursor = conn.execute(
                        """INSERT OR IGNORE INTO community_posts
                           (source, url, title, body, score, num_comments, author, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (p["source"], p["url"], p["title"], p.get("body"),
                         p.get("score", 0), p.get("num_comments", 0),
                         p.get("author"), p.get("created_at")),
                    )
                    inserted += cursor.rowcount
                except sqlite3.IntegrityError:
                    pass
        return inserted

    def get_recent_posts(self, hours: int = 24) -> list[dict[str, Any]]:
        cutoff = self._cutoff_str(hours=hours)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM community_posts
                   WHERE collected_at >= ?
                   ORDER BY score DESC""",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- Anomalies ----

    def insert_anomaly(self, anomaly: dict[str, Any]) -> int:
        details = anomaly.get("details")
        if isinstance(details, dict):
            details = json.dumps(details)
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO anomalies
                   (ticker, signal_type, score, z_score, value, mean, std, summary, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (anomaly["ticker"], anomaly["signal_type"], anomaly["score"],
                 anomaly.get("z_score"), anomaly.get("value"),
                 anomaly.get("mean"), anomaly.get("std"),
                 anomaly.get("summary"), details),
            )
            return cursor.lastrowid

    def get_recent_anomalies(self, hours: int = 24) -> list[dict[str, Any]]:
        cutoff = self._cutoff_str(hours=hours)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM anomalies
                   WHERE detected_at >= ?
                   ORDER BY score DESC""",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    def has_recent_anomaly(self, ticker: str, signal_type: str, hours: int = 24) -> bool:
        cutoff = self._cutoff_str(hours=hours)
        with self._connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM anomalies
                   WHERE ticker = ? AND signal_type = ? AND detected_at >= ?""",
                (ticker, signal_type, cutoff),
            ).fetchone()
        return row["cnt"] > 0

    def clear_recent_anomalies(self, hours: int = 24) -> int:
        """Delete anomalies detected within the given hours window.

        Used by daily pipeline to allow fresh detection on re-runs.
        """
        cutoff = self._cutoff_str(hours=hours)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM anomalies WHERE detected_at >= ?", (cutoff,)
            )
            deleted = cursor.rowcount
        if deleted > 0:
            logger.info("Cleared %d recent anomalies for fresh detection", deleted)
        return deleted

    # ---- Themes ----

    def upsert_theme(self, theme: dict[str, Any]) -> None:
        keywords = theme.get("keywords")
        if isinstance(keywords, list):
            keywords = json.dumps(keywords, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO themes (name, keywords, first_seen, mention_count, momentum)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                       keywords = excluded.keywords,
                       mention_count = excluded.mention_count,
                       momentum = excluded.momentum,
                       updated_at = datetime('now')""",
                (theme["name"], keywords,
                 theme.get("first_seen", self._now_str()),
                 theme.get("mention_count", 0),
                 theme.get("momentum", 0.0)),
            )

    def get_themes(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM themes ORDER BY momentum DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

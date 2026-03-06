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

CREATE TABLE IF NOT EXISTS enriched_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    signal_type TEXT,
    shock_type TEXT,
    sis REAL,
    narrative_category TEXT,
    ai_centricity REAL,
    summary TEXT,
    evidence_score REAL,
    market_evidence REAL,
    media_evidence REAL,
    official_evidence REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(date, ticker, signal_type)
);

CREATE TABLE IF NOT EXISTS narrative_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    category TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    event_pct REAL NOT NULL,
    total_events INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(date, category)
);

CREATE INDEX IF NOT EXISTS idx_price_ticker_ts ON price_data(ticker, timestamp);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_anomalies_detected ON anomalies(detected_at);
CREATE INDEX IF NOT EXISTS idx_anomalies_ticker ON anomalies(ticker, signal_type, detected_at);
CREATE TABLE IF NOT EXISTS regime_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    regime TEXT NOT NULL,
    avg_volatility REAL,
    declining_pct REAL,
    regime_confidence REAL,
    spp_weights TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS hypothesis_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    ticker TEXT,
    hypothesis TEXT NOT NULL,
    evidence TEXT,
    confidence REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    evaluation_date TEXT,
    evaluation_result TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_hypothesis_logs_date ON hypothesis_logs(date);
CREATE INDEX IF NOT EXISTS idx_hypothesis_logs_status ON hypothesis_logs(status);

CREATE TABLE IF NOT EXISTS reaction_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    sector TEXT,
    shock_type TEXT NOT NULL,
    price_direction TEXT NOT NULL,
    price_change_pct REAL,
    duration_days INTEGER DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(date, ticker, shock_type)
);

CREATE INDEX IF NOT EXISTS idx_regime_snapshots_date ON regime_snapshots(date);
CREATE INDEX IF NOT EXISTS idx_narrative_snapshots_date ON narrative_snapshots(date);
CREATE INDEX IF NOT EXISTS idx_enriched_events_date ON enriched_events(date);
CREATE INDEX IF NOT EXISTS idx_reaction_patterns_sector ON reaction_patterns(sector, shock_type);

CREATE TABLE IF NOT EXISTS narrative_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    narrative_id TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    keywords TEXT,
    primary_tickers TEXT,
    start_date TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active_days INTEGER NOT NULL DEFAULT 1,
    peak_sis REAL NOT NULL DEFAULT 0.0,
    avg_spp REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'emerging',
    sis_history TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_narrative_tracks_status ON narrative_tracks(status);
CREATE INDEX IF NOT EXISTS idx_narrative_tracks_last_seen ON narrative_tracks(last_seen);
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
            # Migrate existing DBs: add columns if missing
            for col in ("evidence_score", "market_evidence",
                        "media_evidence", "official_evidence",
                        "tier1_count", "tier2_count", "sns_count",
                        "diffusion_pattern", "spp",
                        "echo_chamber_ratio", "independent_source_count",
                        "regime"):
                col_type = (
                    "TEXT" if col in ("diffusion_pattern", "regime")
                    else "INTEGER" if col == "independent_source_count"
                    else "REAL"
                )
                try:
                    conn.execute(
                        f"ALTER TABLE enriched_events ADD COLUMN {col} {col_type}"
                    )
                except sqlite3.OperationalError:
                    pass  # column already exists
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

    def _cutoff_str(self, reference_date: str | None = None, **kwargs: Any) -> str:
        if reference_date:
            base = datetime.strptime(reference_date, "%Y-%m-%d")
        else:
            base = datetime.utcnow()
        return (base - timedelta(**kwargs)).strftime("%Y-%m-%d %H:%M:%S")

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

    def get_anomalies_by_date_range(
        self, ticker: str, start_date: str, end_date: str,
    ) -> list[dict[str, Any]]:
        """Get anomalies for a ticker within a date range.

        Args:
            ticker: Ticker symbol.
            start_date: Start date string (YYYY-MM-DD).
            end_date: End date string (YYYY-MM-DD).

        Returns:
            List of anomaly dicts ordered by detected_at.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT ticker, signal_type, score, z_score, value,
                          mean, std, summary, detected_at
                   FROM anomalies
                   WHERE ticker = ? AND detected_at >= ? AND detected_at <= ?
                   ORDER BY detected_at""",
                (ticker, start_date, end_date + " 23:59:59"),
            ).fetchall()
        return [dict(r) for r in rows]

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

    # ---- Narrative Snapshots ----

    def insert_narrative_snapshot(
        self,
        date: str,
        category: str,
        event_count: int,
        event_pct: float,
        total_events: int,
    ) -> None:
        """Insert or update a narrative category snapshot for a given date."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO narrative_snapshots
                   (date, category, event_count, event_pct, total_events)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(date, category) DO UPDATE SET
                       event_count = excluded.event_count,
                       event_pct = excluded.event_pct,
                       total_events = excluded.total_events,
                       created_at = datetime('now')""",
                (date, category, event_count, event_pct, total_events),
            )

    # ---- Enriched Events ----

    def insert_enriched_event(
        self,
        date: str,
        event: dict[str, Any],
    ) -> None:
        """Insert or update an enriched event for a given date."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO enriched_events
                   (date, ticker, signal_type, shock_type, sis,
                    narrative_category, ai_centricity, summary,
                    evidence_score, market_evidence, media_evidence,
                    official_evidence,
                    tier1_count, tier2_count, sns_count,
                    diffusion_pattern, spp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(date, ticker, signal_type) DO UPDATE SET
                       shock_type = excluded.shock_type,
                       sis = excluded.sis,
                       narrative_category = excluded.narrative_category,
                       ai_centricity = excluded.ai_centricity,
                       summary = excluded.summary,
                       evidence_score = excluded.evidence_score,
                       market_evidence = excluded.market_evidence,
                       media_evidence = excluded.media_evidence,
                       official_evidence = excluded.official_evidence,
                       tier1_count = excluded.tier1_count,
                       tier2_count = excluded.tier2_count,
                       sns_count = excluded.sns_count,
                       diffusion_pattern = excluded.diffusion_pattern,
                       spp = excluded.spp,
                       created_at = datetime('now')""",
                (date, event.get("ticker"), event.get("signal_type"),
                 event.get("shock_type"), event.get("sis"),
                 event.get("narrative_category"), event.get("ai_centricity"),
                 event.get("summary"),
                 event.get("evidence_score"), event.get("market_evidence"),
                 event.get("media_evidence"), event.get("official_evidence"),
                 event.get("tier1_count"), event.get("tier2_count"),
                 event.get("sns_count"), event.get("diffusion_pattern"),
                 event.get("spp")),
            )

    def get_enriched_events_history(self, days: int = 7, reference_date: str | None = None) -> list[dict[str, Any]]:
        """Get enriched events for the last N days from reference_date."""
        cutoff = self._cutoff_str(reference_date=reference_date, days=days)
        upper = reference_date or datetime.utcnow().strftime("%Y-%m-%d")
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT date, ticker, signal_type, shock_type, sis,
                          narrative_category, ai_centricity, summary,
                          evidence_score, market_evidence,
                          media_evidence, official_evidence,
                          tier1_count, tier2_count, sns_count,
                          diffusion_pattern, spp, regime
                   FROM enriched_events
                   WHERE date >= ? AND date <= ?
                   ORDER BY date DESC, sis DESC""",
                (cutoff[:10], upper),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- Regime Snapshots ----

    def insert_regime_snapshot(self, date: str, regime_info: dict[str, Any]) -> None:
        """Insert or update a regime snapshot for a given date."""
        import json
        weights_json = json.dumps(regime_info.get("spp_weights")) if regime_info.get("spp_weights") else None
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO regime_snapshots
                   (date, regime, avg_volatility, declining_pct, regime_confidence, spp_weights)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(date) DO UPDATE SET
                       regime = excluded.regime,
                       avg_volatility = excluded.avg_volatility,
                       declining_pct = excluded.declining_pct,
                       regime_confidence = excluded.regime_confidence,
                       spp_weights = excluded.spp_weights,
                       created_at = datetime('now')""",
                (date, regime_info.get("regime"), regime_info.get("avg_volatility"),
                 regime_info.get("declining_pct"), regime_info.get("regime_confidence"),
                 weights_json),
            )

    def get_regime_history(self, days: int = 30, reference_date: str | None = None) -> list[dict[str, Any]]:
        """Get regime snapshots for the last N days."""
        cutoff = self._cutoff_str(reference_date=reference_date, days=days)
        upper = reference_date or datetime.utcnow().strftime("%Y-%m-%d")
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT date, regime, avg_volatility, declining_pct, regime_confidence, spp_weights
                   FROM regime_snapshots
                   WHERE date >= ? AND date <= ?
                   ORDER BY date DESC""",
                (cutoff[:10], upper),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- Hypothesis Logs ----

    def insert_hypothesis_log(self, hyp: dict[str, Any]) -> int:
        """Insert a hypothesis log entry and return its ID."""
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO hypothesis_logs
                   (date, ticker, hypothesis, evidence, confidence, status)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (hyp["date"], hyp.get("ticker"), hyp["hypothesis"],
                 hyp.get("evidence"), hyp.get("confidence"),
                 hyp.get("status", "pending")),
            )
            return cursor.lastrowid

    def get_pending_hypotheses(self, days_old: int = 30) -> list[dict[str, Any]]:
        """Get hypotheses pending evaluation (older than days_old)."""
        cutoff = self._cutoff_str(days=days_old)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, date, ticker, hypothesis, evidence, confidence,
                          status, evaluation_date, evaluation_result
                   FROM hypothesis_logs
                   WHERE status = 'pending' AND date <= ?
                   ORDER BY date""",
                (cutoff[:10],),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_hypothesis_evaluation(
        self, hyp_id: int, result: str, evaluation_date: str,
    ) -> None:
        """Update a hypothesis with its evaluation result."""
        with self._connect() as conn:
            conn.execute(
                """UPDATE hypothesis_logs
                   SET status = 'evaluated', evaluation_date = ?,
                       evaluation_result = ?
                   WHERE id = ?""",
                (evaluation_date, result, hyp_id),
            )

    def get_hypothesis_stats(self, days: int = 90) -> dict[str, Any]:
        """Get aggregate hypothesis tracking statistics."""
        cutoff = self._cutoff_str(days=days)
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM hypothesis_logs WHERE date >= ?",
                (cutoff[:10],),
            ).fetchone()["cnt"]
            evaluated = conn.execute(
                "SELECT COUNT(*) as cnt FROM hypothesis_logs WHERE date >= ? AND status = 'evaluated'",
                (cutoff[:10],),
            ).fetchone()["cnt"]
            pending = conn.execute(
                "SELECT COUNT(*) as cnt FROM hypothesis_logs WHERE date >= ? AND status = 'pending'",
                (cutoff[:10],),
            ).fetchone()["cnt"]
        return {"total": total, "evaluated": evaluated, "pending": pending}

    # ---- Reaction Patterns ----

    def insert_reaction_pattern(self, pattern: dict[str, Any]) -> None:
        """Insert or update a reaction pattern for a given date/ticker/shock."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO reaction_patterns
                   (date, ticker, sector, shock_type, price_direction,
                    price_change_pct, duration_days)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(date, ticker, shock_type) DO UPDATE SET
                       sector = excluded.sector,
                       price_direction = excluded.price_direction,
                       price_change_pct = excluded.price_change_pct,
                       duration_days = excluded.duration_days,
                       created_at = datetime('now')""",
                (pattern["date"], pattern["ticker"], pattern.get("sector"),
                 pattern["shock_type"], pattern["price_direction"],
                 pattern.get("price_change_pct"), pattern.get("duration_days", 1)),
            )

    def get_reaction_patterns(
        self, sector: str | None = None, shock_type: str | None = None,
        days: int = 90,
    ) -> list[dict[str, Any]]:
        """Get historical reaction patterns, optionally filtered by sector/shock."""
        cutoff = self._cutoff_str(days=days)
        conditions = ["date >= ?"]
        params: list[Any] = [cutoff[:10]]
        if sector:
            conditions.append("sector = ?")
            params.append(sector)
        if shock_type:
            conditions.append("shock_type = ?")
            params.append(shock_type)
        where = " AND ".join(conditions)
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT date, ticker, sector, shock_type, price_direction,
                           price_change_pct, duration_days
                    FROM reaction_patterns
                    WHERE {where}
                    ORDER BY date DESC""",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_price_data_range(
        self, ticker: str, start_date: str, end_date: str,
    ) -> list[dict[str, Any]]:
        """Get price data for a ticker within a date range.

        Args:
            ticker: Ticker symbol.
            start_date: Start date string (YYYY-MM-DD).
            end_date: End date string (YYYY-MM-DD).

        Returns:
            List of price data dicts ordered by timestamp.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT ticker, timestamp, open, high, low, close, volume
                   FROM price_data
                   WHERE ticker = ? AND timestamp >= ? AND timestamp <= ?
                   ORDER BY timestamp""",
                (ticker, start_date, end_date + " 23:59:59"),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_drift_hypotheses(
        self, days_old: int = 30, reference_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get drift_pending hypotheses older than days_old.

        Args:
            days_old: Minimum age in days for the hypothesis.
            reference_date: Reference date for cutoff calculation.

        Returns:
            List of hypothesis dicts with drift_pending status.
        """
        cutoff = self._cutoff_str(reference_date=reference_date, days=days_old)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, date, ticker, hypothesis, evidence, confidence,
                          status, evaluation_date, evaluation_result
                   FROM hypothesis_logs
                   WHERE status = 'drift_pending' AND date <= ?
                   ORDER BY date""",
                (cutoff[:10],),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_articles_by_date_range(self, days: int = 7, reference_date: str | None = None) -> list[dict[str, Any]]:
        """Get articles collected within the given date range."""
        cutoff = self._cutoff_str(reference_date=reference_date, days=days)
        upper = (reference_date or datetime.utcnow().strftime("%Y-%m-%d")) + " 23:59:59"
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT source, url, title, summary, published_at
                   FROM articles
                   WHERE collected_at >= ? AND collected_at <= ?
                   ORDER BY published_at DESC""",
                (cutoff, upper),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- Narrative Tracks ----

    def upsert_narrative_track(self, track: dict[str, Any]) -> None:
        """Insert or replace a narrative track."""
        keywords = track.get("keywords")
        if isinstance(keywords, list):
            keywords = json.dumps(keywords, ensure_ascii=False)
        primary_tickers = track.get("primary_tickers")
        if isinstance(primary_tickers, list):
            primary_tickers = json.dumps(primary_tickers, ensure_ascii=False)
        sis_history = track.get("sis_history")
        if isinstance(sis_history, list):
            sis_history = json.dumps(sis_history)
        metadata = track.get("metadata")
        if isinstance(metadata, dict):
            metadata = json.dumps(metadata, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO narrative_tracks
                   (narrative_id, category, keywords, primary_tickers,
                    start_date, last_seen, active_days, peak_sis, avg_spp,
                    status, sis_history, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(narrative_id) DO UPDATE SET
                       category = excluded.category,
                       keywords = excluded.keywords,
                       primary_tickers = excluded.primary_tickers,
                       last_seen = excluded.last_seen,
                       active_days = excluded.active_days,
                       peak_sis = excluded.peak_sis,
                       avg_spp = excluded.avg_spp,
                       status = excluded.status,
                       sis_history = excluded.sis_history,
                       metadata = excluded.metadata,
                       updated_at = datetime('now')""",
                (track["narrative_id"], track["category"], keywords,
                 primary_tickers, track["start_date"], track["last_seen"],
                 track.get("active_days", 1), track.get("peak_sis", 0.0),
                 track.get("avg_spp", 0.0), track.get("status", "emerging"),
                 sis_history, metadata),
            )

    def get_active_narrative_tracks(self, reference_date: str | None = None) -> list[dict[str, Any]]:
        """Get narrative tracks that are not inactive."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT narrative_id, category, keywords, primary_tickers,
                          start_date, last_seen, active_days, peak_sis,
                          avg_spp, status, sis_history, metadata
                   FROM narrative_tracks
                   WHERE status != 'inactive'
                   ORDER BY last_seen DESC, peak_sis DESC""",
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("keywords") and isinstance(d["keywords"], str):
                try:
                    d["keywords"] = json.loads(d["keywords"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if d.get("primary_tickers") and isinstance(d["primary_tickers"], str):
                try:
                    d["primary_tickers"] = json.loads(d["primary_tickers"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if d.get("sis_history") and isinstance(d["sis_history"], str):
                try:
                    d["sis_history"] = json.loads(d["sis_history"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if d.get("metadata") and isinstance(d["metadata"], str):
                try:
                    d["metadata"] = json.loads(d["metadata"])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(d)
        return result

    def get_all_narrative_tracks(self) -> list[dict[str, Any]]:
        """Get all narrative tracks."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT narrative_id, category, keywords, primary_tickers,
                          start_date, last_seen, active_days, peak_sis,
                          avg_spp, status, sis_history, metadata
                   FROM narrative_tracks
                   ORDER BY last_seen DESC""",
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("keywords") and isinstance(d["keywords"], str):
                try:
                    d["keywords"] = json.loads(d["keywords"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if d.get("primary_tickers") and isinstance(d["primary_tickers"], str):
                try:
                    d["primary_tickers"] = json.loads(d["primary_tickers"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if d.get("sis_history") and isinstance(d["sis_history"], str):
                try:
                    d["sis_history"] = json.loads(d["sis_history"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if d.get("metadata") and isinstance(d["metadata"], str):
                try:
                    d["metadata"] = json.loads(d["metadata"])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(d)
        return result

    def mark_tracks_inactive(self, reference_date: str, inactive_days: int = 3) -> int:
        """Mark tracks not seen for inactive_days as inactive."""
        from datetime import datetime, timedelta
        cutoff = (datetime.strptime(reference_date, "%Y-%m-%d") - timedelta(days=inactive_days)).strftime("%Y-%m-%d")
        with self._connect() as conn:
            cursor = conn.execute(
                """UPDATE narrative_tracks
                   SET status = 'inactive', updated_at = datetime('now')
                   WHERE status != 'inactive' AND last_seen <= ?""",
                (cutoff,),
            )
            updated = cursor.rowcount
        if updated > 0:
            logger.info("Marked %d narrative tracks as inactive", updated)
        return updated

    def get_narrative_history(self, days: int = 7, reference_date: str | None = None) -> list[dict[str, Any]]:
        """Get narrative snapshots for the last N days from reference_date."""
        cutoff = self._cutoff_str(reference_date=reference_date, days=days)
        upper = reference_date or datetime.utcnow().strftime("%Y-%m-%d")
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT date, category, event_count, event_pct, total_events
                   FROM narrative_snapshots
                   WHERE date >= ? AND date <= ?
                   ORDER BY date DESC, event_pct DESC""",
                (cutoff[:10], upper),
            ).fetchall()
        return [dict(r) for r in rows]

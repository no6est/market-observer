"""Tests for self-verification prediction log and verdict system."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

import pytest

from app.enrichers.self_verification import (
    _compute_verdict,
    _median,
    compute_verification_summary,
    save_prediction_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _TempDB:
    """Lightweight DB wrapper that mirrors the interface expected by
    save_prediction_log (``._connect()`` context manager returning a
    sqlite3 Connection with row_factory)."""

    def __init__(self, db_path: Path) -> None:
        self._path = str(db_path)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db(tmp_path: Path) -> _TempDB:
    """Create a temporary SQLite database."""
    return _TempDB(tmp_path / "test.db")


@pytest.fixture
def sample_narrative_index() -> dict[str, Any]:
    return {
        "ai_ratio": 0.65,
        "category_distribution": {"AI/LLM": 3, "Energy": 1},
    }


@pytest.fixture
def sample_top_events() -> list[dict[str, Any]]:
    return [
        {"ticker": "NVDA", "evidence_score": 0.7},
        {"ticker": "MSFT", "evidence_score": 0.5},
        {"ticker": "GOOGL", "evidence_score": 0.3},
    ]


# ---------------------------------------------------------------------------
# save_prediction_log
# ---------------------------------------------------------------------------


class TestSavePredictionLog:
    def test_saves_to_db(
        self,
        temp_db: _TempDB,
        sample_narrative_index: dict,
        sample_top_events: list,
    ) -> None:
        """Create temp sqlite db, call save, verify row exists."""
        save_prediction_log(
            db=temp_db,
            date="2026-02-22",
            narrative_index=sample_narrative_index,
            overheat_alert={"level": "high"},
            top_events=sample_top_events,
        )

        with temp_db._connect() as conn:
            row = conn.execute(
                "SELECT * FROM prediction_logs WHERE date = ?",
                ("2026-02-22",),
            ).fetchone()

        assert row is not None
        assert row["date"] == "2026-02-22"
        assert row["ai_ratio"] == pytest.approx(0.65)
        assert row["overheat_triggered"] == 1

    def test_overwrites_same_date(
        self,
        temp_db: _TempDB,
        sample_narrative_index: dict,
        sample_top_events: list,
    ) -> None:
        """Call twice with the same date -> only one row (INSERT OR REPLACE)."""
        for _ in range(2):
            save_prediction_log(
                db=temp_db,
                date="2026-02-22",
                narrative_index=sample_narrative_index,
                overheat_alert=None,
                top_events=sample_top_events,
            )

        with temp_db._connect() as conn:
            rows = conn.execute(
                "SELECT COUNT(*) as cnt FROM prediction_logs WHERE date = ?",
                ("2026-02-22",),
            ).fetchone()

        assert rows["cnt"] == 1


# ---------------------------------------------------------------------------
# _compute_verdict
# ---------------------------------------------------------------------------


class TestComputeVerdict:
    def test_tp(self) -> None:
        """overheat=True, ai_cont=False, price_sust=False -> TP."""
        verdict, details = _compute_verdict(
            overheat_triggered=True,
            ai_events_continued=False,
            price_trend_sustained=False,
        )
        assert verdict == "TP"
        assert "correctly warned" in details.lower() or "justified" in details.lower()

    def test_fp_real(self) -> None:
        """overheat=True, ai_cont=True, price_sust=True -> FP."""
        verdict, details = _compute_verdict(
            overheat_triggered=True,
            ai_events_continued=True,
            price_trend_sustained=True,
        )
        assert verdict == "FP"
        assert "false alarm" in details.lower() or "false positive" in details.lower()

    def test_fn(self) -> None:
        """overheat=False, ai_cont=True, price_sust=False -> FN."""
        verdict, details = _compute_verdict(
            overheat_triggered=False,
            ai_events_continued=True,
            price_trend_sustained=False,
        )
        assert verdict == "FN"
        assert "missed" in details.lower() or "should have" in details.lower()

    def test_tn(self) -> None:
        """overheat=False, ai_cont=False, price_sust=False -> TN."""
        verdict, details = _compute_verdict(
            overheat_triggered=False,
            ai_events_continued=False,
            price_trend_sustained=False,
        )
        assert verdict == "TN"
        assert "normal" in details.lower()


# ---------------------------------------------------------------------------
# _median
# ---------------------------------------------------------------------------


class TestMedian:
    def test_odd(self) -> None:
        """[1, 2, 3] -> 2."""
        assert _median([1, 2, 3]) == 2

    def test_even(self) -> None:
        """[1, 2, 3, 4] -> 2.5."""
        assert _median([1, 2, 3, 4]) == 2.5

    def test_empty(self) -> None:
        """[] -> 0.0."""
        assert _median([]) == 0.0


# ---------------------------------------------------------------------------
# compute_verification_summary
# ---------------------------------------------------------------------------


class TestComputeVerificationSummary:
    def test_empty_db(self, temp_db: _TempDB) -> None:
        """No prediction logs in the database -> total=0."""
        # Ensure the table exists (but has no rows)
        with temp_db._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS prediction_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    ai_ratio REAL,
                    median_evidence_score REAL,
                    overheat_triggered INTEGER NOT NULL DEFAULT 0,
                    top_tickers TEXT,
                    category_snapshot TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )

        summary = compute_verification_summary(temp_db, days=7)

        assert summary["total_predictions"] == 0
        assert summary["tp"] == 0
        assert summary["fp"] == 0
        assert summary["tn"] == 0
        assert summary["fn"] == 0
        assert summary["precision"] is None
        assert summary["recall"] is None

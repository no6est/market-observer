"""Tests for narrative history archive."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from app.enrichers.narrative_archive import (
    archive_hypotheses,
    compute_narrative_lifecycle,
    evaluate_pending_hypotheses,
    generate_monthly_summary,
)


class TestArchiveHypotheses:
    def test_archives_hypotheses_with_ticker(self) -> None:
        """Hypotheses with explicit ticker field are archived correctly."""
        db = MagicMock()
        db.insert_hypothesis_log.side_effect = [1, 2]
        hypotheses = [
            {"ticker": "NVDA", "hypothesis": "GPU demand surge", "confidence": 0.8},
            {"ticker": "MSFT", "hypothesis": "AI pivot", "evidence": "news"},
        ]
        ids = archive_hypotheses(db, "2025-01-15", hypotheses)
        assert ids == [1, 2]
        assert db.insert_hypothesis_log.call_count == 2
        # Verify the first call's arguments
        first_call = db.insert_hypothesis_log.call_args_list[0][0][0]
        assert first_call["date"] == "2025-01-15"
        assert first_call["ticker"] == "NVDA"
        assert first_call["hypothesis"] == "GPU demand surge"
        assert first_call["confidence"] == 0.8
        assert first_call["status"] == "pending"

    def test_extracts_ticker_from_text(self) -> None:
        """When ticker field is missing, extract from hypothesis text."""
        db = MagicMock()
        db.insert_hypothesis_log.return_value = 10
        hypotheses = [
            {"hypothesis": "NVDA shows strong momentum in GPU market"},
        ]
        ids = archive_hypotheses(db, "2025-01-15", hypotheses)
        assert ids == [10]
        logged = db.insert_hypothesis_log.call_args[0][0]
        assert logged["ticker"] == "NVDA"

    def test_handles_db_error_gracefully(self) -> None:
        """DB errors are caught, other hypotheses still processed."""
        db = MagicMock()
        db.insert_hypothesis_log.side_effect = [Exception("DB error"), 5]
        hypotheses = [
            {"hypothesis": "Failing one"},
            {"hypothesis": "Succeeding one"},
        ]
        ids = archive_hypotheses(db, "2025-01-15", hypotheses)
        assert ids == [5]

    def test_empty_hypotheses_returns_empty(self) -> None:
        """Empty input returns empty list."""
        db = MagicMock()
        ids = archive_hypotheses(db, "2025-01-15", [])
        assert ids == []
        db.insert_hypothesis_log.assert_not_called()


class TestEvaluatePendingHypotheses:
    def test_evaluates_confirmed(self) -> None:
        """Ticker still in recent events → confirmed."""
        db = MagicMock()
        db.get_pending_hypotheses.return_value = [
            {"id": 1, "date": "2024-12-15", "ticker": "NVDA",
             "hypothesis": "GPU surge", "confidence": 0.8},
        ]
        db.get_enriched_events_history.return_value = [
            {"ticker": "NVDA", "date": "2025-01-15"},
            {"ticker": "MSFT", "date": "2025-01-15"},
        ]
        results = evaluate_pending_hypotheses(db, "2025-01-15")
        assert len(results) == 1
        assert results[0]["evaluation"] == "confirmed"
        db.update_hypothesis_evaluation.assert_called_once_with(1, "confirmed", "2025-01-15")

    def test_evaluates_expired(self) -> None:
        """Ticker not in recent events → expired."""
        db = MagicMock()
        db.get_pending_hypotheses.return_value = [
            {"id": 2, "date": "2024-12-15", "ticker": "XOM",
             "hypothesis": "Oil surge", "confidence": 0.6},
        ]
        db.get_enriched_events_history.return_value = [
            {"ticker": "NVDA", "date": "2025-01-15"},
        ]
        results = evaluate_pending_hypotheses(db, "2025-01-15")
        assert len(results) == 1
        assert results[0]["evaluation"] == "expired"

    def test_evaluates_inconclusive_no_ticker(self) -> None:
        """Hypothesis without ticker → inconclusive."""
        db = MagicMock()
        db.get_pending_hypotheses.return_value = [
            {"id": 3, "date": "2024-12-15", "ticker": None,
             "hypothesis": "Market shift", "confidence": 0.5},
        ]
        db.get_enriched_events_history.return_value = []
        results = evaluate_pending_hypotheses(db, "2025-01-15")
        assert len(results) == 1
        assert results[0]["evaluation"] == "inconclusive"

    def test_no_pending_returns_empty(self) -> None:
        """No pending hypotheses → empty results."""
        db = MagicMock()
        db.get_pending_hypotheses.return_value = []
        results = evaluate_pending_hypotheses(db, "2025-01-15")
        assert results == []


class TestComputeNarrativeLifecycle:
    def test_lifecycle_statistics(self) -> None:
        """Compute active days, peak, convergence for categories."""
        db = MagicMock()
        # 5 days of data: AI dominates first 3 days, then drops
        db.get_narrative_history.return_value = [
            {"date": "2025-01-11", "category": "AI/LLM/自動化", "event_pct": 0.80},
            {"date": "2025-01-11", "category": "金融/金利/流動性", "event_pct": 0.20},
            {"date": "2025-01-12", "category": "AI/LLM/自動化", "event_pct": 0.70},
            {"date": "2025-01-12", "category": "金融/金利/流動性", "event_pct": 0.30},
            {"date": "2025-01-13", "category": "AI/LLM/自動化", "event_pct": 0.60},
            {"date": "2025-01-13", "category": "金融/金利/流動性", "event_pct": 0.40},
            {"date": "2025-01-14", "category": "AI/LLM/自動化", "event_pct": 0.05},
            {"date": "2025-01-14", "category": "金融/金利/流動性", "event_pct": 0.95},
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.03},
            {"date": "2025-01-15", "category": "金融/金利/流動性", "event_pct": 0.97},
        ]
        result = compute_narrative_lifecycle(db, days=90)
        assert result["period_days"] == 5
        cats = result["categories"]
        assert "AI/LLM/自動化" in cats
        ai = cats["AI/LLM/自動化"]
        # AI was above 10% for 3 days (0.80, 0.70, 0.60)
        assert ai["active_days"] == 3
        assert ai["peak_pct"] == 0.80
        assert ai["convergence_days"] > 0

    def test_empty_history(self) -> None:
        """No history data → empty result."""
        db = MagicMock()
        db.get_narrative_history.return_value = []
        result = compute_narrative_lifecycle(db)
        assert result["categories"] == {}
        assert result["period_days"] == 0


class TestGenerateMonthlySummary:
    def test_monthly_summary_structure(self) -> None:
        """Monthly summary has expected keys and values."""
        db = MagicMock()
        db.get_narrative_history.return_value = [
            {"date": "2025-01-11", "category": "AI/LLM/自動化", "event_pct": 0.70},
            {"date": "2025-01-11", "category": "金融/金利/流動性", "event_pct": 0.30},
            {"date": "2025-01-12", "category": "AI/LLM/自動化", "event_pct": 0.60},
            {"date": "2025-01-12", "category": "金融/金利/流動性", "event_pct": 0.40},
        ]
        db.get_hypothesis_stats.return_value = {
            "total": 10, "evaluated": 3, "pending": 7,
        }
        result = generate_monthly_summary(db, "2025-01-15")
        assert "period_days" in result
        assert "narrative_lifecycle" in result
        assert "avg_lifespan_days" in result
        assert "avg_convergence_days" in result
        assert "persistence_distribution" in result
        assert "hypothesis_stats" in result
        assert result["hypothesis_stats"]["total"] == 10

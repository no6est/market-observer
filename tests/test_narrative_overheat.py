"""Tests for narrative overheat detector."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.enrichers.narrative_overheat import (
    _count_ai_dominant_streak,
    detect_narrative_overheat,
)


@pytest.fixture
def ai_heavy_events() -> list[dict]:
    """AI events with LOW evidence_score (poorly supported)."""
    return [
        {"ticker": "NVDA", "ai_centricity": 0.9, "signal_type": "mention_surge", "evidence_score": 0.1},
        {"ticker": "MSFT", "ai_centricity": 0.8, "signal_type": "mention_surge", "evidence_score": 0.15},
        {"ticker": "GOOGL", "ai_centricity": 0.7, "signal_type": "mention_surge", "evidence_score": 0.2},
    ]


@pytest.fixture
def well_supported_events() -> list[dict]:
    """AI events with HIGH evidence_score (well supported by market/media)."""
    return [
        {"ticker": "NVDA", "ai_centricity": 0.9, "signal_type": "price_change", "evidence_score": 0.8},
        {"ticker": "MSFT", "ai_centricity": 0.8, "signal_type": "price_change", "evidence_score": 0.7},
        {"ticker": "GOOGL", "ai_centricity": 0.7, "signal_type": "volume_spike", "evidence_score": 0.6},
    ]


@pytest.fixture
def ai_heavy_index_with_history() -> dict:
    """AI ratio surges above 7-day average."""
    return {
        "ai_ratio": 0.75,
        "category_distribution": {"AI/LLM/自動化": {"count": 3, "pct": 0.75}},
        "top1_concentration": 0.75,
        "historical_avg": {"AI/LLM/自動化": 0.35},
        "warning_flags": [],
    }


@pytest.fixture
def ai_heavy_index_no_history() -> dict:
    """High AI ratio with no historical data (fallback mode)."""
    return {
        "ai_ratio": 0.75,
        "category_distribution": {"AI/LLM/自動化": {"count": 3, "pct": 0.75}},
        "top1_concentration": 0.75,
        "historical_avg": None,
        "warning_flags": [],
    }


@pytest.fixture
def balanced_index() -> dict:
    return {
        "ai_ratio": 0.25,
        "category_distribution": {},
        "top1_concentration": 0.25,
        "historical_avg": {"AI/LLM/自動化": 0.20},
        "warning_flags": [],
    }


def _make_db_with_streak(days: int) -> MagicMock:
    """Create a mock DB with N days of AI-dominant history."""
    db = MagicMock()
    history = []
    for i in range(days):
        date = f"2025-01-{15-i:02d}"
        history.append({"date": date, "category": "AI/LLM/自動化", "event_pct": 0.6})
        history.append({"date": date, "category": "規制/政策/地政学", "event_pct": 0.2})
        history.append({"date": date, "category": "その他", "event_pct": 0.2})
    db.get_narrative_history.return_value = history
    return db


class TestDetectNarrativeOverheat:
    def test_all_conditions_met(self, ai_heavy_events, ai_heavy_index_with_history) -> None:
        """Alert fires: AI surge + weak evidence + streak."""
        db = _make_db_with_streak(5)
        alert = detect_narrative_overheat(ai_heavy_events, ai_heavy_index_with_history, db)
        assert alert is not None
        assert alert["severity"] == "warning"
        assert "過熱" in alert["message"]
        assert alert["conditions"]["ai_ratio"] == 0.75
        assert alert["conditions"]["median_evidence_score"] < 0.3

    def test_no_alert_when_ai_ratio_low(self, ai_heavy_events, balanced_index) -> None:
        """No alert when AI ratio is not significantly above average."""
        db = _make_db_with_streak(5)
        alert = detect_narrative_overheat(ai_heavy_events, balanced_index, db)
        assert alert is None

    def test_no_alert_when_evidence_strong(
        self, well_supported_events, ai_heavy_index_with_history
    ) -> None:
        """No alert when AI events have strong evidence backing."""
        db = _make_db_with_streak(5)
        alert = detect_narrative_overheat(
            well_supported_events, ai_heavy_index_with_history, db
        )
        assert alert is None

    def test_no_alert_when_short_streak(
        self, ai_heavy_events, ai_heavy_index_with_history
    ) -> None:
        db = _make_db_with_streak(2)
        alert = detect_narrative_overheat(ai_heavy_events, ai_heavy_index_with_history, db)
        assert alert is None

    def test_no_db_no_streak(self, ai_heavy_events, ai_heavy_index_with_history) -> None:
        alert = detect_narrative_overheat(
            ai_heavy_events, ai_heavy_index_with_history, db=None
        )
        assert alert is None

    def test_alert_has_recommendation(
        self, ai_heavy_events, ai_heavy_index_with_history
    ) -> None:
        db = _make_db_with_streak(3)
        alert = detect_narrative_overheat(ai_heavy_events, ai_heavy_index_with_history, db)
        assert alert is not None
        assert "recommendation" in alert
        assert len(alert["recommendation"]) > 0

    def test_fallback_to_absolute_threshold(
        self, ai_heavy_events, ai_heavy_index_no_history
    ) -> None:
        """When no historical average, falls back to absolute ai_pct_threshold."""
        db = _make_db_with_streak(5)
        alert = detect_narrative_overheat(ai_heavy_events, ai_heavy_index_no_history, db)
        assert alert is not None
        assert alert["conditions"]["historical_ai_avg"] is None

    def test_conditions_include_new_fields(
        self, ai_heavy_events, ai_heavy_index_with_history
    ) -> None:
        db = _make_db_with_streak(5)
        alert = detect_narrative_overheat(ai_heavy_events, ai_heavy_index_with_history, db)
        assert alert is not None
        assert "median_evidence_score" in alert["conditions"]
        assert "historical_ai_avg" in alert["conditions"]
        assert "consecutive_ai_dominant_days" in alert["conditions"]


class TestCountAiDominantStreak:
    def test_full_streak(self) -> None:
        history = [
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.6},
            {"date": "2025-01-15", "category": "その他", "event_pct": 0.4},
            {"date": "2025-01-14", "category": "AI/LLM/自動化", "event_pct": 0.55},
            {"date": "2025-01-14", "category": "その他", "event_pct": 0.45},
            {"date": "2025-01-13", "category": "AI/LLM/自動化", "event_pct": 0.7},
            {"date": "2025-01-13", "category": "その他", "event_pct": 0.3},
        ]
        assert _count_ai_dominant_streak(history) == 3

    def test_broken_streak(self) -> None:
        history = [
            {"date": "2025-01-15", "category": "AI/LLM/自動化", "event_pct": 0.6},
            {"date": "2025-01-15", "category": "その他", "event_pct": 0.4},
            {"date": "2025-01-14", "category": "規制/政策/地政学", "event_pct": 0.7},
            {"date": "2025-01-14", "category": "AI/LLM/自動化", "event_pct": 0.3},
        ]
        assert _count_ai_dominant_streak(history) == 1

    def test_empty_history(self) -> None:
        assert _count_ai_dominant_streak([]) == 0

"""Tests for propagation direction estimation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.enrichers.propagation import (
    estimate_propagation_direction,
    find_propagation,
)


class TestEstimatePropagationDirection:
    def test_positive_direction(self) -> None:
        """Dominant positive reactions → positive direction."""
        db = MagicMock()
        db.get_reaction_patterns.return_value = [
            {"price_direction": "positive"} for _ in range(7)
        ] + [
            {"price_direction": "negative"} for _ in range(3)
        ]
        result = estimate_propagation_direction(db, "AI_Infrastructure", "Tech shock")
        assert result["direction"] == "positive"
        assert result["confidence"] > 0
        assert result["sample_count"] == 10

    def test_negative_direction(self) -> None:
        """Dominant negative reactions → negative direction."""
        db = MagicMock()
        db.get_reaction_patterns.return_value = [
            {"price_direction": "negative"} for _ in range(8)
        ] + [
            {"price_direction": "positive"} for _ in range(2)
        ]
        result = estimate_propagation_direction(db, "Financial", "Regulation shock")
        assert result["direction"] == "negative"

    def test_mixed_direction(self) -> None:
        """Balanced reactions → mixed direction."""
        db = MagicMock()
        db.get_reaction_patterns.return_value = [
            {"price_direction": "positive"},
            {"price_direction": "negative"},
            {"price_direction": "positive"},
            {"price_direction": "negative"},
            {"price_direction": "neutral"},
        ]
        result = estimate_propagation_direction(db, "Cloud_Security", "Tech shock")
        assert result["direction"] == "mixed"

    def test_unknown_when_no_data(self) -> None:
        """No historical data → unknown direction."""
        db = MagicMock()
        db.get_reaction_patterns.return_value = []
        result = estimate_propagation_direction(db, "Energy", "Regulation shock")
        assert result["direction"] == "unknown"
        assert result["confidence"] == 0.0

    def test_unknown_when_db_none(self) -> None:
        """No DB → unknown direction."""
        result = estimate_propagation_direction(None, "Energy", "Regulation shock")
        assert result["direction"] == "unknown"

    def test_confidence_scales_with_samples(self) -> None:
        """Confidence increases with more samples."""
        db = MagicMock()
        db.get_reaction_patterns.return_value = [
            {"price_direction": "positive"} for _ in range(3)
        ]
        result_small = estimate_propagation_direction(db, "S", "T")
        db.get_reaction_patterns.return_value = [
            {"price_direction": "positive"} for _ in range(10)
        ]
        result_large = estimate_propagation_direction(db, "S", "T")
        assert result_large["confidence"] >= result_small["confidence"]


class TestFindPropagationWithDirection:
    def test_propagation_includes_direction(self) -> None:
        """Propagation results include direction fields."""
        db = MagicMock()
        db.get_reaction_patterns.return_value = [
            {"price_direction": "positive"} for _ in range(5)
        ]
        anomalies = [
            {"ticker": "NVDA", "signal_type": "price_change",
             "score": 0.8, "shock_type": "Tech shock"},
        ]
        sector_map = {"AI_Infrastructure": ["NVDA", "AMD", "SMCI"]}
        result = find_propagation(anomalies, sector_map, db=db)
        assert len(result) == 1
        assert "direction" in result[0]
        assert "direction_confidence" in result[0]
        assert "direction_sample_count" in result[0]

    def test_propagation_without_db_has_unknown_direction(self) -> None:
        """Without DB, direction is unknown."""
        anomalies = [
            {"ticker": "NVDA", "signal_type": "price_change",
             "score": 0.8, "shock_type": "Tech shock"},
        ]
        sector_map = {"AI_Infrastructure": ["NVDA", "AMD"]}
        result = find_propagation(anomalies, sector_map)
        assert len(result) == 1
        assert result[0]["direction"] == "unknown"

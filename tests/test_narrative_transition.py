"""Tests for narrative transition detection and outlook."""

import pytest

from app.enrichers.narrative_transition import (
    detect_narrative_transitions,
    build_transition_outlook,
)


def _momentum(category, momentum_val, today_count=5, yesterday_count=5):
    return {
        "category": category,
        "momentum": momentum_val,
        "today_count": today_count,
        "yesterday_count": yesterday_count,
        "classification": "安定",
    }


class TestDetectNarrativeTransitions:
    def test_basic_pair_detection(self):
        momentum = [
            _momentum("AI/LLM", -0.5),
            _momentum("エネルギー", 0.5),
        ]
        result = detect_narrative_transitions(momentum)
        assert len(result) == 1
        assert result[0]["from_category"] == "AI/LLM"
        assert result[0]["to_category"] == "エネルギー"
        assert result[0]["from_momentum"] == -0.5
        assert result[0]["to_momentum"] == 0.5

    def test_multiple_pairs(self):
        momentum = [
            _momentum("AI/LLM", -0.5),
            _momentum("規制", -0.4),
            _momentum("エネルギー", 0.5),
            _momentum("金融", 0.8),
        ]
        result = detect_narrative_transitions(momentum)
        assert len(result) == 4  # 2 declining × 2 rising

    def test_no_transitions_all_stable(self):
        momentum = [
            _momentum("AI/LLM", 0.0),
            _momentum("エネルギー", 0.1),
            _momentum("金融", -0.1),
        ]
        result = detect_narrative_transitions(momentum)
        assert result == []

    def test_no_transitions_declining_only(self):
        momentum = [
            _momentum("AI/LLM", -0.5),
            _momentum("エネルギー", -0.8),
        ]
        result = detect_narrative_transitions(momentum)
        assert result == []

    def test_no_transitions_rising_only(self):
        momentum = [
            _momentum("AI/LLM", 0.5),
            _momentum("エネルギー", 0.8),
        ]
        result = detect_narrative_transitions(momentum)
        assert result == []

    def test_threshold_boundary_exclusive(self):
        """Exactly -0.3 should NOT be declining (< -0.3 required)."""
        momentum = [
            _momentum("AI/LLM", -0.3),
            _momentum("エネルギー", 0.3),
        ]
        result = detect_narrative_transitions(momentum)
        assert result == []

    def test_threshold_just_below(self):
        momentum = [
            _momentum("AI/LLM", -0.301),
            _momentum("エネルギー", 0.301),
        ]
        result = detect_narrative_transitions(momentum)
        assert len(result) == 1

    def test_vanished_category(self):
        """Momentum -1.0 (vanished) should be in declining."""
        momentum = [
            _momentum("AI/LLM", -1.0),
            _momentum("エネルギー", 0.5),
        ]
        result = detect_narrative_transitions(momentum)
        assert len(result) == 1
        assert result[0]["from_category"] == "AI/LLM"

    def test_new_category_rising(self):
        """New category with count-based momentum > 0.3."""
        momentum = [
            _momentum("AI/LLM", -0.5),
            _momentum("新カテゴリ", 3.0, today_count=3, yesterday_count=0),
        ]
        result = detect_narrative_transitions(momentum)
        assert len(result) == 1
        assert result[0]["to_category"] == "新カテゴリ"

    def test_empty_list(self):
        result = detect_narrative_transitions([])
        assert result == []

    def test_custom_thresholds(self):
        momentum = [
            _momentum("AI/LLM", -0.2),
            _momentum("エネルギー", 0.2),
        ]
        # Default thresholds: nothing
        assert detect_narrative_transitions(momentum) == []
        # Relaxed thresholds
        result = detect_narrative_transitions(
            momentum, declining_threshold=-0.1, rising_threshold=0.1,
        )
        assert len(result) == 1


class TestBuildTransitionOutlook:
    def test_basic_aggregation(self):
        today = [
            _momentum("AI/LLM", 0.0, today_count=10),
            _momentum("エネルギー", 0.0, today_count=3),
        ]
        history = [
            {"from_category": "AI/LLM", "to_category": "エネルギー"},
            {"from_category": "AI/LLM", "to_category": "エネルギー"},
            {"from_category": "AI/LLM", "to_category": "金融"},
        ]
        result = build_transition_outlook(today, history)
        assert result["dominant_category"] == "AI/LLM"
        assert result["total_observations"] == 3
        assert len(result["historical_transitions"]) == 2
        # エネルギー should be first (2 > 1)
        assert result["historical_transitions"][0]["to_category"] == "エネルギー"
        assert result["historical_transitions"][0]["count"] == 2
        assert abs(result["historical_transitions"][0]["pct"] - 0.667) < 0.01

    def test_top_n_limit(self):
        today = [_momentum("AI/LLM", 0.0, today_count=10)]
        history = [
            {"from_category": "AI/LLM", "to_category": f"cat{i}"}
            for i in range(10)
        ]
        result = build_transition_outlook(today, history, top_n=3)
        assert len(result["historical_transitions"]) == 3

    def test_no_history(self):
        today = [_momentum("AI/LLM", 0.0, today_count=10)]
        result = build_transition_outlook(today, [])
        assert result["dominant_category"] == "AI/LLM"
        assert result["historical_transitions"] == []
        assert result["total_observations"] == 0

    def test_empty_momentum(self):
        result = build_transition_outlook([], [])
        assert result["dominant_category"] == ""
        assert result["historical_transitions"] == []

    def test_no_matching_from_category(self):
        today = [_momentum("AI/LLM", 0.0, today_count=10)]
        history = [
            {"from_category": "エネルギー", "to_category": "金融"},
        ]
        result = build_transition_outlook(today, history)
        assert result["dominant_category"] == "AI/LLM"
        assert result["historical_transitions"] == []
        assert result["total_observations"] == 0

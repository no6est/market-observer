"""Tests for source reliability score (SRS) and weighted momentum."""

import pytest

from app.enrichers.source_reliability import compute_srs, apply_srs_to_events
from app.enrichers.narrative_momentum import (
    compute_category_momentum,
    compute_weighted_category_momentum,
)


class TestComputeSRS:
    def test_tier1_direct(self):
        event = {
            "diffusion_pattern": "tier1_direct",
            "independent_source_count": 0,
            "echo_chamber_ratio": 0.0,
        }
        srs = compute_srs(event)
        assert srs == pytest.approx(1.0)

    def test_sns_to_tier1(self):
        event = {
            "diffusion_pattern": "sns_to_tier1",
            "independent_source_count": 0,
            "echo_chamber_ratio": 0.0,
        }
        srs = compute_srs(event)
        assert srs == pytest.approx(0.85)

    def test_sns_only_high_echo(self):
        event = {
            "diffusion_pattern": "sns_only",
            "independent_source_count": 1,
            "echo_chamber_ratio": 0.8,
        }
        srs = compute_srs(event)
        # base=0.30, diversity=min(1/5, 0.20)=0.20, penalty=0.8*0.20=0.16
        assert srs == pytest.approx(0.30 + 0.20 - 0.16, abs=0.01)

    def test_no_coverage(self):
        event = {
            "diffusion_pattern": "no_coverage",
            "independent_source_count": 0,
            "echo_chamber_ratio": 0.0,
        }
        srs = compute_srs(event)
        assert srs == pytest.approx(0.20)

    def test_diversity_bonus(self):
        event = {
            "diffusion_pattern": "sns_to_tier2",
            "independent_source_count": 3,
            "echo_chamber_ratio": 0.0,
        }
        srs = compute_srs(event)
        # base=0.60, diversity=min(3/5, 0.20)=0.20
        assert srs == pytest.approx(0.80, abs=0.01)

    def test_diversity_bonus_max(self):
        event = {
            "diffusion_pattern": "sns_to_tier2",
            "independent_source_count": 10,
            "echo_chamber_ratio": 0.0,
        }
        srs = compute_srs(event)
        # base=0.60, diversity=min(10/5, 0.20)=0.20
        assert srs == pytest.approx(0.80, abs=0.01)

    def test_clamp_upper(self):
        event = {
            "diffusion_pattern": "tier1_direct",
            "independent_source_count": 10,
            "echo_chamber_ratio": 0.0,
        }
        srs = compute_srs(event)
        assert srs <= 1.0

    def test_clamp_lower(self):
        event = {
            "diffusion_pattern": "no_coverage",
            "independent_source_count": 0,
            "echo_chamber_ratio": 1.0,
        }
        srs = compute_srs(event)
        # base=0.20, penalty=1.0*0.20=0.20 => 0.0
        assert srs >= 0.0
        assert srs == pytest.approx(0.0)

    def test_missing_fields_no_error(self):
        """Missing optional fields should not raise KeyError."""
        event = {}
        srs = compute_srs(event)
        assert 0.0 <= srs <= 1.0

    def test_none_values(self):
        event = {
            "diffusion_pattern": "sns_to_tier2",
            "independent_source_count": None,
            "echo_chamber_ratio": None,
        }
        srs = compute_srs(event)
        assert srs == pytest.approx(0.60)

    def test_custom_tier_weights(self):
        event = {
            "diffusion_pattern": "tier1_direct",
            "independent_source_count": 0,
            "echo_chamber_ratio": 0.0,
        }
        srs = compute_srs(event, tier_weights={"tier1_direct": 0.5})
        assert srs == pytest.approx(0.5)


class TestApplySRSToEvents:
    def test_adds_srs_field(self):
        events = [
            {"diffusion_pattern": "tier1_direct", "independent_source_count": 0, "echo_chamber_ratio": 0.0},
            {"diffusion_pattern": "sns_only", "independent_source_count": 0, "echo_chamber_ratio": 0.0},
        ]
        apply_srs_to_events(events)
        assert "srs" in events[0]
        assert "srs" in events[1]
        assert events[0]["srs"] > events[1]["srs"]

    def test_empty_events(self):
        events = []
        apply_srs_to_events(events)
        assert events == []


class TestWeightedCategoryMomentum:
    def test_srs_weighting_matters(self):
        """Events with higher SRS should weigh more."""
        today = [
            {"narrative_category": "AI/LLM", "srs": 1.0},
            {"narrative_category": "AI/LLM", "srs": 0.9},
        ]
        yesterday = [
            {"narrative_category": "AI/LLM", "srs": 0.3},
        ]
        result = compute_weighted_category_momentum(today, yesterday)
        cat = result[0]
        assert cat["category"] == "AI/LLM"
        assert cat["today_weight"] > cat["yesterday_weight"]
        # momentum = (1.9 - 0.3) / 0.3 ≈ 5.33
        assert cat["momentum"] > 1.0

    def test_srs_fallback_to_1(self):
        """Without srs field, fallback to 1.0 — matches raw count."""
        today = [
            {"narrative_category": "AI/LLM"},
            {"narrative_category": "AI/LLM"},
        ]
        yesterday = [
            {"narrative_category": "AI/LLM"},
        ]
        weighted = compute_weighted_category_momentum(today, yesterday)
        unweighted = compute_category_momentum(today, yesterday)

        # With fallback=1.0, weighted should match unweighted momentum
        assert weighted[0]["momentum"] == unweighted[0]["momentum"]

    def test_output_has_weight_fields(self):
        today = [{"narrative_category": "AI/LLM", "srs": 0.5}]
        yesterday = [{"narrative_category": "AI/LLM", "srs": 0.5}]
        result = compute_weighted_category_momentum(today, yesterday)
        assert "today_weight" in result[0]
        assert "yesterday_weight" in result[0]

    def test_empty_events(self):
        result = compute_weighted_category_momentum([], [])
        assert result == []

    def test_vanished_category(self):
        today = []
        yesterday = [{"narrative_category": "AI/LLM", "srs": 0.5}]
        result = compute_weighted_category_momentum(today, yesterday)
        assert result[0]["classification"] == "消滅"
        assert result[0]["momentum"] == -1.0

    def test_new_category(self):
        today = [{"narrative_category": "AI/LLM", "srs": 0.5}]
        yesterday = []
        result = compute_weighted_category_momentum(today, yesterday)
        assert result[0]["classification"] == "新出"

"""Tests for narrative concentration index calculator."""

from __future__ import annotations

import pytest

from app.enrichers.narrative_concentration import compute_narrative_concentration


@pytest.fixture
def balanced_events() -> list[dict]:
    return [
        {"ticker": "NVDA", "narrative_category": "AI/LLM/自動化", "ai_centricity": 0.9},
        {"ticker": "CRWD", "narrative_category": "規制/政策/地政学", "ai_centricity": 0.1},
        {"ticker": "XOM", "narrative_category": "エネルギー/資源", "ai_centricity": 0.05},
        {"ticker": "JPM", "narrative_category": "金融/金利/流動性", "ai_centricity": 0.1},
    ]


@pytest.fixture
def ai_heavy_events() -> list[dict]:
    return [
        {"ticker": "NVDA", "narrative_category": "AI/LLM/自動化", "ai_centricity": 0.95},
        {"ticker": "MSFT", "narrative_category": "AI/LLM/自動化", "ai_centricity": 0.85},
        {"ticker": "GOOGL", "narrative_category": "AI/LLM/自動化", "ai_centricity": 0.9},
        {"ticker": "CRWD", "narrative_category": "規制/政策/地政学", "ai_centricity": 0.1},
    ]


class TestComputeNarrativeConcentration:
    def test_empty_events(self) -> None:
        result = compute_narrative_concentration([], db=None)
        assert result["category_distribution"] == {}
        assert result["ai_ratio"] == 0.0
        assert result["top1_concentration"] == 0.0
        assert result["warning_flags"] == []

    def test_balanced_distribution(self, balanced_events) -> None:
        result = compute_narrative_concentration(balanced_events, db=None)
        dist = result["category_distribution"]
        assert len(dist) == 4
        assert dist["AI/LLM/自動化"]["count"] == 1
        assert dist["AI/LLM/自動化"]["pct"] == 0.25
        assert result["top1_concentration"] == 0.25

    def test_ai_ratio_calculation(self, balanced_events) -> None:
        result = compute_narrative_concentration(balanced_events, db=None)
        # 1 AI event out of 4 = 0.25
        assert result["ai_ratio"] == 0.25

    def test_ai_heavy_warnings(self, ai_heavy_events) -> None:
        result = compute_narrative_concentration(ai_heavy_events, db=None)
        # 3 AI + 0 adjacent = 0.75
        assert result["ai_ratio"] == 0.75
        assert len(result["warning_flags"]) > 0
        assert any("AI" in w for w in result["warning_flags"])

    def test_top1_concentration_warning(self) -> None:
        events = [
            {"ticker": f"T{i}", "narrative_category": "AI/LLM/自動化", "ai_centricity": 0.9}
            for i in range(7)
        ] + [
            {"ticker": "CRWD", "narrative_category": "規制/政策/地政学", "ai_centricity": 0.1},
        ]
        result = compute_narrative_concentration(events, db=None)
        assert result["top1_concentration"] > 0.6
        assert any("偏り" in w for w in result["warning_flags"])

    def test_adjacent_category_partial_count(self) -> None:
        events = [
            {"ticker": "NVDA", "narrative_category": "AI/LLM/自動化", "ai_centricity": 0.9},
            {"ticker": "TSM", "narrative_category": "半導体/供給網", "ai_centricity": 0.4},
            {"ticker": "CRWD", "narrative_category": "規制/政策/地政学", "ai_centricity": 0.1},
        ]
        result = compute_narrative_concentration(events, db=None)
        # AI: 1/3 + adjacent: 1/3 * 0.3 = 0.333 + 0.1 = 0.433
        assert 0.4 <= result["ai_ratio"] <= 0.5

    def test_distribution_pct_sums_to_one(self, balanced_events) -> None:
        result = compute_narrative_concentration(balanced_events, db=None)
        total_pct = sum(
            info["pct"] for info in result["category_distribution"].values()
        )
        assert abs(total_pct - 1.0) < 0.01

    def test_no_db_historical_avg_is_none(self, balanced_events) -> None:
        result = compute_narrative_concentration(balanced_events, db=None)
        assert result["historical_avg"] is None

    def test_result_includes_basis_fields(self, balanced_events) -> None:
        result = compute_narrative_concentration(balanced_events, db=None)
        assert "basis" in result
        assert "total_events" in result
        assert "basis_events" in result
        assert result["basis"] == "全イベント"
        assert result["total_events"] == 4
        assert result["basis_events"] == 4

    def test_top_ranked_basis(self) -> None:
        events = [
            {"ticker": "NVDA", "narrative_category": "AI/LLM/自動化", "sis": 0.8},
            {"ticker": "CRWD", "narrative_category": "規制/政策/地政学", "sis": 0.5},
            {"ticker": "XOM", "narrative_category": "エネルギー/資源", "sis": 0.1},
        ]
        result = compute_narrative_concentration(
            events, db=None, narrative_basis="top_ranked"
        )
        assert result["total_events"] == 3
        assert result["basis_events"] == 2  # Only NVDA + CRWD (SIS >= 0.3)
        assert result["basis"] == "SIS上位イベント（≥0.3）"

    def test_social_only_basis(self) -> None:
        events = [
            {"ticker": "NVDA", "narrative_category": "AI/LLM/自動化", "signal_type": "price_change"},
            {"ticker": "PLTR", "narrative_category": "AI/LLM/自動化", "signal_type": "mention_surge"},
            {"ticker": "CRWD", "narrative_category": "規制/政策/地政学", "signal_type": "mention_surge"},
        ]
        result = compute_narrative_concentration(
            events, db=None, narrative_basis="social_only"
        )
        assert result["total_events"] == 3
        assert result["basis_events"] == 2  # Only mention_surge signals
        assert result["basis"] == "SNSシグナルのみ"

    def test_empty_after_basis_filter(self) -> None:
        events = [
            {"ticker": "NVDA", "narrative_category": "AI/LLM/自動化", "sis": 0.1},
        ]
        result = compute_narrative_concentration(
            events, db=None, narrative_basis="top_ranked"
        )
        assert result["total_events"] == 1
        assert result["basis_events"] == 0
        assert result["ai_ratio"] == 0.0

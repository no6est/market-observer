"""Tests for Phase 2-3 narrative modules."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.enrichers.narrative_momentum import (
    compute_category_momentum,
    detect_weak_drift,
)
from app.enrichers.narrative_graph import (
    build_narrative_graph,
    format_narrative_graph_text,
    _classify_strength,
)
from app.enrichers.regime_narrative_cross import (
    compute_regime_narrative_cross,
)
from app.enrichers.story_generator import (
    generate_story_summary,
)


# --- Momentum ---


class TestCategoryMomentum:
    def test_basic_increase(self):
        today = [
            {"narrative_category": "AI/LLM/自動化"},
            {"narrative_category": "AI/LLM/自動化"},
        ]
        yesterday = [
            {"narrative_category": "AI/LLM/自動化"},
        ]
        result = compute_category_momentum(today, yesterday)
        assert len(result) == 1
        assert result[0]["category"] == "AI/LLM/自動化"
        assert result[0]["momentum"] == 1.0
        assert result[0]["classification"] == "拡大中"

    def test_rapid_expansion(self):
        today = [{"narrative_category": "X"}] * 5
        yesterday = [{"narrative_category": "X"}] * 2
        result = compute_category_momentum(today, yesterday)
        assert result[0]["momentum"] == 1.5
        assert result[0]["classification"] == "急拡大"

    def test_stable(self):
        today = [{"narrative_category": "X"}] * 3
        yesterday = [{"narrative_category": "X"}] * 3
        result = compute_category_momentum(today, yesterday)
        assert result[0]["momentum"] == 0.0
        assert result[0]["classification"] == "安定"

    def test_contraction(self):
        today = [{"narrative_category": "X"}] * 1
        yesterday = [{"narrative_category": "X"}] * 5
        result = compute_category_momentum(today, yesterday)
        assert result[0]["momentum"] < -0.3
        assert result[0]["classification"] == "縮小"

    def test_new_category(self):
        today = [{"narrative_category": "新カテゴリ"}]
        yesterday = []
        result = compute_category_momentum(today, yesterday)
        assert result[0]["classification"] == "新出"

    def test_disappeared_category(self):
        today = []
        yesterday = [{"narrative_category": "消えたカテゴリ"}]
        result = compute_category_momentum(today, yesterday)
        assert result[0]["classification"] == "消滅"

    def test_empty_events(self):
        result = compute_category_momentum([], [])
        assert result == []

    def test_zero_division(self):
        today = [{"narrative_category": "X"}] * 3
        yesterday = []
        result = compute_category_momentum(today, yesterday)
        assert result[0]["classification"] == "新出"


# --- Weak Drift ---


class TestWeakDrift:
    def _make_context(self, cat_pct=0.15, z_score=1.5):
        narrative_health = {
            "category_scores": {
                "AI/LLM/自動化": {"z_score": z_score},
            },
        }
        narrative_index = {
            "category_distribution": {
                "AI/LLM/自動化": {"pct": cat_pct},
            },
        }
        return narrative_health, narrative_index

    def test_all_conditions_met(self):
        nh, ni = self._make_context(cat_pct=0.15, z_score=1.5)
        events = [
            {"ticker": "NVDA", "narrative_category": "AI/LLM/自動化",
             "signal_type": "mention_surge", "summary": "test", "shock_type": "Tech shock"},
        ]
        result = detect_weak_drift(events, nh, ni, z_threshold=1.2, category_ratio=0.30)
        assert len(result) == 1
        assert result[0]["strength"] == "weak"

    def test_category_ratio_too_high(self):
        nh, ni = self._make_context(cat_pct=0.35, z_score=1.5)
        events = [
            {"ticker": "NVDA", "narrative_category": "AI/LLM/自動化",
             "signal_type": "mention_surge"},
        ]
        result = detect_weak_drift(events, nh, ni)
        assert len(result) == 0

    def test_z_score_too_low(self):
        nh, ni = self._make_context(cat_pct=0.15, z_score=1.0)
        events = [
            {"ticker": "NVDA", "narrative_category": "AI/LLM/自動化",
             "signal_type": "mention_surge"},
        ]
        result = detect_weak_drift(events, nh, ni)
        assert len(result) == 0

    def test_no_mention_surge(self):
        nh, ni = self._make_context(cat_pct=0.15, z_score=1.5)
        events = [
            {"ticker": "NVDA", "narrative_category": "AI/LLM/自動化",
             "signal_type": "price_change"},
        ]
        result = detect_weak_drift(events, nh, ni)
        assert len(result) == 0

    def test_none_inputs(self):
        result = detect_weak_drift([], None, None)
        assert result == []


# --- Narrative Graph ---


class TestNarrativeGraph:
    def test_basic_grouping(self):
        events = [
            {"ticker": "NVDA", "sis": 0.85, "narrative_category": "AI/LLM/自動化"},
            {"ticker": "AMD", "sis": 0.45, "narrative_category": "AI/LLM/自動化"},
            {"ticker": "LMT", "sis": 0.38, "narrative_category": "規制/政策/地政学"},
        ]
        graph = build_narrative_graph(events)
        assert len(graph) == 2
        # First category should have more events
        ai_entry = next(g for g in graph if g["category"] == "AI/LLM/自動化")
        assert len(ai_entry["tickers"]) == 2
        assert ai_entry["tickers"][0]["ticker"] == "NVDA"

    def test_strength_classification(self):
        assert _classify_strength(0.8) == "strong"
        assert _classify_strength(0.5) == "strong"
        assert _classify_strength(0.3) == "moderate"
        assert _classify_strength(0.2) == "moderate"
        assert _classify_strength(0.1) == "weak"

    def test_sis_sort_within_category(self):
        events = [
            {"ticker": "AMD", "sis": 0.3, "narrative_category": "AI/LLM/自動化"},
            {"ticker": "NVDA", "sis": 0.9, "narrative_category": "AI/LLM/自動化"},
        ]
        graph = build_narrative_graph(events)
        assert graph[0]["tickers"][0]["ticker"] == "NVDA"

    def test_empty_events(self):
        assert build_narrative_graph([]) == []

    def test_format_text(self):
        graph = [
            {"category": "AI", "tickers": [
                {"ticker": "NVDA", "sis": 0.85, "strength": "strong"},
            ]},
        ]
        text = format_narrative_graph_text(graph)
        assert "NVDA" in text
        assert "AI" in text


# --- Regime × Narrative ---


class TestRegimeNarrativeCross:
    def test_basic_cross(self):
        events = [
            {"narrative_category": "AI/LLM/自動化", "sis": 0.8},
            {"narrative_category": "AI/LLM/自動化", "sis": 0.6},
            {"narrative_category": "規制/政策/地政学", "sis": 0.4},
        ]
        regime = {"regime": "normal"}
        result = compute_regime_narrative_cross(events, regime)
        assert result is not None
        assert result["regime"] == "normal"
        assert len(result["categories"]) == 2
        ai = next(c for c in result["categories"] if c["category"] == "AI/LLM/自動化")
        assert ai["data_sufficient"] is True
        reg = next(c for c in result["categories"] if c["category"] == "規制/政策/地政学")
        assert reg["data_sufficient"] is False

    def test_no_regime(self):
        assert compute_regime_narrative_cross([], None) is None

    def test_no_events(self):
        result = compute_regime_narrative_cross([], {"regime": "normal"})
        assert result is None


# --- Story Generator ---


class TestStoryGenerator:
    def test_template_fallback(self):
        events = [
            {"ticker": "NVDA", "sis": 0.85, "spp": 0.5,
             "shock_type": "Tech shock",
             "narrative_category": "AI/LLM/自動化"},
        ]
        regime = {"regime": "normal"}
        result = generate_story_summary(events, regime, gemini_client=None)
        assert "NVDA" in result
        assert "テクノロジーショック" in result
        assert "平時" in result

    def test_empty_events(self):
        result = generate_story_summary([], None, None)
        assert "検出されませんでした" in result

    def test_llm_mock(self):
        mock_client = MagicMock()
        mock_client.generate.return_value = "LLMが生成したストーリーサマリーです。"
        events = [
            {"ticker": "NVDA", "sis": 0.85,
             "shock_type": "Tech shock",
             "narrative_category": "AI/LLM/自動化"},
        ]
        result = generate_story_summary(events, {"regime": "normal"}, mock_client)
        assert result == "LLMが生成したストーリーサマリーです。"

    def test_llm_failure_fallback(self):
        mock_client = MagicMock()
        mock_client.generate.side_effect = Exception("API error")
        events = [
            {"ticker": "NVDA", "sis": 0.85,
             "shock_type": "Tech shock",
             "narrative_category": "AI/LLM/自動化"},
        ]
        result = generate_story_summary(events, {"regime": "normal"}, mock_client)
        assert "NVDA" in result  # Template fallback

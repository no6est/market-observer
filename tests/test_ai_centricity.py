"""Tests for AI centricity score calculator."""

from __future__ import annotations

import pytest

from app.enrichers.ai_centricity import compute_ai_centricity


@pytest.fixture
def ai_event() -> dict:
    return {
        "ticker": "NVDA",
        "signal_type": "price_change",
        "score": 0.8,
        "summary": "NVDA AI GPU demand surge",
        "narrative_category": "AI/LLM/自動化",
    }


@pytest.fixture
def non_ai_event() -> dict:
    return {
        "ticker": "CRWD",
        "signal_type": "price_change",
        "score": 0.7,
        "summary": "CRWD cybersecurity breach impact",
        "narrative_category": "規制/政策/地政学",
    }


@pytest.fixture
def adjacent_event() -> dict:
    return {
        "ticker": "NVDA",
        "signal_type": "volume_spike",
        "score": 0.6,
        "summary": "Semiconductor supply chain disruption",
        "narrative_category": "半導体/供給網",
    }


class TestComputeAiCentricity:
    def test_high_ai_score(self, ai_event) -> None:
        articles = [
            {"title": "AI revolution: GPT and LLM transform industries", "summary": "Machine learning and deep learning advances"},
        ]
        score = compute_ai_centricity(ai_event, articles, [])
        assert 0.5 <= score <= 1.0

    def test_low_ai_score(self, non_ai_event) -> None:
        articles = [
            {"title": "Cybersecurity regulation update: SEC compliance requirements", "summary": "New regulatory framework for data protection"},
        ]
        score = compute_ai_centricity(non_ai_event, articles, [])
        assert 0.0 <= score <= 0.3

    def test_adjacent_category_partial_credit(self, adjacent_event) -> None:
        articles = [
            {"title": "TSMC chip shortage impacts GPU supply chain", "summary": "Semiconductor logistics bottleneck"},
        ]
        score = compute_ai_centricity(adjacent_event, articles, [])
        # Should get partial credit from adjacent category (0.3)
        assert 0.05 <= score <= 0.6

    def test_score_range(self, ai_event) -> None:
        score = compute_ai_centricity(ai_event, [], [])
        assert 0.0 <= score <= 1.0

    def test_empty_context(self) -> None:
        event = {
            "ticker": "MSFT",
            "signal_type": "price_change",
            "score": 0.5,
            "summary": "",
            "narrative_category": "その他",
        }
        score = compute_ai_centricity(event, [], [])
        assert score == 0.0

    def test_posts_contribute(self, ai_event) -> None:
        posts = [
            {"title": "OpenAI GPT-5 changes everything", "body": "AI artificial intelligence LLM transformer model training"},
        ]
        score = compute_ai_centricity(ai_event, [], posts)
        assert score > 0.3

    def test_ai_category_boosts_score(self) -> None:
        event_with_ai_cat = {
            "ticker": "NVDA",
            "signal_type": "price_change",
            "score": 0.5,
            "summary": "Price change detected",
            "narrative_category": "AI/LLM/自動化",
        }
        event_without_ai_cat = {
            "ticker": "NVDA",
            "signal_type": "price_change",
            "score": 0.5,
            "summary": "Price change detected",
            "narrative_category": "その他",
        }
        score_with = compute_ai_centricity(event_with_ai_cat, [], [])
        score_without = compute_ai_centricity(event_without_ai_cat, [], [])
        assert score_with > score_without

    def test_score_precision(self, ai_event) -> None:
        score = compute_ai_centricity(ai_event, [], [])
        # Should be rounded to 3 decimal places
        assert score == round(score, 3)

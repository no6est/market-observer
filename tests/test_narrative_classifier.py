"""Tests for narrative category classifier."""

from __future__ import annotations

import pytest

from app.enrichers.narrative_classifier import (
    NARRATIVE_CATEGORIES,
    classify_narrative_category,
)


@pytest.fixture
def base_event() -> dict:
    return {
        "ticker": "NVDA",
        "signal_type": "price_change",
        "score": 0.8,
        "summary": "",
        "details": {},
    }


class TestClassifyNarrativeCategory:
    def test_ai_category(self, base_event) -> None:
        articles = [
            {"title": "OpenAI launches new GPT model with breakthrough capabilities", "summary": "The new LLM demonstrates advanced AI reasoning"},
        ]
        result = classify_narrative_category(base_event, articles, [])
        assert result == "AI/LLM/自動化"

    def test_regulation_category(self, base_event) -> None:
        articles = [
            {"title": "SEC announces new antitrust probe into tech giants", "summary": "Regulatory compliance requirements expected to increase"},
        ]
        result = classify_narrative_category(base_event, articles, [])
        assert result == "規制/政策/地政学"

    def test_financial_category(self, base_event) -> None:
        articles = [
            {"title": "Federal Reserve signals rate cut amid inflation concerns", "summary": "Bond yields drop as monetary policy shifts"},
        ]
        result = classify_narrative_category(base_event, articles, [])
        assert result == "金融/金利/流動性"

    def test_energy_category(self, base_event) -> None:
        articles = [
            {"title": "OPEC cuts oil production, crude prices surge", "summary": "Energy markets react to renewable transition concerns"},
        ]
        result = classify_narrative_category(base_event, articles, [])
        assert result == "エネルギー/資源"

    def test_semiconductor_category(self, base_event) -> None:
        articles = [
            {"title": "TSMC announces new 2nm chip fab amid supply chain concerns", "summary": "Semiconductor shortage affects GPU production and HBM memory"},
        ]
        result = classify_narrative_category(base_event, articles, [])
        assert result == "半導体/供給網"

    def test_governance_category(self, base_event) -> None:
        articles = [
            {"title": "CEO resigns amid board restructuring and audit concerns", "summary": "Executive leadership succession plan announced"},
        ]
        result = classify_narrative_category(base_event, articles, [])
        assert result == "ガバナンス/経営"

    def test_social_category(self, base_event) -> None:
        articles = [
            {"title": "Tech workers union strike over wage and remote work policies", "summary": "Labor market disruption as employees demand hybrid workforce changes"},
        ]
        result = classify_narrative_category(base_event, articles, [])
        assert result == "社会/労働/教育"

    def test_empty_context_returns_other(self, base_event) -> None:
        result = classify_narrative_category(base_event, [], [])
        assert result == "その他"

    def test_no_match_returns_other(self, base_event) -> None:
        articles = [{"title": "Lorem ipsum dolor sit amet", "summary": "Nothing relevant"}]
        result = classify_narrative_category(base_event, articles, [])
        assert result == "その他"

    def test_posts_contribute_to_classification(self, base_event) -> None:
        posts = [
            {"title": "AI is changing everything with LLM and GPT", "body": "Machine learning transformers are the future of artificial intelligence"},
        ]
        result = classify_narrative_category(base_event, [], posts)
        assert result == "AI/LLM/自動化"

    def test_result_is_valid_category(self, base_event) -> None:
        articles = [{"title": "Some news about technology", "summary": "Details"}]
        result = classify_narrative_category(base_event, articles, [])
        assert result in NARRATIVE_CATEGORIES

    def test_event_summary_contributes(self) -> None:
        event = {
            "ticker": "GOOGL",
            "signal_type": "mention_surge",
            "score": 0.6,
            "summary": "OpenAI GPT model launch drives AI chatbot discussion",
            "details": {},
        }
        result = classify_narrative_category(event, [], [])
        assert result == "AI/LLM/自動化"

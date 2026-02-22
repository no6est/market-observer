"""Tests for non-AI structural change highlighter."""

from __future__ import annotations

import pytest

from app.enrichers.non_ai_highlights import (
    compute_undercovered_score,
    extract_non_ai_highlights,
)


@pytest.fixture
def mixed_events() -> list[dict]:
    return [
        {
            "ticker": "NVDA",
            "summary": "AI GPU demand surge",
            "sis": 0.9,
            "narrative_category": "AI/LLM/自動化",
            "ai_centricity": 0.95,
            "shock_type": "Tech shock",
            "evidence_titles": ["AI chip news"],
            "evidence_score": 0.8,
            "signal_type": "price_change",
        },
        {
            "ticker": "CRWD",
            "summary": "Cybersecurity regulation update",
            "sis": 0.7,
            "narrative_category": "規制/政策/地政学",
            "ai_centricity": 0.1,
            "shock_type": "Regulation shock",
            "evidence_titles": ["SEC compliance update"],
            "evidence_score": 0.5,
            "signal_type": "volume_spike",
        },
        {
            "ticker": "XOM",
            "summary": "Oil supply disruption",
            "sis": 0.8,
            "narrative_category": "エネルギー/資源",
            "ai_centricity": 0.05,
            "shock_type": "Business model shock",
            "evidence_titles": ["OPEC production cut"],
            "evidence_score": 0.2,
            "signal_type": "price_change",
        },
        {
            "ticker": "JPM",
            "summary": "Rate policy impact",
            "sis": 0.6,
            "narrative_category": "金融/金利/流動性",
            "ai_centricity": 0.15,
            "shock_type": "Execution signal",
            "evidence_titles": ["Fed rate decision"],
            "evidence_score": 0.6,
            "signal_type": "mention_surge",
        },
    ]


class TestExtractNonAiHighlights:
    def test_filters_high_ai_events(self, mixed_events) -> None:
        highlights = extract_non_ai_highlights(mixed_events)
        tickers = [h["ticker"] for h in highlights]
        assert "NVDA" not in tickers

    def test_includes_non_ai_events(self, mixed_events) -> None:
        highlights = extract_non_ai_highlights(mixed_events)
        tickers = [h["ticker"] for h in highlights]
        assert "XOM" in tickers
        assert "CRWD" in tickers

    def test_sorted_by_undercovered_score(self, mixed_events) -> None:
        highlights = extract_non_ai_highlights(mixed_events)
        scores = [h["undercovered_score"] for h in highlights]
        assert scores == sorted(scores, reverse=True)

    def test_top_n_limit(self, mixed_events) -> None:
        highlights = extract_non_ai_highlights(mixed_events, top_n=2)
        assert len(highlights) <= 2

    def test_custom_threshold(self, mixed_events) -> None:
        # With threshold 0.05, only XOM (0.05) qualifies
        highlights = extract_non_ai_highlights(mixed_events, ai_threshold=0.05)
        assert len(highlights) == 0  # 0.05 is not < 0.05

    def test_threshold_exclusive(self, mixed_events) -> None:
        # With threshold 0.06, only XOM (0.05) qualifies
        highlights = extract_non_ai_highlights(mixed_events, ai_threshold=0.06)
        assert len(highlights) == 1
        assert highlights[0]["ticker"] == "XOM"

    def test_empty_events(self) -> None:
        highlights = extract_non_ai_highlights([])
        assert highlights == []

    def test_all_ai_events(self) -> None:
        events = [
            {"ticker": "NVDA", "sis": 0.9, "ai_centricity": 0.95, "summary": "AI"},
            {"ticker": "MSFT", "sis": 0.8, "ai_centricity": 0.85, "summary": "AI"},
        ]
        highlights = extract_non_ai_highlights(events)
        assert highlights == []

    def test_highlight_fields(self, mixed_events) -> None:
        highlights = extract_non_ai_highlights(mixed_events, top_n=1)
        assert len(highlights) == 1
        h = highlights[0]
        assert "ticker" in h
        assert "summary" in h
        assert "sis" in h
        assert "narrative_category" in h
        assert "ai_centricity" in h
        assert "shock_type" in h
        assert "evidence_titles" in h
        assert "evidence_score" in h
        assert "undercovered_score" in h


class TestUndercoveredScore:
    def test_high_sis_low_evidence_high_score(self) -> None:
        """High SIS + low evidence + market signal = high undercovered score."""
        event = {"sis": 0.8, "evidence_score": 0.1, "signal_type": "price_change"}
        score = compute_undercovered_score(event)
        assert score > 0.7

    def test_high_sis_high_evidence_lower_score(self) -> None:
        """High SIS + high evidence = lower undercovered score than low evidence."""
        low_ev = {"sis": 0.8, "evidence_score": 0.1, "signal_type": "price_change"}
        high_ev = {"sis": 0.8, "evidence_score": 0.9, "signal_type": "price_change"}
        assert compute_undercovered_score(high_ev) < compute_undercovered_score(low_ev)

    def test_low_sis_low_score(self) -> None:
        """Low SIS events are less important, even if undercovered."""
        event = {"sis": 0.1, "evidence_score": 0.0, "signal_type": "mention_surge"}
        score = compute_undercovered_score(event)
        assert score < 0.5

    def test_mention_only_no_market_signal(self) -> None:
        """mention_surge lacks market signal component."""
        price_event = {"sis": 0.5, "evidence_score": 0.2, "signal_type": "price_change"}
        mention_event = {"sis": 0.5, "evidence_score": 0.2, "signal_type": "mention_surge"}
        assert compute_undercovered_score(price_event) > compute_undercovered_score(mention_event)

    def test_score_in_range(self) -> None:
        event = {"sis": 0.5, "evidence_score": 0.5, "signal_type": "volume_spike"}
        score = compute_undercovered_score(event)
        assert 0.0 <= score <= 1.0

    def test_xom_ranked_higher_than_jpm(self, mixed_events) -> None:
        """XOM (high SIS, low evidence, price_change) should score higher than JPM."""
        highlights = extract_non_ai_highlights(mixed_events)
        tickers = [h["ticker"] for h in highlights]
        assert tickers.index("XOM") < tickers.index("JPM")

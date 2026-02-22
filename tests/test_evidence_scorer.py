"""Tests for evidence score calculator."""

from __future__ import annotations

import pytest

from app.enrichers.evidence_scorer import (
    compute_evidence_score,
    _compute_market_evidence,
    _compute_media_evidence,
    _compute_official_evidence,
    _is_tier1,
    _is_tier2,
)


class TestComputeMarketEvidence:
    def test_price_change_signal(self) -> None:
        event = {"signal_type": "price_change", "z_score": 2.5}
        score = _compute_market_evidence(event)
        assert score >= 0.7
        assert score <= 1.0

    def test_volume_spike_signal(self) -> None:
        event = {"signal_type": "volume_spike", "z_score": 2.0}
        score = _compute_market_evidence(event)
        assert score >= 0.5
        assert score <= 1.0

    def test_mention_surge_weak(self) -> None:
        event = {"signal_type": "mention_surge", "z_score": 5.0}
        score = _compute_market_evidence(event)
        assert score == 0.1

    def test_high_z_score_bonus(self) -> None:
        low_z = {"signal_type": "price_change", "z_score": 1.5}
        high_z = {"signal_type": "price_change", "z_score": 4.0}
        assert _compute_market_evidence(high_z) > _compute_market_evidence(low_z)

    def test_capped_at_one(self) -> None:
        event = {"signal_type": "price_change", "z_score": 20.0}
        assert _compute_market_evidence(event) <= 1.0


class TestComputeMediaEvidence:
    def test_tier1_article(self) -> None:
        articles = [{"source": "Reuters", "url": "https://reuters.com/article"}]
        score = _compute_media_evidence(articles)
        assert score >= 0.3

    def test_tier2_article(self) -> None:
        articles = [{"source": "TechCrunch", "url": "https://techcrunch.com/post"}]
        score = _compute_media_evidence(articles)
        assert score >= 0.1

    def test_multiple_tier1_capped(self) -> None:
        articles = [
            {"source": "Reuters", "url": "https://reuters.com/a"},
            {"source": "Bloomberg", "url": "https://bloomberg.com/b"},
            {"source": "WSJ", "url": "https://wsj.com/c"},
            {"source": "NYTimes", "url": "https://nytimes.com/d"},
        ]
        score = _compute_media_evidence(articles)
        assert score <= 1.0

    def test_no_articles(self) -> None:
        assert _compute_media_evidence([]) == 0.0

    def test_unknown_source(self) -> None:
        articles = [{"source": "MyBlog", "url": "https://myblog.com/post"}]
        score = _compute_media_evidence(articles)
        assert score == 0.0


class TestComputeOfficialEvidence:
    def test_announcement_in_title(self) -> None:
        articles = [{"title": "NVIDIA announces Blackwell Ultra GPU", "summary": ""}]
        score = _compute_official_evidence(articles, [])
        assert score > 0

    def test_earnings_keyword(self) -> None:
        articles = [{"title": "Q4 earnings beat expectations", "summary": ""}]
        score = _compute_official_evidence(articles, [])
        assert score > 0

    def test_no_official_keywords(self) -> None:
        articles = [{"title": "Stock goes up today", "summary": ""}]
        score = _compute_official_evidence(articles, [])
        assert score == 0.0

    def test_post_with_official_keyword(self) -> None:
        posts = [{"title": "CEO confirms restructuring plan"}]
        score = _compute_official_evidence([], posts)
        assert score > 0


class TestSourceClassification:
    def test_tier1_by_source(self) -> None:
        assert _is_tier1({"source": "Reuters", "url": ""})
        assert _is_tier1({"source": "Bloomberg", "url": ""})

    def test_tier1_by_url(self) -> None:
        assert _is_tier1({"source": "", "url": "https://www.reuters.com/article/x"})

    def test_tier2_sources(self) -> None:
        assert _is_tier2({"source": "TechCrunch", "url": ""})
        assert _is_tier2({"source": "ArsTechnica", "url": ""})

    def test_not_tier1_or_tier2(self) -> None:
        article = {"source": "RandomBlog", "url": "https://random.blog/post"}
        assert not _is_tier1(article)
        assert not _is_tier2(article)


class TestComputeEvidenceScore:
    def test_well_supported_event(self) -> None:
        event = {"ticker": "NVDA", "signal_type": "price_change", "z_score": 3.5}
        articles = [
            {"source": "Reuters", "url": "https://reuters.com/a", "title": "NVIDIA announces GPU", "summary": ""},
        ]
        result = compute_evidence_score(event, articles, [])
        assert result["evidence_score"] > 0.5
        assert result["market_evidence"] > 0.5
        assert result["media_evidence"] > 0
        assert result["official_evidence"] > 0

    def test_mention_only_event(self) -> None:
        event = {"ticker": "PLTR", "signal_type": "mention_surge", "z_score": 5.0}
        result = compute_evidence_score(event, [], [])
        assert result["evidence_score"] < 0.2
        assert result["market_evidence"] == 0.1

    def test_all_scores_in_range(self) -> None:
        event = {"ticker": "X", "signal_type": "price_change", "z_score": 2.0}
        articles = [{"source": "Reuters", "url": "r.com", "title": "announces", "summary": ""}]
        result = compute_evidence_score(event, articles, [])
        for key in ("evidence_score", "market_evidence", "media_evidence", "official_evidence"):
            assert 0.0 <= result[key] <= 1.0

    def test_empty_articles_and_posts(self) -> None:
        event = {"ticker": "X", "signal_type": "volume_spike", "z_score": 3.0}
        result = compute_evidence_score(event, [], [])
        assert result["media_evidence"] == 0.0
        assert result["official_evidence"] == 0.0
        assert result["market_evidence"] > 0

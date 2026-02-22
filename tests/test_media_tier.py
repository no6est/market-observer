"""Tests for media tier distribution calculator."""

from __future__ import annotations

import pytest

from app.enrichers.media_tier import (
    compute_media_tier_distribution,
    compute_sns_bias_ratio,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_event() -> dict:
    """Minimal event dict used across tests."""
    return {"ticker": "NVDA"}


# ---------------------------------------------------------------------------
# compute_media_tier_distribution
# ---------------------------------------------------------------------------


class TestComputeMediaTierDistribution:
    def test_tier1_direct(self, base_event: dict) -> None:
        """Articles from Tier1 source only, no posts -> tier1_direct."""
        articles = [
            {"source": "Reuters", "url": "https://reuters.com/article/nvda"},
        ]
        posts: list[dict] = []

        result = compute_media_tier_distribution(base_event, articles, posts)

        assert result["tier1_count"] == 1
        assert result["sns_count"] == 0
        assert result["diffusion_pattern"] == "tier1_direct"

    def test_sns_to_tier1(self, base_event: dict) -> None:
        """Reuters article + reddit posts -> sns_to_tier1."""
        articles = [
            {"source": "Reuters", "url": "https://reuters.com/article/nvda"},
        ]
        posts = [
            {"source": "reddit", "title": "NVDA is mooning"},
        ]

        result = compute_media_tier_distribution(base_event, articles, posts)

        assert result["tier1_count"] == 1
        assert result["sns_count"] == 1
        assert result["diffusion_pattern"] == "sns_to_tier1"

    def test_sns_to_tier2(self, base_event: dict) -> None:
        """TechCrunch article + posts, no tier1 -> sns_to_tier2."""
        articles = [
            {"source": "TechCrunch", "url": "https://techcrunch.com/post"},
        ]
        posts = [
            {"source": "reddit", "title": "Interesting article on TC"},
        ]

        result = compute_media_tier_distribution(base_event, articles, posts)

        assert result["tier1_count"] == 0
        assert result["tier2_count"] == 1
        assert result["sns_count"] == 1
        assert result["diffusion_pattern"] == "sns_to_tier2"

    def test_sns_only(self, base_event: dict) -> None:
        """Only community posts, no articles -> sns_only."""
        articles: list[dict] = []
        posts = [
            {"source": "reddit", "title": "Hot take on NVDA"},
            {"source": "hackernews", "title": "HN thread on NVDA"},
        ]

        result = compute_media_tier_distribution(base_event, articles, posts)

        assert result["tier1_count"] == 0
        assert result["tier2_count"] == 0
        assert result["sns_count"] == 2
        assert result["diffusion_pattern"] == "sns_only"

    def test_no_coverage(self, base_event: dict) -> None:
        """Empty articles and posts -> no_coverage."""
        result = compute_media_tier_distribution(base_event, [], [])

        assert result["tier1_count"] == 0
        assert result["tier2_count"] == 0
        assert result["sns_count"] == 0
        assert result["total_sources"] == 0
        assert result["diffusion_pattern"] == "no_coverage"

    def test_counts_correct(self, base_event: dict) -> None:
        """2 tier1, 1 tier2, 3 posts -> correct counts and total."""
        articles = [
            {"source": "Reuters", "url": "https://reuters.com/a"},
            {"source": "Bloomberg", "url": "https://bloomberg.com/b"},
            {"source": "TechCrunch", "url": "https://techcrunch.com/c"},
        ]
        posts = [
            {"source": "reddit", "title": "Post 1"},
            {"source": "reddit", "title": "Post 2"},
            {"source": "hackernews", "title": "Post 3"},
        ]

        result = compute_media_tier_distribution(base_event, articles, posts)

        assert result["tier1_count"] == 2
        assert result["tier2_count"] == 1
        assert result["sns_count"] == 3
        assert result["total_sources"] == 6
        # Tier1 present + SNS present -> sns_to_tier1
        assert result["diffusion_pattern"] == "sns_to_tier1"


# ---------------------------------------------------------------------------
# compute_sns_bias_ratio
# ---------------------------------------------------------------------------


class TestComputeSnsBiasRatio:
    def test_all_sns(self) -> None:
        """5 sns out of 5 total -> 1.0."""
        tier_dist = {"sns_count": 5, "total_sources": 5}
        assert compute_sns_bias_ratio(tier_dist) == 1.0

    def test_no_sns(self) -> None:
        """3 articles, 0 posts -> 0.0."""
        tier_dist = {"sns_count": 0, "total_sources": 3}
        assert compute_sns_bias_ratio(tier_dist) == 0.0

    def test_mixed(self) -> None:
        """2 tier1 articles + 3 sns posts = 3/5 = 0.6."""
        tier_dist = {"sns_count": 3, "total_sources": 5}
        assert compute_sns_bias_ratio(tier_dist) == 0.6

    def test_empty(self) -> None:
        """total_sources=0 -> 0.0 (no division by zero)."""
        tier_dist = {"sns_count": 0, "total_sources": 0}
        assert compute_sns_bias_ratio(tier_dist) == 0.0

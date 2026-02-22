"""Tests for media echo chamber detection and correction."""

from __future__ import annotations

import pytest

from app.enrichers.echo_chamber import (
    _title_similarity,
    apply_echo_correction,
    detect_echo_chamber,
)


# ---------------------------------------------------------------------------
# _title_similarity
# ---------------------------------------------------------------------------


class TestTitleSimilarity:
    def test_identical_titles(self) -> None:
        sim = _title_similarity("NVIDIA launches Blackwell GPU", "NVIDIA launches Blackwell GPU")
        assert sim == 1.0

    def test_completely_different(self) -> None:
        sim = _title_similarity("NVIDIA launches Blackwell GPU", "Apple reports quarterly earnings")
        assert sim == 0.0

    def test_partial_overlap(self) -> None:
        sim = _title_similarity(
            "NVIDIA launches Blackwell GPU architecture",
            "NVIDIA reveals Blackwell chip details",
        )
        assert 0.0 < sim < 1.0
        # "NVIDIA" and "Blackwell" are shared
        assert sim >= 0.2

    def test_case_insensitive(self) -> None:
        sim = _title_similarity("NVIDIA GPU Launch", "nvidia gpu launch")
        assert sim == 1.0

    def test_stopwords_removed(self) -> None:
        # "The" and "a" are stopwords and should not contribute
        sim = _title_similarity("The NVIDIA GPU", "A NVIDIA GPU")
        assert sim == 1.0

    def test_both_empty_after_stopwords(self) -> None:
        sim = _title_similarity("the a an is", "the and or but")
        assert sim == 1.0

    def test_one_empty_after_stopwords(self) -> None:
        sim = _title_similarity("the a an", "NVIDIA GPU")
        assert sim == 0.0

    def test_empty_strings(self) -> None:
        # Both empty -> both word sets empty -> returns 1.0
        sim = _title_similarity("", "")
        assert sim == 1.0

    def test_one_empty_one_nonempty(self) -> None:
        sim = _title_similarity("", "NVIDIA GPU")
        assert sim == 0.0

    def test_returns_float_in_range(self) -> None:
        sim = _title_similarity("market crash fears grow", "stock market fears rising")
        assert 0.0 <= sim <= 1.0


# ---------------------------------------------------------------------------
# detect_echo_chamber
# ---------------------------------------------------------------------------


class TestDetectEchoChamber:
    def test_no_echo_diverse_articles(self) -> None:
        articles = [
            {"title": "NVIDIA launches Blackwell GPU", "url": "https://a.com/1",
             "source": "A", "summary": ""},
            {"title": "Apple reports quarterly earnings", "url": "https://b.com/2",
             "source": "B", "summary": ""},
            {"title": "Fed raises interest rates", "url": "https://c.com/3",
             "source": "C", "summary": ""},
        ]
        posts: list[dict] = []
        result = detect_echo_chamber(articles, posts)

        assert result["total_sources"] == 3
        assert result["independent_sources"] == 3
        assert result["echo_ratio"] == 0.0
        assert result["correction_factor"] == 1.0
        assert len(result["echo_clusters"]) == 3

    def test_high_echo_similar_titles(self) -> None:
        articles = [
            {"title": "NVIDIA launches Blackwell GPU", "url": "https://a.com/1",
             "source": "A", "summary": ""},
            {"title": "NVIDIA launches Blackwell GPU chip", "url": "https://b.com/2",
             "source": "B", "summary": ""},
            {"title": "NVIDIA Blackwell GPU launched", "url": "https://c.com/3",
             "source": "C", "summary": ""},
        ]
        posts: list[dict] = []
        result = detect_echo_chamber(articles, posts)

        # All three should cluster together
        assert result["independent_sources"] < result["total_sources"]
        assert result["echo_ratio"] > 0.0
        assert result["correction_factor"] < 1.0
        assert result["correction_factor"] >= 0.5

    def test_url_reference_clustering(self) -> None:
        articles = [
            {"title": "Original story", "url": "https://original.com/story",
             "source": "Original", "summary": "Some content."},
            {"title": "Commentary piece", "url": "https://echo.com/piece",
             "source": "Echo", "summary": "As reported by https://original.com/story"},
        ]
        posts: list[dict] = []
        result = detect_echo_chamber(articles, posts)

        # The two should be in the same cluster via URL reference
        assert result["independent_sources"] == 1
        assert result["echo_ratio"] > 0.0
        assert result["correction_factor"] < 1.0

    def test_empty_input(self) -> None:
        result = detect_echo_chamber([], [])

        assert result["total_sources"] == 0
        assert result["independent_sources"] == 0
        assert result["echo_ratio"] == 0.0
        assert result["correction_factor"] == 1.0
        assert result["echo_clusters"] == []

    def test_single_article(self) -> None:
        articles = [
            {"title": "Solo article", "url": "https://a.com/1",
             "source": "A", "summary": ""},
        ]
        result = detect_echo_chamber(articles, [])

        assert result["total_sources"] == 1
        assert result["independent_sources"] == 1
        assert result["echo_ratio"] == 0.0
        assert result["correction_factor"] == 1.0

    def test_posts_only(self) -> None:
        posts = [
            {"title": "Reddit discussion on NVIDIA", "source": "reddit"},
            {"title": "Another post about Apple", "source": "reddit"},
            {"title": "HackerNews NVIDIA thread", "source": "hackernews"},
        ]
        result = detect_echo_chamber([], posts)

        assert result["total_sources"] == 3
        assert result["independent_sources"] >= 2  # titles are diverse
        assert result["correction_factor"] >= 0.5

    def test_posts_with_similar_titles(self) -> None:
        posts = [
            {"title": "NVIDIA Blackwell GPU specs revealed", "source": "reddit"},
            {"title": "NVIDIA Blackwell GPU specs details", "source": "hackernews"},
        ]
        result = detect_echo_chamber([], posts)

        assert result["total_sources"] == 2
        # These posts have very similar titles
        assert result["independent_sources"] <= 2

    def test_correction_factor_range(self) -> None:
        articles = [
            {"title": f"Same story variant {i}", "url": f"https://x.com/{i}",
             "source": f"Source{i}", "summary": ""}
            for i in range(10)
        ]
        result = detect_echo_chamber(articles, [])

        assert 0.5 <= result["correction_factor"] <= 1.0
        assert 0.0 <= result["echo_ratio"] <= 1.0

    def test_echo_clusters_structure(self) -> None:
        articles = [
            {"title": "NVIDIA GPU launch", "url": "https://a.com/1",
             "source": "A", "summary": ""},
            {"title": "Apple earnings report", "url": "https://b.com/2",
             "source": "B", "summary": ""},
        ]
        result = detect_echo_chamber(articles, [])

        for cluster in result["echo_clusters"]:
            assert "representative_title" in cluster
            assert "source_count" in cluster
            assert "sources" in cluster
            assert cluster["source_count"] >= 1
            assert isinstance(cluster["sources"], list)

    def test_clusters_sorted_by_size(self) -> None:
        articles = [
            {"title": "NVIDIA Blackwell GPU launch", "url": "https://a.com/1",
             "source": "A", "summary": ""},
            {"title": "NVIDIA Blackwell GPU reveal", "url": "https://b.com/2",
             "source": "B", "summary": ""},
            {"title": "NVIDIA Blackwell GPU details", "url": "https://c.com/3",
             "source": "C", "summary": ""},
            {"title": "Apple quarterly earnings report", "url": "https://d.com/4",
             "source": "D", "summary": ""},
        ]
        result = detect_echo_chamber(articles, [])

        clusters = result["echo_clusters"]
        for i in range(len(clusters) - 1):
            assert clusters[i]["source_count"] >= clusters[i + 1]["source_count"]

    def test_mixed_articles_and_posts(self) -> None:
        articles = [
            {"title": "NVIDIA Blackwell GPU launch", "url": "https://a.com/1",
             "source": "A", "summary": ""},
        ]
        posts = [
            {"title": "NVIDIA Blackwell GPU launch discussion", "source": "reddit"},
        ]
        result = detect_echo_chamber(articles, posts)

        assert result["total_sources"] == 2

    def test_custom_similarity_threshold(self) -> None:
        articles = [
            {"title": "NVIDIA launches Blackwell GPU", "url": "https://a.com/1",
             "source": "A", "summary": ""},
            {"title": "NVIDIA reveals Blackwell chip architecture", "url": "https://b.com/2",
             "source": "B", "summary": ""},
        ]
        # High threshold: less likely to cluster
        result_strict = detect_echo_chamber(articles, [], similarity_threshold=0.9)
        # Low threshold: more likely to cluster
        result_loose = detect_echo_chamber(articles, [], similarity_threshold=0.2)

        assert result_loose["independent_sources"] <= result_strict["independent_sources"]


# ---------------------------------------------------------------------------
# apply_echo_correction
# ---------------------------------------------------------------------------


class TestApplyEchoCorrection:
    def test_correction_applied(self) -> None:
        event = {"ticker": "NVDA", "media_evidence": 0.8}
        echo_info = {
            "correction_factor": 0.6,
            "echo_ratio": 0.5,
            "independent_sources": 3,
        }
        result = apply_echo_correction(event, echo_info)

        assert result["media_evidence"] == pytest.approx(0.48, abs=0.001)
        assert result["echo_chamber_ratio"] == 0.5
        assert result["independent_source_count"] == 3

    def test_noop_when_factor_is_one(self) -> None:
        event = {"ticker": "NVDA", "media_evidence": 0.8}
        echo_info = {
            "correction_factor": 1.0,
            "echo_ratio": 0.0,
            "independent_sources": 5,
        }
        result = apply_echo_correction(event, echo_info)

        assert result["media_evidence"] == 0.8
        assert result["echo_chamber_ratio"] == 0.0
        assert result["independent_source_count"] == 5

    def test_returns_same_event_dict(self) -> None:
        event = {"ticker": "NVDA", "media_evidence": 0.8}
        echo_info = {"correction_factor": 0.7, "echo_ratio": 0.3, "independent_sources": 2}
        result = apply_echo_correction(event, echo_info)

        # Should mutate and return the same dict
        assert result is event

    def test_missing_media_evidence_defaults_to_zero(self) -> None:
        event = {"ticker": "NVDA"}
        echo_info = {"correction_factor": 0.6, "echo_ratio": 0.5, "independent_sources": 3}
        result = apply_echo_correction(event, echo_info)

        assert result["media_evidence"] == 0.0

    def test_missing_correction_factor_defaults_to_one(self) -> None:
        event = {"ticker": "NVDA", "media_evidence": 0.8}
        echo_info = {}  # No correction_factor
        result = apply_echo_correction(event, echo_info)

        assert result["media_evidence"] == 0.8

    def test_adds_echo_metadata_fields(self) -> None:
        event = {"ticker": "NVDA", "media_evidence": 0.5}
        echo_info = {
            "correction_factor": 0.8,
            "echo_ratio": 0.4,
            "independent_sources": 4,
        }
        result = apply_echo_correction(event, echo_info)

        assert "echo_chamber_ratio" in result
        assert "independent_source_count" in result
        assert result["echo_chamber_ratio"] == 0.4
        assert result["independent_source_count"] == 4

    def test_correction_with_zero_media_evidence(self) -> None:
        event = {"ticker": "NVDA", "media_evidence": 0.0}
        echo_info = {"correction_factor": 0.5, "echo_ratio": 0.6, "independent_sources": 2}
        result = apply_echo_correction(event, echo_info)

        assert result["media_evidence"] == 0.0

    def test_preserves_existing_event_fields(self) -> None:
        event = {
            "ticker": "NVDA",
            "media_evidence": 0.8,
            "signal_type": "price_change",
            "z_score": 2.5,
        }
        echo_info = {"correction_factor": 0.7, "echo_ratio": 0.3, "independent_sources": 2}
        result = apply_echo_correction(event, echo_info)

        assert result["signal_type"] == "price_change"
        assert result["z_score"] == 2.5
        assert result["ticker"] == "NVDA"

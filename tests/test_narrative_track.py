"""Tests for narrative_track module (Phase 1)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.enrichers.narrative_track import (
    _compute_jaccard,
    _extract_keywords_from_events,
    _extract_tickers_from_events,
    detect_cooling_tracks,
    determine_lifecycle_status,
    generate_narrative_id,
    match_to_existing_tracks,
    update_narrative_tracks,
)


# --- narrative_id generation ---


class TestGenerateNarrativeId:
    def test_deterministic(self):
        nid1 = generate_narrative_id("AI/LLM/自動化", ["nvidia", "gpu", "chip"])
        nid2 = generate_narrative_id("AI/LLM/自動化", ["nvidia", "gpu", "chip"])
        assert nid1 == nid2

    def test_different_category(self):
        nid1 = generate_narrative_id("AI/LLM/自動化", ["nvidia", "gpu"])
        nid2 = generate_narrative_id("規制/政策/地政学", ["nvidia", "gpu"])
        assert nid1 != nid2

    def test_keyword_order_independent(self):
        nid1 = generate_narrative_id("AI/LLM/自動化", ["gpu", "nvidia", "chip"])
        nid2 = generate_narrative_id("AI/LLM/自動化", ["chip", "nvidia", "gpu"])
        assert nid1 == nid2

    def test_contains_category(self):
        nid = generate_narrative_id("AI/LLM/自動化", ["nvidia"])
        assert nid.startswith("AI/LLM/自動化::")

    def test_uses_top5_only(self):
        kw6 = ["a", "b", "c", "d", "e", "f"]
        kw5 = ["a", "b", "c", "d", "e"]
        nid1 = generate_narrative_id("cat", kw6)
        nid2 = generate_narrative_id("cat", kw5)
        assert nid1 == nid2


# --- Jaccard ---


class TestJaccard:
    def test_identical(self):
        assert _compute_jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self):
        assert _compute_jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial(self):
        assert _compute_jaccard({"a", "b", "c"}, {"b", "c", "d"}) == pytest.approx(0.5)

    def test_empty(self):
        assert _compute_jaccard(set(), {"a"}) == 0.0
        assert _compute_jaccard(set(), set()) == 0.0


# --- Keyword extraction ---


class TestExtractKeywords:
    def test_basic(self):
        events = [
            {"summary": "NVIDIA announces new GPU architecture for AI training"},
        ]
        kw = _extract_keywords_from_events(events)
        assert len(kw) > 0

    def test_uses_evidence_titles(self):
        events = [
            {"summary": "", "evidence_titles": ["NVIDIA GPU launch delayed"]},
        ]
        kw = _extract_keywords_from_events(events)
        assert len(kw) > 0

    def test_empty_events(self):
        assert _extract_keywords_from_events([]) == []


# --- Ticker extraction ---


class TestExtractTickers:
    def test_ordered_by_sis(self):
        events = [
            {"ticker": "AMD", "sis": 0.3},
            {"ticker": "NVDA", "sis": 0.9},
            {"ticker": "MSFT", "sis": 0.5},
        ]
        tickers = _extract_tickers_from_events(events)
        assert tickers == ["NVDA", "MSFT", "AMD"]

    def test_deduplicates(self):
        events = [
            {"ticker": "NVDA", "sis": 0.9},
            {"ticker": "NVDA", "sis": 0.3},
        ]
        tickers = _extract_tickers_from_events(events)
        assert tickers == ["NVDA"]


# --- Matching ---


class TestMatchToExistingTracks:
    def test_exact_keyword_match(self):
        tracks = [{
            "category": "AI/LLM/自動化",
            "keywords": ["nvidia", "gpu", "chip"],
            "primary_tickers": ["NVDA"],
            "narrative_id": "test-1",
        }]
        result = match_to_existing_tracks(
            "AI/LLM/自動化", ["nvidia", "gpu", "chip"], ["NVDA"], tracks,
        )
        assert result is not None
        assert result["narrative_id"] == "test-1"

    def test_below_threshold(self):
        tracks = [{
            "category": "AI/LLM/自動化",
            "keywords": ["regulation", "policy"],
            "primary_tickers": ["LMT"],
            "narrative_id": "test-1",
        }]
        result = match_to_existing_tracks(
            "AI/LLM/自動化", ["nvidia", "gpu"], ["NVDA"], tracks,
        )
        assert result is None

    def test_different_category_no_match(self):
        tracks = [{
            "category": "規制/政策/地政学",
            "keywords": ["nvidia", "gpu", "chip"],
            "primary_tickers": ["NVDA"],
            "narrative_id": "test-1",
        }]
        result = match_to_existing_tracks(
            "AI/LLM/自動化", ["nvidia", "gpu", "chip"], ["NVDA"], tracks,
        )
        assert result is None

    def test_ticker_overlap_boosts(self):
        tracks = [{
            "category": "AI/LLM/自動化",
            "keywords": ["nvidia", "gpu", "training", "model"],
            "primary_tickers": ["NVDA", "AMD", "MSFT"],
            "narrative_id": "test-1",
        }]
        # Keywords partially match, but tickers heavily overlap
        result = match_to_existing_tracks(
            "AI/LLM/自動化",
            ["nvidia", "inference", "deployment", "model"],
            ["NVDA", "AMD", "MSFT"],
            tracks,
        )
        assert result is not None

    def test_empty_existing_tracks(self):
        result = match_to_existing_tracks(
            "AI/LLM/自動化", ["nvidia"], ["NVDA"], [],
        )
        assert result is None


# --- Lifecycle ---


class TestLifecycleStatus:
    def test_emerging_day1(self):
        assert determine_lifecycle_status(1, [0.5], 0.3, 1) == "emerging"

    def test_expanding_trend_up(self):
        status = determine_lifecycle_status(3, [0.3, 0.5, 0.7], 0.4, 2)
        assert status == "expanding"

    def test_peak(self):
        status = determine_lifecycle_status(4, [0.3, 0.7, 0.8, 0.79], 0.6, 1)
        assert status == "peak"

    def test_cooling_no_events(self):
        status = determine_lifecycle_status(3, [0.5, 0.6], 0.5, 0)
        assert status == "cooling"

    def test_short_series_2points(self):
        status = determine_lifecycle_status(2, [0.3, 0.5], 0.3, 1)
        assert status == "expanding"

    def test_empty_sis_history(self):
        status = determine_lifecycle_status(2, [], 0.3, 1)
        assert status == "expanding"


# --- Cooling ---


class TestCoolingDetection:
    def test_detects_cooling(self):
        tracks = [
            {"narrative_id": "n1", "category": "AI/LLM/自動化",
             "active_days": 3, "last_seen": "2026-03-06",
             "peak_sis": 0.8, "primary_tickers": ["NVDA"], "status": "expanding"},
        ]
        cooling = detect_cooling_tracks(tracks, set(), "2026-03-07")
        assert len(cooling) == 1
        assert cooling[0]["category"] == "AI/LLM/自動化"

    def test_not_cooling_if_present(self):
        tracks = [
            {"narrative_id": "n1", "category": "AI/LLM/自動化",
             "active_days": 3, "last_seen": "2026-03-06",
             "peak_sis": 0.8, "primary_tickers": ["NVDA"], "status": "expanding"},
        ]
        cooling = detect_cooling_tracks(tracks, {"AI/LLM/自動化"}, "2026-03-07")
        assert len(cooling) == 0

    def test_not_cooling_if_day1(self):
        tracks = [
            {"narrative_id": "n1", "category": "AI/LLM/自動化",
             "active_days": 1, "last_seen": "2026-03-06",
             "peak_sis": 0.3, "primary_tickers": ["NVDA"], "status": "emerging"},
        ]
        cooling = detect_cooling_tracks(tracks, set(), "2026-03-07")
        assert len(cooling) == 0

    def test_skip_inactive(self):
        tracks = [
            {"narrative_id": "n1", "category": "AI/LLM/自動化",
             "active_days": 5, "last_seen": "2026-03-01",
             "peak_sis": 0.8, "primary_tickers": ["NVDA"], "status": "inactive"},
        ]
        cooling = detect_cooling_tracks(tracks, set(), "2026-03-07")
        assert len(cooling) == 0


# --- DB Integration (mock) ---


class TestUpdateNarrativeTracks:
    def _make_mock_db(self, existing_tracks=None):
        db = MagicMock()
        db.get_active_narrative_tracks.return_value = existing_tracks or []
        db.mark_tracks_inactive.return_value = 0
        return db

    def test_new_track_created(self):
        db = self._make_mock_db()
        events = [
            {"ticker": "NVDA", "sis": 0.8, "spp": 0.5,
             "narrative_category": "AI/LLM/自動化",
             "summary": "NVIDIA GPU architecture launch"},
        ]
        result = update_narrative_tracks(events, db, "2026-03-07")
        assert result["new_count"] == 1
        assert result["updated_count"] == 0
        assert db.upsert_narrative_track.call_count == 1

    def test_existing_track_updated(self):
        existing = [{
            "narrative_id": "AI/LLM/自動化::abc123",
            "category": "AI/LLM/自動化",
            "keywords": ["nvidia", "gpu", "architecture", "launch"],
            "primary_tickers": ["NVDA"],
            "start_date": "2026-03-06",
            "last_seen": "2026-03-06",
            "active_days": 1,
            "peak_sis": 0.5,
            "avg_spp": 0.3,
            "status": "emerging",
            "sis_history": [0.5],
        }]
        db = self._make_mock_db(existing)
        events = [
            {"ticker": "NVDA", "sis": 0.8, "spp": 0.6,
             "narrative_category": "AI/LLM/自動化",
             "summary": "NVIDIA GPU architecture improvements announced"},
        ]
        result = update_narrative_tracks(events, db, "2026-03-07")
        assert result["updated_count"] == 1
        assert result["new_count"] == 0

    def test_empty_events(self):
        db = self._make_mock_db()
        result = update_narrative_tracks([], db, "2026-03-07")
        assert result["new_count"] == 0
        assert result["updated_count"] == 0
        assert result["active_tracks"] == []

    def test_cooling_detected(self):
        existing = [{
            "narrative_id": "AI/LLM/自動化::abc123",
            "category": "AI/LLM/自動化",
            "keywords": ["nvidia", "gpu"],
            "primary_tickers": ["NVDA"],
            "start_date": "2026-03-05",
            "last_seen": "2026-03-06",
            "active_days": 2,
            "peak_sis": 0.8,
            "avg_spp": 0.5,
            "status": "expanding",
            "sis_history": [0.5, 0.8],
        }]
        db = self._make_mock_db(existing)
        # No AI events today, but different category
        events = [
            {"ticker": "LMT", "sis": 0.4, "spp": 0.3,
             "narrative_category": "規制/政策/地政学",
             "summary": "Defense regulation update"},
        ]
        result = update_narrative_tracks(events, db, "2026-03-07")
        assert len(result["cooling_tracks"]) == 1
        assert result["cooling_tracks"][0]["category"] == "AI/LLM/自動化"

"""Tests for Structural Persistence Probability (SPP) calculator."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.enrichers.spp import compute_spp, compute_spp_batch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def price_change_event() -> dict:
    """Event driven by a price change signal."""
    return {
        "ticker": "NVDA",
        "signal_type": "price_change",
        "z_score": 3.0,
        "evidence_score": 0.6,
        "diffusion_pattern": "sns_to_tier1",
        "propagation_targets": ["AMD", "TSM"],
    }


@pytest.fixture
def mention_event() -> dict:
    """Event driven only by mention surge."""
    return {
        "ticker": "PLTR",
        "signal_type": "mention_surge",
        "z_score": 5.0,
        "evidence_score": 0.2,
        "diffusion_pattern": "sns_only",
        "propagation_targets": [],
    }


@pytest.fixture
def propagation_event() -> dict:
    """Event with multiple propagation targets."""
    return {
        "ticker": "MSFT",
        "signal_type": "price_change",
        "z_score": 2.5,
        "evidence_score": 0.5,
        "diffusion_pattern": "sns_to_tier2",
        "propagation_targets": ["GOOGL", "AMZN", "META"],
    }


@pytest.fixture
def mock_db_with_history() -> MagicMock:
    """Mock database returning 3 days of history for the same ticker."""
    db = MagicMock()
    db.get_enriched_events_history.return_value = [
        {"ticker": "NVDA", "date": "2026-02-19", "evidence_score": 0.5},
        {"ticker": "NVDA", "date": "2026-02-20", "evidence_score": 0.55},
        {"ticker": "NVDA", "date": "2026-02-21", "evidence_score": 0.6},
    ]
    return db


# ---------------------------------------------------------------------------
# compute_spp
# ---------------------------------------------------------------------------


class TestComputeSpp:
    def test_price_change_no_db(self, price_change_event: dict) -> None:
        """price_change event without db -> SPP in [0, 1]."""
        spp = compute_spp(price_change_event, db=None)
        assert 0.0 <= spp <= 1.0

    def test_mention_only_low_spp(
        self, price_change_event: dict, mention_event: dict
    ) -> None:
        """mention_surge event should produce lower SPP than price_change."""
        spp_mention = compute_spp(mention_event, db=None)
        spp_price = compute_spp(price_change_event, db=None)
        assert spp_mention < spp_price

    def test_propagation_boosts_spp(self, propagation_event: dict) -> None:
        """Event with 3 propagation_targets -> SPP > 0."""
        spp = compute_spp(propagation_event, db=None)
        assert spp > 0.0

    def test_diffusion_factor(self) -> None:
        """tier1_direct event should have higher SPP than sns_only event."""
        tier1_event = {
            "ticker": "X",
            "signal_type": "price_change",
            "z_score": 2.0,
            "evidence_score": 0.5,
            "diffusion_pattern": "tier1_direct",
            "propagation_targets": [],
        }
        sns_event = {
            "ticker": "X",
            "signal_type": "price_change",
            "z_score": 2.0,
            "evidence_score": 0.5,
            "diffusion_pattern": "sns_only",
            "propagation_targets": [],
        }
        spp_tier1 = compute_spp(tier1_event, db=None)
        spp_sns = compute_spp(sns_event, db=None)
        assert spp_tier1 > spp_sns

    def test_with_mock_db(
        self, price_change_event: dict, mock_db_with_history: MagicMock
    ) -> None:
        """Mock db with 3 days of same ticker -> consecutive factor > 0.2."""
        spp = compute_spp(price_change_event, db=mock_db_with_history)
        # With db, consecutive_days_factor = min(3/5, 1.0) = 0.6
        # Without db it would be 0.2.  With db the base consecutive
        # contribution is 0.6*0.25 = 0.15 vs 0.2*0.25 = 0.05 without db.
        # So SPP with db should be notably higher than the no-db default
        # for the consecutive component alone.
        assert spp > 0.0
        # The consecutive days factor when 3 dates present = 3/5 = 0.6
        # Verify the overall SPP benefited from the db history by being
        # greater than the no-db version.
        spp_no_db = compute_spp(price_change_event, db=None)
        assert spp > spp_no_db


# ---------------------------------------------------------------------------
# compute_spp_batch
# ---------------------------------------------------------------------------


class TestComputeSppBatch:
    def test_adds_spp_field(self) -> None:
        """Batch of 3 events -> all get 'spp' key."""
        events = [
            {"ticker": "A", "signal_type": "price_change", "z_score": 2.0},
            {"ticker": "B", "signal_type": "volume_spike", "z_score": 1.5},
            {"ticker": "C", "signal_type": "mention_surge", "z_score": 4.0},
        ]
        result = compute_spp_batch(events, db=None)

        assert len(result) == 3
        for ev in result:
            assert "spp" in ev
            assert isinstance(ev["spp"], float)
            assert 0.0 <= ev["spp"] <= 1.0

    def test_sorted_by_nothing(self) -> None:
        """Original order is preserved after batch computation."""
        events = [
            {"ticker": "Z", "signal_type": "mention_surge", "z_score": 1.0},
            {"ticker": "A", "signal_type": "price_change", "z_score": 5.0},
            {"ticker": "M", "signal_type": "volume_spike", "z_score": 3.0},
        ]
        result = compute_spp_batch(events, db=None)

        assert result[0]["ticker"] == "Z"
        assert result[1]["ticker"] == "A"
        assert result[2]["ticker"] == "M"

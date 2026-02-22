"""Tests for narrative stats baseline layer."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.enrichers.narrative_baseline import (
    compute_category_baselines,
    compute_category_zscore,
    evaluate_narrative_health,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(history_by_window: dict[int, list[dict]] | None = None):
    """Create a mock DB whose ``get_narrative_history`` returns data keyed by window."""
    db = MagicMock()
    if history_by_window is None:
        history_by_window = {}

    def _side_effect(days: int, reference_date=None):
        return history_by_window.get(days, [])

    db.get_narrative_history.side_effect = _side_effect
    return db


def _make_history_rows(category: str, pcts: list[float]) -> list[dict]:
    return [{"category": category, "event_pct": p} for p in pcts]


# ---------------------------------------------------------------------------
# compute_category_baselines
# ---------------------------------------------------------------------------


class TestComputeCategoryBaselines:
    def test_basic_structure(self) -> None:
        rows = (
            _make_history_rows("AI/LLM", [0.5, 0.6, 0.4, 0.55, 0.45])
            + _make_history_rows("Energy", [0.3, 0.2, 0.25, 0.28, 0.22])
        )
        db = _make_db({7: rows, 30: rows, 90: rows})
        result = compute_category_baselines(db, reference_date="2026-01-22")

        assert "baselines" in result
        assert "reference_date" in result
        assert "sample_sizes" in result
        assert result["reference_date"] == "2026-01-22"

        # Default windows
        for w in [7, 30, 90]:
            assert w in result["baselines"]
            assert w in result["sample_sizes"]
            assert "AI/LLM" in result["baselines"][w]
            assert "Energy" in result["baselines"][w]

    def test_baseline_stats_values(self) -> None:
        pcts = [0.5, 0.6, 0.4, 0.55, 0.45]
        rows = _make_history_rows("AI/LLM", pcts)
        db = _make_db({30: rows})
        result = compute_category_baselines(db, reference_date="2026-01-22", windows=[30])

        stats = result["baselines"][30]["AI/LLM"]
        assert stats["n"] == 5
        assert "mean" in stats
        assert "std" in stats
        assert stats["mean"] == pytest.approx(0.5, abs=0.01)
        assert stats["std"] > 0

    def test_empty_history(self) -> None:
        db = _make_db({7: [], 30: [], 90: []})
        result = compute_category_baselines(db, reference_date="2026-01-22")

        for w in [7, 30, 90]:
            assert result["baselines"][w] == {}
            assert result["sample_sizes"][w] == 0

    def test_multiple_windows(self) -> None:
        short_rows = _make_history_rows("AI/LLM", [0.5, 0.6])
        long_rows = _make_history_rows("AI/LLM", [0.5, 0.6, 0.4, 0.55, 0.45])
        db = _make_db({7: short_rows, 30: long_rows})
        result = compute_category_baselines(db, reference_date="2026-01-22", windows=[7, 30])

        assert result["baselines"][7]["AI/LLM"]["n"] == 2
        assert result["baselines"][30]["AI/LLM"]["n"] == 5

    def test_custom_windows(self) -> None:
        rows = _make_history_rows("AI/LLM", [0.5, 0.6, 0.4])
        db = _make_db({14: rows, 60: rows})
        result = compute_category_baselines(db, reference_date="2026-01-22", windows=[14, 60])

        assert 14 in result["baselines"]
        assert 60 in result["baselines"]
        assert 7 not in result["baselines"]

    def test_db_exception_handled(self) -> None:
        db = MagicMock()
        db.get_narrative_history.side_effect = RuntimeError("DB error")
        result = compute_category_baselines(db, reference_date="2026-01-22", windows=[7])

        assert result["baselines"][7] == {}
        assert result["sample_sizes"][7] == 0

    def test_sample_sizes_total(self) -> None:
        rows = (
            _make_history_rows("AI/LLM", [0.5, 0.6, 0.4])
            + _make_history_rows("Energy", [0.3, 0.2])
        )
        db = _make_db({30: rows})
        result = compute_category_baselines(db, reference_date="2026-01-22", windows=[30])

        # 3 AI rows + 2 Energy rows = 5
        assert result["sample_sizes"][30] == 5

    def test_small_sample_uses_pstdev(self) -> None:
        """When n < 3, population stdev (pstdev) is used instead of sample stdev."""
        rows = _make_history_rows("AI/LLM", [0.5, 0.6])
        db = _make_db({7: rows})
        result = compute_category_baselines(db, reference_date="2026-01-22", windows=[7])

        stats = result["baselines"][7]["AI/LLM"]
        assert stats["n"] == 2
        # pstdev of [0.5, 0.6] = 0.05; stdev would be ~0.0707
        assert stats["std"] == pytest.approx(0.05, abs=0.001)

    def test_reference_date_none_uses_today(self) -> None:
        db = _make_db({30: []})
        result = compute_category_baselines(db, reference_date=None, windows=[30])

        assert result["reference_date"] != ""
        # Should be an ISO date string
        assert len(result["reference_date"]) == 10


# ---------------------------------------------------------------------------
# compute_category_zscore
# ---------------------------------------------------------------------------


class TestComputeCategoryZscore:
    @pytest.fixture
    def baseline(self) -> dict:
        return {
            "baselines": {
                30: {
                    "AI/LLM": {"mean": 0.5, "std": 0.1, "n": 10},
                    "Energy": {"mean": 0.3, "std": 0.05, "n": 8},
                }
            },
            "sample_sizes": {30: 18},
        }

    def test_normal_case(self, baseline) -> None:
        result = compute_category_zscore(
            current_pct=0.55, baseline=baseline, window=30, category="AI/LLM"
        )
        assert result["z_score"] is not None
        assert result["z_score"] == pytest.approx(0.5, abs=0.01)
        assert result["is_anomalous"] is False
        assert result["status"] == "normal"
        assert result["mean"] == 0.5
        assert result["std"] == 0.1
        assert result["window"] == 30

    def test_anomalous_high_zscore(self, baseline) -> None:
        # 0.8 is 3 std devs above mean of 0.5 with std 0.1
        result = compute_category_zscore(
            current_pct=0.8, baseline=baseline, window=30, category="AI/LLM"
        )
        assert result["z_score"] is not None
        assert abs(result["z_score"]) > 2.0
        assert result["is_anomalous"] is True
        assert result["status"] == "anomalous"

    def test_elevated_status(self, baseline) -> None:
        # z_score between 1.0 and 2.0 -> "elevated"
        result = compute_category_zscore(
            current_pct=0.65, baseline=baseline, window=30, category="AI/LLM"
        )
        assert result["z_score"] is not None
        assert 1.0 <= abs(result["z_score"]) < 2.0
        assert result["status"] == "elevated"

    def test_insufficient_data_small_n(self) -> None:
        baseline = {
            "baselines": {
                30: {
                    "AI/LLM": {"mean": 0.5, "std": 0.1, "n": 2},
                }
            }
        }
        result = compute_category_zscore(
            current_pct=0.55, baseline=baseline, window=30, category="AI/LLM"
        )
        assert result["z_score"] is None
        assert result["status"] == "insufficient_data"
        assert result["is_anomalous"] is False

    def test_insufficient_data_zero_std(self) -> None:
        baseline = {
            "baselines": {
                30: {
                    "AI/LLM": {"mean": 0.5, "std": 0.0, "n": 10},
                }
            }
        }
        result = compute_category_zscore(
            current_pct=0.55, baseline=baseline, window=30, category="AI/LLM"
        )
        assert result["z_score"] is None
        assert result["status"] == "insufficient_data"
        assert result["is_anomalous"] is False
        # With std=0, normal_range defaults to (0.0, 1.0)
        assert result["normal_range"] == (0.0, 1.0)

    def test_missing_category(self, baseline) -> None:
        result = compute_category_zscore(
            current_pct=0.5, baseline=baseline, window=30, category="Nonexistent"
        )
        assert result["z_score"] is None
        assert result["status"] == "insufficient_data"
        assert result["mean"] is None
        assert result["std"] is None

    def test_missing_window(self, baseline) -> None:
        result = compute_category_zscore(
            current_pct=0.5, baseline=baseline, window=7, category="AI/LLM"
        )
        assert result["z_score"] is None
        assert result["status"] == "insufficient_data"

    def test_normal_range_clamped(self, baseline) -> None:
        result = compute_category_zscore(
            current_pct=0.55, baseline=baseline, window=30, category="AI/LLM"
        )
        low, high = result["normal_range"]
        assert low >= 0.0
        assert high <= 1.0
        assert low < high

    def test_pre_extracted_stats_no_category(self) -> None:
        """When category is None, baseline is treated as pre-extracted stats."""
        stats = {"mean": 0.5, "std": 0.1, "n": 10}
        result = compute_category_zscore(
            current_pct=0.55, baseline=stats, window=30, category=None
        )
        assert result["z_score"] is not None
        assert result["z_score"] == pytest.approx(0.5, abs=0.01)

    def test_negative_zscore(self, baseline) -> None:
        # Below mean
        result = compute_category_zscore(
            current_pct=0.2, baseline=baseline, window=30, category="AI/LLM"
        )
        assert result["z_score"] is not None
        assert result["z_score"] < 0
        assert abs(result["z_score"]) > 2.0
        assert result["is_anomalous"] is True


# ---------------------------------------------------------------------------
# evaluate_narrative_health
# ---------------------------------------------------------------------------


class TestEvaluateNarrativeHealth:
    @pytest.fixture
    def baselines(self) -> dict:
        return {
            "baselines": {
                30: {
                    "AI/LLM": {"mean": 0.5, "std": 0.1, "n": 10},
                    "Energy": {"mean": 0.3, "std": 0.05, "n": 8},
                    "Finance": {"mean": 0.2, "std": 0.04, "n": 6},
                }
            },
            "sample_sizes": {30: 24},
        }

    def test_all_normal(self, baselines) -> None:
        distribution = {
            "AI/LLM": {"count": 5, "pct": 0.5},
            "Energy": {"count": 3, "pct": 0.3},
            "Finance": {"count": 2, "pct": 0.2},
        }
        result = evaluate_narrative_health(distribution, baselines, window=30)

        assert result["window"] == 30
        assert result["sample_size"] == 24
        assert len(result["anomalous_categories"]) == 0
        assert result["health_summary"] == "全カテゴリが統計的正常範囲"
        assert "AI/LLM" in result["category_scores"]
        assert "Energy" in result["category_scores"]
        assert "Finance" in result["category_scores"]

    def test_some_anomalous(self, baselines) -> None:
        distribution = {
            "AI/LLM": {"count": 8, "pct": 0.8},  # 3 std above mean -> anomalous
            "Energy": {"count": 1, "pct": 0.1},  # 4 std below mean -> anomalous
            "Finance": {"count": 1, "pct": 0.1},  # within range
        }
        result = evaluate_narrative_health(distribution, baselines, window=30)

        assert len(result["anomalous_categories"]) >= 1
        assert "AI/LLM" in result["anomalous_categories"]
        assert "カテゴリが統計的異常範囲" in result["health_summary"]

    def test_empty_distribution(self, baselines) -> None:
        result = evaluate_narrative_health({}, baselines, window=30)

        # Categories in baseline but absent today should get z-scored with pct=0.0
        assert "AI/LLM" in result["category_scores"]
        assert result["category_scores"]["AI/LLM"]["current_pct"] == 0.0

    def test_missing_categories_in_baseline(self) -> None:
        """Categories in distribution but not in baselines -> insufficient_data."""
        baselines = {
            "baselines": {30: {}},
            "sample_sizes": {30: 0},
        }
        distribution = {
            "AI/LLM": {"count": 5, "pct": 0.5},
        }
        result = evaluate_narrative_health(distribution, baselines, window=30)

        assert "AI/LLM" in result["category_scores"]
        assert result["category_scores"]["AI/LLM"]["status"] == "insufficient_data"
        assert len(result["anomalous_categories"]) == 0

    def test_category_scores_structure(self, baselines) -> None:
        distribution = {"AI/LLM": {"count": 5, "pct": 0.5}}
        result = evaluate_narrative_health(distribution, baselines, window=30)

        score = result["category_scores"]["AI/LLM"]
        assert "current_pct" in score
        assert "z_score" in score
        assert "mean" in score
        assert "std" in score
        assert "normal_range" in score
        assert "status" in score
        assert isinstance(score["normal_range"], list)

    def test_absent_category_flagged_anomalous(self) -> None:
        """A category present in baseline but absent today with pct=0.0 can be anomalous."""
        baselines = {
            "baselines": {
                30: {
                    "AI/LLM": {"mean": 0.5, "std": 0.1, "n": 10},
                }
            },
            "sample_sizes": {30: 10},
        }
        # Empty distribution -- AI/LLM is absent
        result = evaluate_narrative_health({}, baselines, window=30)

        # 0.0 vs mean=0.5 with std=0.1 -> z = -5.0 -> anomalous
        assert "AI/LLM" in result["anomalous_categories"]
        assert result["category_scores"]["AI/LLM"]["status"] == "anomalous"

    def test_anomalous_count_in_summary(self, baselines) -> None:
        distribution = {
            "AI/LLM": {"count": 8, "pct": 0.8},
            "Energy": {"count": 1, "pct": 0.05},
        }
        result = evaluate_narrative_health(distribution, baselines, window=30)

        n_anom = len(result["anomalous_categories"])
        if n_anom > 0:
            assert f"{n_anom}カテゴリが統計的異常範囲" == result["health_summary"]
        else:
            assert result["health_summary"] == "全カテゴリが統計的正常範囲"

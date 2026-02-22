"""Tests for narrative chart generation (matplotlib)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.enrichers.narrative_chart import (
    generate_charts,
    generate_media_diffusion_chart,
    generate_narrative_trend_chart,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def trend_data_3days() -> list[dict[str, Any]]:
    """Three days of narrative trend data with two categories."""
    return [
        {
            "date": "2026-02-19",
            "categories": {"AI/LLM/\u81ea\u52d5\u5316": 0.6, "\u30a8\u30cd\u30eb\u30ae\u30fc/\u8cc7\u6e90": 0.4},
        },
        {
            "date": "2026-02-20",
            "categories": {"AI/LLM/\u81ea\u52d5\u5316": 0.55, "\u30a8\u30cd\u30eb\u30ae\u30fc/\u8cc7\u6e90": 0.45},
        },
        {
            "date": "2026-02-21",
            "categories": {"AI/LLM/\u81ea\u52d5\u5316": 0.5, "\u30a8\u30cd\u30eb\u30ae\u30fc/\u8cc7\u6e90": 0.5},
        },
    ]


@pytest.fixture
def propagation_data() -> dict[str, int]:
    """Sample media diffusion data."""
    return {
        "sns_only": 5,
        "sns_to_tier2": 3,
        "sns_to_tier1": 2,
        "tier1_direct": 1,
    }


# ---------------------------------------------------------------------------
# generate_narrative_trend_chart
# ---------------------------------------------------------------------------


class TestGenerateNarrativeTrendChart:
    def test_generates_png(
        self, tmp_path: Path, trend_data_3days: list[dict[str, Any]]
    ) -> None:
        """Pass 3-day trend data, temp output -> file exists and is PNG."""
        output = tmp_path / "trend.png"

        result = generate_narrative_trend_chart(trend_data_3days, output)

        assert result is not None
        assert Path(result).exists()
        # PNG files start with the 8-byte signature \x89PNG\r\n\x1a\n
        content = Path(result).read_bytes()
        assert content[:4] == b"\x89PNG"

    def test_empty_data(self, tmp_path: Path) -> None:
        """Empty list -> returns None."""
        output = tmp_path / "trend.png"

        result = generate_narrative_trend_chart([], output)

        assert result is None
        assert not output.exists()

    def test_returns_path(
        self, tmp_path: Path, trend_data_3days: list[dict[str, Any]]
    ) -> None:
        """Returns the output path as a string."""
        output = tmp_path / "trend.png"

        result = generate_narrative_trend_chart(trend_data_3days, output)

        assert isinstance(result, str)
        assert result == str(output)


# ---------------------------------------------------------------------------
# generate_media_diffusion_chart
# ---------------------------------------------------------------------------


class TestGenerateMediaDiffusionChart:
    def test_generates_png(
        self, tmp_path: Path, propagation_data: dict[str, int]
    ) -> None:
        """Pass propagation data -> file exists and is PNG."""
        output = tmp_path / "diffusion.png"

        result = generate_media_diffusion_chart(propagation_data, output)

        assert result is not None
        assert Path(result).exists()
        content = Path(result).read_bytes()
        assert content[:4] == b"\x89PNG"

    def test_empty_data(self, tmp_path: Path) -> None:
        """Empty dict -> returns None."""
        output = tmp_path / "diffusion.png"

        result = generate_media_diffusion_chart({}, output)

        assert result is None
        assert not output.exists()


# ---------------------------------------------------------------------------
# generate_charts
# ---------------------------------------------------------------------------


class TestGenerateCharts:
    def test_both_charts(
        self,
        tmp_path: Path,
        trend_data_3days: list[dict[str, Any]],
        propagation_data: dict[str, int],
    ) -> None:
        """Generates both chart files in a temp directory."""
        result = generate_charts(
            narrative_trend=trend_data_3days,
            propagation_data=propagation_data,
            output_dir=tmp_path,
        )

        assert result["trend_chart"] is not None
        assert result["diffusion_chart"] is not None
        assert Path(result["trend_chart"]).exists()
        assert Path(result["diffusion_chart"]).exists()
        # Verify the files are in the expected directory
        assert Path(result["trend_chart"]).parent == tmp_path
        assert Path(result["diffusion_chart"]).parent == tmp_path

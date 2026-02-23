"""Integration tests for market_scope (US/JP/GLOBAL) routing.

Verifies that config.active_tickers, active_rss_feeds, and active_sector_map
return correct subsets based on market_scope. Also verifies report templates
render correctly for each mode.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from app.config import AppConfig, load_config


def _write_config(tmp_path: Path, scope: str) -> Path:
    data = {
        "market_scope": scope,
        "tickers": ["NVDA", "MSFT"],
        "jp_tickers": ["7203.T", "6758.T"],
        "rss_feeds": [{"name": "TC", "url": "https://example.com/us"}],
        "jp_rss_feeds": [{"name": "Nikkei", "url": "https://example.com/jp"}],
        "sector_map": {"AI": ["NVDA", "MSFT"]},
        "jp_sector_map": {"JP_Tech": ["6758.T"]},
        "database": {"path": "test.db"},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


class TestMarketScopeUS:
    def test_active_tickers_us(self, tmp_path: Path) -> None:
        cfg = load_config(_write_config(tmp_path, "US"))
        assert cfg.active_tickers == ["NVDA", "MSFT"]

    def test_active_rss_feeds_us(self, tmp_path: Path) -> None:
        cfg = load_config(_write_config(tmp_path, "US"))
        assert len(cfg.active_rss_feeds) == 1
        assert cfg.active_rss_feeds[0].name == "TC"

    def test_active_sector_map_us(self, tmp_path: Path) -> None:
        cfg = load_config(_write_config(tmp_path, "US"))
        assert "AI" in cfg.active_sector_map
        assert "JP_Tech" not in cfg.active_sector_map


class TestMarketScopeJP:
    def test_active_tickers_jp(self, tmp_path: Path) -> None:
        cfg = load_config(_write_config(tmp_path, "JP"))
        assert cfg.active_tickers == ["7203.T", "6758.T"]

    def test_active_rss_feeds_jp(self, tmp_path: Path) -> None:
        cfg = load_config(_write_config(tmp_path, "JP"))
        assert len(cfg.active_rss_feeds) == 1
        assert cfg.active_rss_feeds[0].name == "Nikkei"

    def test_active_sector_map_jp(self, tmp_path: Path) -> None:
        cfg = load_config(_write_config(tmp_path, "JP"))
        assert "JP_Tech" in cfg.active_sector_map
        assert "AI" not in cfg.active_sector_map


class TestMarketScopeGLOBAL:
    def test_active_tickers_global(self, tmp_path: Path) -> None:
        cfg = load_config(_write_config(tmp_path, "GLOBAL"))
        assert cfg.active_tickers == ["NVDA", "MSFT", "7203.T", "6758.T"]

    def test_active_rss_feeds_global(self, tmp_path: Path) -> None:
        cfg = load_config(_write_config(tmp_path, "GLOBAL"))
        assert len(cfg.active_rss_feeds) == 2

    def test_active_sector_map_global(self, tmp_path: Path) -> None:
        cfg = load_config(_write_config(tmp_path, "GLOBAL"))
        assert "AI" in cfg.active_sector_map
        assert "JP_Tech" in cfg.active_sector_map


class TestDefaultScope:
    def test_default_is_us(self, tmp_path: Path) -> None:
        """Config without market_scope defaults to US."""
        data = {
            "tickers": ["AAPL"],
            "jp_tickers": ["7203.T"],
            "database": {"path": "test.db"},
        }
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump(data), encoding="utf-8")
        cfg = load_config(path)
        assert cfg.market_scope == "US"
        assert cfg.active_tickers == ["AAPL"]


class TestReportRendering:
    """Verify templates render without errors for each market_scope."""

    def test_structural_us(self) -> None:
        from app.reporter.daily_report import generate_structural_report
        md = generate_structural_report(
            events=[], structural_themes=[], causal_chains=[],
            hypotheses=[], propagation=[], structural_questions=[],
            tracking_queries=[], date="2026-02-23", market_scope="US",
        )
        assert "構造変化観測レポート" in md
        assert "(GLOBAL)" not in md

    def test_structural_global(self) -> None:
        from app.reporter.daily_report import generate_structural_report
        events = [
            {"ticker": "NVDA", "shock_type": "Tech shock", "sis": 0.5,
             "evidence_score": 0.5, "spp": 0.4, "signal_type": "price_change",
             "summary": "Test"},
            {"ticker": "7203.T", "shock_type": "Execution signal", "sis": 0.3,
             "evidence_score": 0.3, "spp": 0.2, "signal_type": "price_change",
             "summary": "テスト"},
        ]
        md = generate_structural_report(
            events=events, structural_themes=[], causal_chains=[],
            hypotheses=[], propagation=[], structural_questions=[],
            tracking_queries=[], date="2026-02-23", market_scope="GLOBAL",
        )
        assert "(GLOBAL)" in md
        assert "[US]" in md
        assert "[JP]" in md
        # JP ticker should show Japanese display name
        assert "7203.T（トヨタ）" in md
        # US ticker should NOT get a display name suffix
        assert "NVDA（" not in md

    def test_structural_jp(self) -> None:
        from app.reporter.daily_report import generate_structural_report
        events = [
            {"ticker": "7203.T", "shock_type": "Execution signal", "sis": 0.3,
             "evidence_score": 0.3, "spp": 0.2, "signal_type": "price_change",
             "summary": "テスト"},
        ]
        md = generate_structural_report(
            events=events, structural_themes=[], causal_chains=[],
            hypotheses=[], propagation=[], structural_questions=[],
            tracking_queries=[], date="2026-02-23", market_scope="JP",
        )
        assert "(JP)" in md
        # JP-only mode should NOT show market tags
        assert "[JP]" not in md
        assert "[US]" not in md

    def test_weekly_global(self) -> None:
        from app.reporter.daily_report import generate_weekly_report
        analysis = {
            "period": "7日間",
            "shock_type_distribution": {},
            "narrative_trend": [],
        }
        md = generate_weekly_report(analysis=analysis, date="2026-02-23", market_scope="GLOBAL")
        assert "(GLOBAL)" in md

    def test_monthly_global_cross_market(self) -> None:
        from app.reporter.daily_report import generate_monthly_report
        analysis = {
            "period": "30日間",
            "narrative_lifecycle": {},
            "lifecycle_stats": {},
            "hypothesis_evaluations": [],
            "hypothesis_scorecard": {},
            "regime_arc": {"regime_composition": {}, "transitions": [], "dominant": "normal",
                           "stability_score": 0.5, "volatility_trend": "横ばい"},
            "structural_persistence": {"core_tickers": [], "transient_tickers": [],
                                        "turnover_rate": 0.0},
            "month_over_month": {"available": False},
            "shock_type_distribution": {},
            "propagation_structure": {},
            "forward_posture": {"attention_reallocation": [], "watch_tickers": [],
                                "regime_outlook": ""},
            "narrative_trend": [],
            "regime_history": [],
            "reaction_lag": None,
            "watch_ticker_followup": None,
            "extinction_chains": None,
            "drift_evaluation": None,
            "response_profile": None,
            "direction_analysis": None,
            "regime_cross": None,
            "exhaustion": None,
            "exhaustion_evaluation": None,
            "cross_market": {
                "narrative_comparison": [
                    {"category": "AI/LLM/自動化", "us_pct": 0.5, "jp_pct": 0.2,
                     "delta_pt": 0.3, "notable": True},
                ],
                "reaction_speed_comparison": {
                    "us": {"total": 5, "avg_lag": 2.0, "immediate_rate": 0.4, "no_reaction_rate": 0.2},
                    "jp": {"total": 3, "avg_lag": 3.0, "immediate_rate": 0.33, "no_reaction_rate": 0.33},
                },
                "transplant_candidates": [],
            },
        }
        md = generate_monthly_report(analysis=analysis, date="2026-02-23", market_scope="GLOBAL")
        assert "(GLOBAL)" in md
        assert "日米ナラティブ比較" in md
        assert "日米反応速度比較" in md
        assert "ナラティブ移植候補" in md

    def test_monthly_us_no_cross_market(self) -> None:
        from app.reporter.daily_report import generate_monthly_report
        analysis = {
            "period": "30日間",
            "narrative_lifecycle": {},
            "lifecycle_stats": {},
            "hypothesis_evaluations": [],
            "hypothesis_scorecard": {},
            "regime_arc": {"regime_composition": {}, "transitions": [], "dominant": "normal",
                           "stability_score": 0.5, "volatility_trend": "横ばい"},
            "structural_persistence": {"core_tickers": [], "transient_tickers": [],
                                        "turnover_rate": 0.0},
            "month_over_month": {"available": False},
            "shock_type_distribution": {},
            "propagation_structure": {},
            "forward_posture": {"attention_reallocation": [], "watch_tickers": [],
                                "regime_outlook": ""},
            "narrative_trend": [],
            "regime_history": [],
            "reaction_lag": None,
            "watch_ticker_followup": None,
            "extinction_chains": None,
            "drift_evaluation": None,
            "response_profile": None,
            "direction_analysis": None,
            "regime_cross": None,
            "exhaustion": None,
            "exhaustion_evaluation": None,
            "cross_market": None,
        }
        md = generate_monthly_report(analysis=analysis, date="2026-02-23", market_scope="US")
        assert "日米ナラティブ比較" not in md

    def test_structural_global_market_summary_and_regime(self) -> None:
        """GLOBAL structural report renders 市場別概要, narrative, and regime sections."""
        from app.reporter.daily_report import generate_structural_report

        events = [
            {"ticker": "NVDA", "shock_type": "Tech shock", "sis": 0.5,
             "evidence_score": 0.5, "spp": 0.4, "signal_type": "price_change",
             "summary": "GPU demand surge"},
            {"ticker": "MSFT", "shock_type": "Tech shock", "sis": 0.4,
             "evidence_score": 0.4, "spp": 0.3, "signal_type": "price_change",
             "summary": "Cloud growth"},
            {"ticker": "7203.T", "shock_type": "Execution signal", "sis": 0.3,
             "evidence_score": 0.3, "spp": 0.2, "signal_type": "price_change",
             "summary": "EV production ramp"},
        ]

        narrative_index = {
            "basis": "全イベント",
            "basis_events": 3,
            "total_events": 3,
            "category_distribution": {
                "AI/LLM/自動化": {"count": 2, "pct": 0.67},
                "製造・産業": {"count": 1, "pct": 0.33},
            },
            "ai_ratio": 0.67,
            "top1_concentration": 0.67,
            "historical_avg": None,
            "warning_flags": [],
        }
        narrative_index_us = {
            "category_distribution": {
                "AI/LLM/自動化": {"count": 2, "pct": 1.0},
            },
            "ai_ratio": 1.0,
            "top1_concentration": 1.0,
        }
        narrative_index_jp = {
            "category_distribution": {
                "製造・産業": {"count": 1, "pct": 1.0},
            },
            "ai_ratio": 0.0,
            "top1_concentration": 1.0,
        }

        regime_info = {
            "regime": "normal",
            "avg_volatility": 0.18,
            "declining_pct": 0.33,
            "regime_confidence": 0.56,
            "spp_weights": {
                "consecutive_days": 0.25, "evidence_trend": 0.25,
                "price_trend": 0.15, "media_diffusion": 0.20,
                "sector_propagation": 0.15,
            },
        }
        regime_info_us = {
            "regime": "normal",
            "avg_volatility": 0.15,
            "declining_pct": 0.0,
            "regime_confidence": 0.8,
        }
        regime_info_jp = {
            "regime": "high_vol",
            "avg_volatility": 0.30,
            "declining_pct": 1.0,
            "regime_confidence": 0.4,
        }

        md = generate_structural_report(
            events=events,
            structural_themes=[],
            causal_chains=[],
            hypotheses=[],
            propagation=[],
            structural_questions=[],
            tracking_queries=[],
            date="2026-02-23",
            market_scope="GLOBAL",
            narrative_index=narrative_index,
            narrative_index_us=narrative_index_us,
            narrative_index_jp=narrative_index_jp,
            regime_info=regime_info,
            regime_info_us=regime_info_us,
            regime_info_jp=regime_info_jp,
        )

        # 市場別概要 section with US/JP event counts
        assert "市場別概要" in md
        # US events: NVDA + MSFT = 2, JP events: 7203.T = 1
        assert "| US |" in md
        assert "| JP |" in md

        # Narrative distribution sections for each market
        assert "ナラティブ分布" in md
        assert "US市場ナラティブ分布" in md
        assert "JP市場ナラティブ分布" in md

        # Regime section renders without error
        assert "市場レジーム" in md
        assert "市場別レジーム" in md
        # JP regime is high_vol -> should show 高ボラティリティ
        assert "高ボラティリティ" in md


class TestInvalidScope:
    """Verify that an invalid market_scope falls back to US behavior."""

    def test_invalid_scope_defaults_to_us_tickers(self, tmp_path: Path) -> None:
        """Config with market_scope='INVALID' should behave like US (fallback)."""
        cfg = load_config(_write_config(tmp_path, "INVALID"))
        # Since the code uses if/elif for JP/GLOBAL and falls through to US,
        # active_tickers should return the US tickers list.
        assert cfg.market_scope == "INVALID"
        assert cfg.active_tickers == ["NVDA", "MSFT"]

    def test_invalid_scope_defaults_to_us_rss(self, tmp_path: Path) -> None:
        """Invalid scope returns US RSS feeds (fallback behavior)."""
        cfg = load_config(_write_config(tmp_path, "INVALID"))
        assert len(cfg.active_rss_feeds) == 1
        assert cfg.active_rss_feeds[0].name == "TC"

    def test_invalid_scope_defaults_to_us_sector_map(self, tmp_path: Path) -> None:
        """Invalid scope returns US sector map (fallback behavior)."""
        cfg = load_config(_write_config(tmp_path, "INVALID"))
        assert "AI" in cfg.active_sector_map
        assert "JP_Tech" not in cfg.active_sector_map

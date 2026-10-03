"""Tests for signal calibration (realized outcomes of SPP / mention surges)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock

from app.enrichers.signal_calibration import (
    MIN_SAMPLES,
    event_session_index,
    compute_signal_calibration,
)
from app.reporter.daily_report import generate_weekly_report


def _sessions(n: int, start: date = date(2026, 6, 1)) -> list[str]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


DATES = _sessions(80)
EVENT_IDX = 40


def _trend_series(up_after_event: bool) -> list[dict[str, Any]]:
    """Flat-ish series, +10% jump at EVENT_IDX, then a steady drift."""
    closes, price = [], 100.0
    for i, _ in enumerate(DATES):
        if i == EVENT_IDX:
            price *= 1.10
        elif i > EVENT_IDX:
            price *= 1.005 if up_after_event else 0.995
        else:
            price *= 1.001 if i % 2 else 0.999
        closes.append(price)
    return [{"timestamp": f"{d}T00:00:00-04:00", "close": c} for d, c in zip(DATES, closes)]


def _db(events: list[dict[str, Any]], series_by_ticker: dict[str, list[dict[str, Any]]]) -> MagicMock:
    db = MagicMock()
    db.get_enriched_events_history.return_value = events
    db.get_price_data_range.side_effect = lambda t, s, e: series_by_ticker.get(t, [])
    return db


def _price_event(ticker: str, spp: float) -> dict[str, Any]:
    d = DATES[EVENT_IDX]
    return {"date": d, "ticker": ticker, "signal_type": "price_change", "spp": spp,
            "summary": "前日比+10.0%の価格変動", "created_at": f"{d} 23:00:00"}


class TestEventSession:
    def test_run_after_close_maps_to_same_session(self) -> None:
        series = [(d, 1.0) for d in DATES]
        e = {"created_at": f"{DATES[10]} 23:30:00"}
        assert event_session_index(series, e) == 10

    def test_run_before_close_maps_to_previous_session(self) -> None:
        series = [(d, 1.0) for d in DATES]
        e = {"created_at": f"{DATES[10]} 15:00:00"}
        assert event_session_index(series, e) == 9


class TestComputeSignalCalibration:
    def test_high_spp_continuation_measured(self) -> None:
        tickers = [f"T{i}" for i in range(MIN_SAMPLES + 2)]
        events = [_price_event(t, 0.7) for t in tickers]
        series = {t: _trend_series(up_after_event=True) for t in tickers}
        result = compute_signal_calibration(_db(events, series), DATES[-1], lookback_days=120)
        high = result["spp_buckets"][0]
        assert high["label"].startswith("SPP≥")
        assert high["cont5"] == 1.0
        assert high["cont20"] == 1.0

    def test_reversal_gives_zero_continuation(self) -> None:
        tickers = [f"T{i}" for i in range(MIN_SAMPLES)]
        events = [_price_event(t, 0.7) for t in tickers]
        series = {t: _trend_series(up_after_event=False) for t in tickers}
        result = compute_signal_calibration(_db(events, series), DATES[-1], lookback_days=120)
        assert result["spp_buckets"][0]["cont5"] == 0.0

    def test_small_sample_reported_as_none(self) -> None:
        events = [_price_event("T0", 0.7)]
        result = compute_signal_calibration(
            _db(events, {"T0": _trend_series(True)}), DATES[-1], lookback_days=120,
        )
        assert result["spp_buckets"][0]["cont5"] is None
        assert result["spp_buckets"][0]["n5"] == 1

    def test_repeated_summary_counted_once(self) -> None:
        e1 = _price_event("T0", 0.7)
        e2 = dict(e1, date=DATES[EVENT_IDX + 1], created_at=f"{DATES[EVENT_IDX + 1]} 23:00:00")
        result = compute_signal_calibration(
            _db([e1, e2], {"T0": _trend_series(True)}), DATES[-1], lookback_days=120,
        )
        assert result["event_count"] == 1

    def test_mention_surge_coincident_with_move(self) -> None:
        tickers = [f"T{i}" for i in range(MIN_SAMPLES)]
        d = DATES[EVENT_IDX]
        events = [{"date": d, "ticker": t, "signal_type": "mention_surge", "spp": 0.5,
                   "summary": "8件の言及（通常の2.6倍）", "created_at": f"{d} 23:00:00"}
                  for t in tickers]
        series = {t: _trend_series(True) for t in tickers}
        m = compute_signal_calibration(_db(events, series), DATES[-1], lookback_days=120)["mention_surge"]
        assert m["n"] == MIN_SAMPLES
        assert m["coincident_rate"] == 1.0
        assert m["baseline_coincident_rate"] < 0.1

    def test_no_events(self) -> None:
        result = compute_signal_calibration(_db([], {}), DATES[-1])
        assert result["event_count"] == 0


class TestWeeklyRendering:
    def test_calibration_section_rendered(self) -> None:
        analysis = {"signal_calibration": {
            "lookback_days": 120, "event_count": 289,
            "spp_buckets": [
                {"label": "SPP≥0.6", "n5": 29, "cont5": 0.586, "n20": 27, "cont20": 0.519},
                {"label": "SPP<0.6", "n5": 3, "cont5": None, "n20": 3, "cont20": None},
            ],
            "mention_surge": {"n": 110, "coincident_rate": 0.10, "subsequent_rate": 0.28,
                              "baseline_coincident_rate": 0.065, "baseline_subsequent_rate": 0.17},
        }}
        md = generate_weekly_report(analysis=analysis, date="2026-10-03")
        assert "## シグナル実績検証" in md
        assert "| SPP≥0.6 | 59%（n=29） | 52%（n=27） |" in md
        assert "サンプル不足（n=3）" in md
        assert "| 同じ取引日に大きな値動き（±2σ） | 10% | 6% |" in md

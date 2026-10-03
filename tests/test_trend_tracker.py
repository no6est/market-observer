"""Tests for the medium-term trend board and event follow-ups."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock

from app.enrichers.signal_calibration import locate_move_session
from app.enrichers.trend_tracker import compute_event_followups, compute_trend_board
from app.reporter.daily_report import generate_weekly_report


def _sessions(n: int, end: date = date(2026, 10, 2)) -> list[str]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return list(reversed(out))


DATES = _sessions(100)
REF = "2026-10-03"


def _rows(closes: list[float]) -> list[dict[str, Any]]:
    return [{"timestamp": f"{d}T00:00:00-04:00", "close": c} for d, c in zip(DATES[-len(closes):], closes)]


def _steady_uptrend() -> list[float]:
    # +0.8% / -0.2% alternating: strong drift relative to its volatility
    out, p = [], 100.0
    for i in range(len(DATES)):
        p *= 1.008 if i % 2 else 0.998
        out.append(p)
    return out


def _noise() -> list[float]:
    out, p = [], 100.0
    for i in range(len(DATES)):
        p *= 1.02 if i % 2 else 1 / 1.02
        out.append(p)
    return out


def _db(prices: dict[str, list[float]], events: list[dict[str, Any]] | None = None,
        articles: list[dict[str, Any]] | None = None) -> MagicMock:
    db = MagicMock()
    db.get_price_data_range.side_effect = lambda t, s, e: [r for r in _rows(prices.get(t, [])) if s <= r["timestamp"][:10] <= e]
    db.get_enriched_events_history.return_value = events or []
    db.get_articles_by_date_range.return_value = articles or []
    return db


class TestTrendBoard:
    def test_detects_uptrend_and_flags_under_coverage(self) -> None:
        events = [{"ticker": "NVDA", "signal_type": "mention_surge", "summary": f"s{i}"} for i in range(5)]
        db = _db({"DDOG": _steady_uptrend(), "NVDA": _noise(), "MSFT": _noise()}, events)
        board = compute_trend_board(db, ["DDOG", "NVDA", "MSFT"], REF)
        top = board["rows"][0]
        assert top["ticker"] == "DDOG"
        assert top["direction"] == "up"
        assert top["trend_z"] >= 2.0
        assert top["return_long"] > 0.15
        assert top["under_covered"] is True
        assert {r["ticker"]: r["direction"] for r in board["rows"]}["NVDA"] == "none"

    def test_counts_articles_by_alias(self) -> None:
        articles = [{"title": "Datadog beats estimates"}, {"title": "Unrelated"}]
        board = compute_trend_board(_db({"DDOG": _steady_uptrend()}, articles=articles), ["DDOG"], REF)
        assert board["rows"][0]["article_count"] == 1

    def test_short_history_skipped(self) -> None:
        board = compute_trend_board(_db({"NEW": [100.0] * 30}), ["NEW"], REF)
        assert board["rows"] == []


def _flat_then(move: float, after: float, n_after: int) -> list[float]:
    closes = [100.0] * (len(DATES) - n_after - 1)
    closes.append(closes[-1] * (1 + move))
    for _ in range(n_after):
        closes.append(closes[-1] * (1 + after / n_after))
    return closes


def _event(ticker: str, pct: float, n_after: int) -> dict[str, Any]:
    d = DATES[-1 - n_after]
    sign = "+" if pct >= 0 else ""
    return {"date": d, "ticker": ticker, "signal_type": "price_change",
            "summary": f"前日比{sign}{pct}%の価格変動", "created_at": f"{d} 23:00:00"}


class TestEventFollowups:
    def test_status_classification(self) -> None:
        prices = {
            "UP": _flat_then(0.10, 0.05, 5),     # +10% then further up
            "REV": _flat_then(0.10, -0.08, 5),   # gave back most of it
            "PART": _flat_then(0.10, -0.02, 5),  # gave back a little
        }
        events = [_event("UP", 10.0, 5), _event("REV", 10.0, 5), _event("PART", 10.0, 5)]
        res = {f["ticker"]: f for f in compute_event_followups(_db(prices, events), REF)}
        assert res["UP"]["status"] == "continued"
        assert res["REV"]["status"] == "reversed"
        assert res["PART"]["status"] == "partial"
        assert res["UP"]["sessions"] == 5

    def test_small_moves_and_repeats_excluded(self) -> None:
        prices = {"A": _flat_then(0.10, 0.0, 5), "B": _flat_then(0.03, 0.0, 5)}
        e = _event("A", 10.0, 5)
        repeat = dict(e, date=DATES[-3], created_at=f"{DATES[-3]} 23:00:00")
        res = compute_event_followups(_db(prices, [e, repeat, _event("B", 3.0, 5)]), REF)
        assert [f["ticker"] for f in res] == ["A"]

    def test_late_report_anchored_to_actual_move(self) -> None:
        # Move happened 5 sessions ago but was reported 2 sessions later.
        prices = {"A": _flat_then(0.10, 0.0, 5)}
        late = dict(_event("A", 10.0, 5), created_at=f"{DATES[-4]} 23:00:00")
        res = compute_event_followups(_db(prices, [late]), REF)
        assert res[0]["event_session"] == DATES[-6]


class TestLocateMoveSession:
    def test_finds_matching_earlier_session(self) -> None:
        series = [("d0", 100.0), ("d1", 111.5), ("d2", 111.5), ("d3", 111.5)]
        assert locate_move_session(series, 3, 11.5) == 1

    def test_returns_none_when_move_not_in_prices(self) -> None:
        series = [("d0", 100.0), ("d1", 101.0), ("d2", 102.0)]
        assert locate_move_session(series, 2, 9.0) is None


class TestWeeklyRendering:
    def test_trend_sections_rendered(self) -> None:
        analysis = {
            "trend_board": {"universe_median_60": 0.11, "rows": [{
                "ticker": "DDOG", "return_short": 0.29, "return_long": 1.09, "relative_long": 0.98,
                "trend_z": 2.06, "from_high": -0.02, "event_count": 1, "article_count": 0,
                "direction": "up", "under_covered": True,
            }]},
            "event_followups": [{"ticker": "MDB", "event_session": "2026-09-28", "move": -0.2175,
                                 "since": 0.07, "sessions": 4, "status": "partial"}],
        }
        md = generate_weekly_report(analysis=analysis, date=REF)
        assert "## 中期トレンド" in md
        assert "| DDOG | +29.0% | +109.0% | +98.0pt | +2.1 | -2.0% | 1 | 0 | 上昇トレンド ⚠報告少 |" in md
        assert "## 主要イベントのその後" in md
        assert "| MDB | 2026-09-28 | -21.8% | +7.0% | 4 | 一部戻し |" in md

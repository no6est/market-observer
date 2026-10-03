"""Medium-term trend board and follow-up of past large moves.

Daily detection only sees single-session anomalies, so multi-month moves
(e.g. DDOG +142%, NET +96%, SNOW +93% from March to October 2026) never
formed a narrative lasting more than 2 days. This module measures trends
over 20/60 sessions directly from prices, compares them with how often the
system reported on each ticker, and tracks what happened after recent
large moves.
"""

from __future__ import annotations

import logging
import math
import re
import statistics
from datetime import datetime, timedelta
from typing import Any

from app.enrichers.signal_calibration import event_session_index, locate_move_session
from app.enrichers.ticker_aliases import find_related_content

logger = logging.getLogger(__name__)

SHORT_WINDOW = 20
LONG_WINDOW = 60
# |trend_z| >= 2: trend (about 0.8 tickers/week on Mar-Oct 2026 data; caught
# CRWD, DDOG, SNOW, UNH runs). 1.5-2: shown as a tendency, not flagged.
TREND_Z_THRESHOLD = 2.0
TENDENCY_Z_THRESHOLD = 1.5
# Calendar days covering LONG_WINDOW sessions, for event/article counts.
COVERAGE_DAYS = 90
_RETURN_RE = re.compile(r"前日比([+\-]?\d+(?:\.\d+)?)%")


def _closes(db: Any, ticker: str, reference_date: str, calendar_days: int) -> list[tuple[str, float]]:
    start = (datetime.strptime(reference_date, "%Y-%m-%d") - timedelta(days=calendar_days)).strftime("%Y-%m-%d")
    rows = db.get_price_data_range(ticker, start, reference_date)
    return [(r["timestamp"][:10], r["close"]) for r in rows if r.get("close")]


def compute_trend_board(
    db: Any,
    tickers: list[str],
    reference_date: str,
) -> dict[str, Any]:
    """Measure 20/60-session trends and the system's coverage of each ticker.

    trend_z is the 60-session log return divided by the volatility expected
    over 60 sessions (daily std * sqrt(60)); |trend_z| >= 2 is a trend that
    random daily noise rarely produces.

    Returns:
        {"rows": [...sorted by |trend_z|...], "universe_median_60": float}.
        A row is "under_covered" when it is trending but the system reported
        on it less often than the median ticker.
    """
    events = db.get_enriched_events_history(days=COVERAGE_DAYS, reference_date=reference_date)
    articles = db.get_articles_by_date_range(days=COVERAGE_DAYS, reference_date=reference_date)

    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        series = _closes(db, ticker, reference_date, calendar_days=LONG_WINDOW * 2 + 30)
        if len(series) <= LONG_WINDOW:
            continue
        closes = [c for _, c in series]
        last = closes[-1]
        r_short = last / closes[-1 - SHORT_WINDOW] - 1
        r_long = last / closes[-1 - LONG_WINDOW] - 1
        daily = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - LONG_WINDOW, len(closes))]
        sigma = statistics.pstdev(daily)
        trend_z = math.log(1 + r_long) / (sigma * math.sqrt(LONG_WINDOW)) if sigma else 0.0
        high = max(closes[-1 - LONG_WINDOW:])

        reported = {(e.get("signal_type"), e.get("summary")) for e in events if e.get("ticker") == ticker}
        matched_articles, _ = find_related_content(ticker, articles, [])
        rows.append({
            "ticker": ticker,
            "as_of": series[-1][0],
            "return_short": round(r_short, 4),
            "return_long": round(r_long, 4),
            "trend_z": round(trend_z, 2),
            "from_high": round(last / high - 1, 4),
            "event_count": len(reported),
            "article_count": len(matched_articles),
        })

    if not rows:
        return {"rows": [], "universe_median_60": None}

    median_long = statistics.median(r["return_long"] for r in rows)
    median_events = statistics.median(r["event_count"] for r in rows)
    for r in rows:
        r["relative_long"] = round(r["return_long"] - median_long, 4)
        z = r["trend_z"]
        if z >= TREND_Z_THRESHOLD:
            r["direction"] = "up"
        elif z <= -TREND_Z_THRESHOLD:
            r["direction"] = "down"
        elif z >= TENDENCY_Z_THRESHOLD:
            r["direction"] = "weak_up"
        elif z <= -TENDENCY_Z_THRESHOLD:
            r["direction"] = "weak_down"
        else:
            r["direction"] = "none"
        r["under_covered"] = r["direction"] in ("up", "down") and (
            r["event_count"] < median_events or r["event_count"] == 0
        )

    rows.sort(key=lambda r: abs(r["trend_z"]), reverse=True)
    logger.info(
        "Trend board: %d tickers, trending=%s",
        len(rows), [(r["ticker"], r["trend_z"]) for r in rows if r["direction"] != "none"],
    )
    return {"rows": rows, "universe_median_60": round(median_long, 4)}


def compute_event_followups(
    db: Any,
    reference_date: str,
    days: int = 30,
    min_move_pct: float = 5.0,
) -> list[dict[str, Any]]:
    """Track what happened after large price events of the last `days` days.

    Each distinct move (same ticker + summary counted once) of at least
    min_move_pct is compared with the latest close:
    - "continued": price moved further in the event's direction
    - "reversed": at least half of the event move was given back
    - "partial": gave back less than half
    """
    events = db.get_enriched_events_history(days=days, reference_date=reference_date)
    seen: set[tuple] = set()
    followups: list[dict[str, Any]] = []
    series_cache: dict[str, list[tuple[str, float]]] = {}

    for e in sorted(events, key=lambda x: (x.get("date", ""), x.get("created_at") or "")):
        if e.get("signal_type") != "price_change":
            continue
        key = (e.get("ticker"), e.get("summary"))
        if key in seen:
            continue
        seen.add(key)
        m = _RETURN_RE.search(e.get("summary") or "")
        if not m or abs(float(m.group(1))) < min_move_pct:
            continue
        move = float(m.group(1)) / 100
        ticker = e["ticker"]
        if ticker not in series_cache:
            series_cache[ticker] = _closes(db, ticker, reference_date, calendar_days=days + 20)
        series = series_cache[ticker]
        idx = event_session_index(series, e)
        if idx is None or idx < 1:
            continue
        idx = locate_move_session(series, idx, move * 100)
        if idx is None:
            logger.debug("Skipping %s %s: reported move not found in prices", ticker, e.get("summary"))
            continue
        since = series[-1][1] / series[idx][1] - 1
        direction = 1 if move > 0 else -1
        if since * direction >= 0:
            status = "continued"
        elif -since * direction >= abs(move) / 2:
            status = "reversed"
        else:
            status = "partial"
        followups.append({
            "ticker": ticker,
            "event_session": series[idx][0],
            "move": round(move, 4),
            "since": round(since, 4),
            "sessions": len(series) - 1 - idx,
            "status": status,
        })

    followups.sort(key=lambda f: abs(f["move"]), reverse=True)
    return followups

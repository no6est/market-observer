"""Signal calibration: check reported scores against realized price outcomes.

The daily report ranks events by SPP and flags mention surges, but neither
had been checked against what prices did afterwards. A backtest over
Mar-Oct 2026 found SPP had no predictive value (5-session continuation ~55%
for high-SPP events) and mention surges coincided with moves rather than
preceding them. This module recomputes those checks from the DB on every
weekly run so the report states how well the signals actually performed.
"""

from __future__ import annotations

import logging
import re
import statistics
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# US cash session closes 20:00 UTC (EDT) / 21:00 UTC (EST); a bar dated D
# is treated as closed from D 21:00 UTC onward.
_SESSION_CLOSE_HOUR_UTC = 21
_RETURN_RE = re.compile(r"前日比([+\-]?\d+(?:\.\d+)?)%")

SPP_HIGH = 0.6
MIN_SAMPLES = 10
HORIZONS = (5, 20)
_VOL_WINDOW = 20
_LOOKAHEAD = 3  # sessions checked for a "subsequent" large move


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("T", " ")[:19])
    except (ValueError, AttributeError):
        return None


def _load_prices(db: Any, tickers: set[str], start: str, end: str) -> dict[str, list[tuple[str, float]]]:
    """Load (session_date, close) series per ticker, skipping missing closes."""
    prices: dict[str, list[tuple[str, float]]] = {}
    for ticker in tickers:
        rows = db.get_price_data_range(ticker, start, end)
        series = [(r["timestamp"][:10], r["close"]) for r in rows if r.get("close")]
        if series:
            prices[ticker] = series
    return prices


def event_session_index(series: list[tuple[str, float]], event: dict[str, Any]) -> int | None:
    """Index of the last session already closed when the event was recorded."""
    created = _parse_ts(event.get("created_at") or "")
    if created is None:
        cutoff_date = event.get("date", "")
        idx = None
        for i, (d, _) in enumerate(series):
            if d <= cutoff_date:
                idx = i
        return idx
    idx = None
    for i, (d, _) in enumerate(series):
        close_time = datetime.strptime(d, "%Y-%m-%d") + timedelta(hours=_SESSION_CLOSE_HOUR_UTC)
        if close_time <= created:
            idx = i
    return idx


def locate_move_session(
    series: list[tuple[str, float]], idx: int, move_pct: float, max_back: int = 5,
) -> int | None:
    """Return the session (at or before idx) whose daily return matches move_pct.

    A move can be reported days after it happened (stale data, weekends), so
    this searches back up to max_back sessions for a daily return within
    0.5pt of the reported percentage. Returns None when nothing matches: the
    reported move does not exist in the current (split-adjusted) prices, e.g.
    CRWD's 4:1 split reported as -74.9%, and cannot be evaluated.
    """
    for i in range(idx, max(0, idx - max_back), -1):
        ret_pct = (series[i][1] / series[i - 1][1] - 1) * 100
        if abs(ret_pct - move_pct) <= 0.5:
            return i
    return None


def _daily_returns(series: list[tuple[str, float]]) -> list[float]:
    return [series[i][1] / series[i - 1][1] - 1 for i in range(1, len(series))]


def _sigma_before(returns: list[float], ret_idx: int) -> float | None:
    """Std of the daily returns preceding returns[ret_idx]."""
    window = returns[max(0, ret_idx - _VOL_WINDOW):ret_idx]
    if len(window) < 5:
        return None
    sd = statistics.pstdev(window)
    return sd or None


def _rate(hits: int, n: int) -> float | None:
    return round(hits / n, 3) if n else None


def compute_signal_calibration(
    db: Any,
    reference_date: str,
    lookback_days: int = 120,
) -> dict[str, Any]:
    """Compare SPP buckets and mention surges with realized price outcomes.

    Args:
        db: Database with get_enriched_events_history() and get_price_data_range().
        reference_date: Report date (YYYY-MM-DD).
        lookback_days: Event window to evaluate.

    Returns:
        Dict with "spp_buckets" (continuation rates of price events by SPP
        bucket), "mention_surge" (coincident vs subsequent large-move rates
        with a baseline over all sessions) and sample sizes. Rates are None
        when the bucket has fewer than MIN_SAMPLES events.
    """
    events = db.get_enriched_events_history(days=lookback_days, reference_date=reference_date)
    if not events:
        return {"lookback_days": lookback_days, "event_count": 0}

    # One entry per distinct move; the same summary repeated on later days
    # is the same event re-reported.
    unique: dict[tuple, dict[str, Any]] = {}
    for e in sorted(events, key=lambda x: (x.get("date", ""), x.get("created_at") or "")):
        key = (e.get("ticker"), e.get("signal_type"), e.get("summary"))
        unique.setdefault(key, e)

    ref = datetime.strptime(reference_date, "%Y-%m-%d")
    start = (ref - timedelta(days=lookback_days + 45)).strftime("%Y-%m-%d")
    tickers = {e.get("ticker") for e in unique.values() if e.get("ticker")}
    prices = _load_prices(db, tickers, start, reference_date)

    buckets = {
        "high": {"label": f"SPP≥{SPP_HIGH}", "n": {h: 0 for h in HORIZONS}, "hits": {h: 0 for h in HORIZONS}},
        "low": {"label": f"SPP<{SPP_HIGH}", "n": {h: 0 for h in HORIZONS}, "hits": {h: 0 for h in HORIZONS}},
        "all": {"label": "全価格イベント", "n": {h: 0 for h in HORIZONS}, "hits": {h: 0 for h in HORIZONS}},
    }
    mention = {"n": 0, "coincident": 0, "subsequent": 0}

    for e in unique.values():
        series = prices.get(e.get("ticker"))
        if not series:
            continue
        idx = event_session_index(series, e)
        if idx is None or idx < 1:
            continue
        signal = e.get("signal_type")

        if signal == "price_change":
            m = _RETURN_RE.search(e.get("summary") or "")
            if not m or float(m.group(1)) == 0:
                continue
            direction = 1 if float(m.group(1)) > 0 else -1
            idx = locate_move_session(series, idx, float(m.group(1)))
            if idx is None:
                continue
            spp = e.get("spp")
            groups = ["all"]
            if spp is not None and spp >= SPP_HIGH:
                groups.append("high")
            elif spp is not None:
                groups.append("low")
            for h in HORIZONS:
                if idx + h >= len(series):
                    continue
                cont = (series[idx + h][1] / series[idx][1] - 1) * direction > 0
                for g in groups:
                    buckets[g]["n"][h] += 1
                    buckets[g]["hits"][h] += cont

        elif signal == "mention_surge":
            returns = _daily_returns(series)
            ret_idx = idx - 1  # return of session idx
            sigma = _sigma_before(returns, ret_idx)
            if sigma is None or ret_idx + _LOOKAHEAD >= len(returns):
                continue
            mention["n"] += 1
            mention["coincident"] += abs(returns[ret_idx]) >= 2 * sigma
            nxt = returns[ret_idx + 1:ret_idx + 1 + _LOOKAHEAD]
            mention["subsequent"] += max(abs(r) for r in nxt) >= 2 * sigma

    # Baseline: same two measures over every ticker-session in the window.
    base_n = base_co = base_sub = 0
    for series in prices.values():
        returns = _daily_returns(series)
        for i in range(_VOL_WINDOW, len(returns) - _LOOKAHEAD):
            sigma = _sigma_before(returns, i)
            if sigma is None:
                continue
            base_n += 1
            base_co += abs(returns[i]) >= 2 * sigma
            base_sub += max(abs(r) for r in returns[i + 1:i + 1 + _LOOKAHEAD]) >= 2 * sigma

    spp_rows = []
    for key in ("high", "low", "all"):
        b = buckets[key]
        row = {"label": b["label"]}
        for h in HORIZONS:
            n = b["n"][h]
            row[f"n{h}"] = n
            row[f"cont{h}"] = _rate(b["hits"][h], n) if n >= MIN_SAMPLES else None
        spp_rows.append(row)

    mn = mention["n"]
    result = {
        "lookback_days": lookback_days,
        "event_count": len(unique),
        "spp_buckets": spp_rows,
        "mention_surge": {
            "n": mn,
            "coincident_rate": _rate(mention["coincident"], mn) if mn >= MIN_SAMPLES else None,
            "subsequent_rate": _rate(mention["subsequent"], mn) if mn >= MIN_SAMPLES else None,
            "baseline_coincident_rate": _rate(base_co, base_n),
            "baseline_subsequent_rate": _rate(base_sub, base_n),
        },
    }
    logger.info(
        "Signal calibration: %d unique events, SPP buckets=%s, mention=%s",
        len(unique), spp_rows, result["mention_surge"],
    )
    return result

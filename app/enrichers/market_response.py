"""Market response structure analysis — v8.

Analyzes how markets respond to narratives over time:
- PHASE 1: Reaction lag analysis (narrative → price response delay)
  + Direction analysis (price direction, LLM sentiment, alignment)
- PHASE 2: Watch ticker follow-up (previous month evaluation)
- PHASE 3: Narrative extinction / reorganization chain detection
- PHASE 4: Early drift persistent tracking and evaluation
- PHASE 5: Market response profile classification (7 types)
- PHASE 6: Regime × Reaction Lag cross analysis
- PHASE 7: Narrative exhaustion detection + post-evaluation

This module produces metrics only — no hypotheses are generated.
All language uses "co-occurrence / response" framing, never causal assertions.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PHASE 1: Reaction Lag Analysis
# ---------------------------------------------------------------------------

_REACTION_THRESHOLD_PCT = 2.0
_MAX_LAG_DAYS = 30
_HISTOGRAM_BUCKETS = [
    "0日", "1日", "2日", "3日", "4日", "5日", "6-10日", "11+日", "未反応",
]


def _classify_sentiment_batch(
    llm_client: Any | None,
    events: list[dict[str, Any]],
) -> dict[tuple[str, str], str]:
    """Classify event sentiment using LLM batch processing.

    Each event's summary is sent to Gemini to determine
    "positive" / "negative" / "unclear" sentiment.

    Args:
        llm_client: Gemini client instance or None.
        events: List of enriched event dicts.

    Returns:
        Mapping from (ticker, date) to sentiment string.
    """
    result: dict[tuple[str, str], str] = {}

    # Without LLM, all sentiments default to "unclear"
    if llm_client is None:
        for e in events:
            ticker = e.get("ticker", "")
            date = e.get("date", "")
            if ticker and date:
                result[(ticker, date)] = "unclear"
        return result

    # Collect events with summaries for batch classification
    batch_events: list[dict[str, Any]] = []
    for e in events:
        ticker = e.get("ticker", "")
        date = e.get("date", "")
        summary = e.get("summary", "")
        if ticker and date:
            batch_events.append({
                "ticker": ticker,
                "date": date,
                "summary": summary or "",
            })

    if not batch_events:
        return result

    # Process in chunks to avoid token limits
    _CHUNK_SIZE = 20
    valid_values = {"positive", "negative", "unclear"}

    for chunk_start in range(0, len(batch_events), _CHUNK_SIZE):
        chunk = batch_events[chunk_start:chunk_start + _CHUNK_SIZE]

        lines = []
        for i, be in enumerate(chunk, 1):
            lines.append(f'{i}. "{be["ticker"]}: {be["summary"]}"')
        summaries_text = "\n".join(lines)

        prompt = (
            "以下のイベントサマリーについて、市場センチメントを分類してください。\n"
            "各行に対して positive / negative / unclear のいずれかをJSON配列で返してください。\n"
            "配列の要素数は入力行数と一致させてください。\n\n"
            f"{summaries_text}\n\n"
            "回答（JSON配列のみ）:"
        )

        try:
            response = llm_client.generate(prompt, max_tokens=1024)
            if response:
                # Parse JSON array from response
                # Strip markdown code fences if present
                cleaned = response.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[-1]
                    cleaned = cleaned.rsplit("```", 1)[0]
                cleaned = cleaned.strip()

                sentiments = json.loads(cleaned)
                if isinstance(sentiments, list) and len(sentiments) == len(chunk):
                    for be, s in zip(chunk, sentiments):
                        val = s.strip().lower() if isinstance(s, str) else "unclear"
                        result[(be["ticker"], be["date"])] = (
                            val if val in valid_values else "unclear"
                        )
                    continue
        except Exception:
            logger.debug(
                "LLM sentiment classification failed for chunk %d-%d",
                chunk_start, chunk_start + len(chunk),
            )

        # Fallback for this chunk: all "unclear"
        for be in chunk:
            result[(be["ticker"], be["date"])] = "unclear"

    return result


def _compute_alignment(sentiment: str, price_direction: str) -> str:
    """Compute direction alignment between sentiment and price move.

    Args:
        sentiment: "positive", "negative", or "unclear".
        price_direction: "up", "down", or "flat".

    Returns:
        "aligned", "contrarian", or "unknown".
    """
    if sentiment == "unclear" or price_direction == "flat":
        return "unknown"
    if (sentiment == "positive" and price_direction == "up") or \
       (sentiment == "negative" and price_direction == "down"):
        return "aligned"
    if (sentiment == "positive" and price_direction == "down") or \
       (sentiment == "negative" and price_direction == "up"):
        return "contrarian"
    return "unknown"


def compute_reaction_lag(
    db: Any,
    days: int = 30,
    reference_date: str | None = None,
    llm_client: Any | None = None,
) -> dict[str, Any]:
    """Compute reaction lag between narrative events and price moves.

    For each enriched event, measures how many days until the ticker's
    daily return exceeds ±2%.  Also classifies price direction, LLM
    sentiment, and direction alignment.

    Args:
        db: Database instance.
        days: Analysis window in days.
        reference_date: Reference date (YYYY-MM-DD).
        llm_client: Optional Gemini client for sentiment classification.
            When None, sentiment defaults to "unclear" (degraded mode).

    Returns:
        Dict with event_lags, stats, and histogram_data.
    """
    empty = {
        "event_lags": [],
        "stats": {
            "avg_lag": 0.0,
            "median_lag": 0.0,
            "immediate_rate": 0.0,
            "delayed_rate": 0.0,
            "no_reaction_rate": 0.0,
            "total_events": 0,
            "aligned_rate": 0.0,
            "contrarian_rate": 0.0,
        },
        "histogram_data": [(b, 0) for b in _HISTOGRAM_BUCKETS],
    }

    try:
        events = db.get_enriched_events_history(
            days=days, reference_date=reference_date,
        )
    except Exception:
        logger.debug("Failed to fetch enriched events for reaction lag")
        return empty

    if not events:
        return empty

    # LLM sentiment classification (batch)
    sentiment_map = _classify_sentiment_batch(llm_client, events)

    event_lags: list[dict[str, Any]] = []

    for event in events:
        ticker = event.get("ticker")
        event_date = event.get("date")
        if not ticker or not event_date:
            continue

        sentiment = sentiment_map.get((ticker, event_date), "unclear")

        try:
            start_dt = datetime.strptime(event_date, "%Y-%m-%d")
        except ValueError:
            continue

        end_dt = start_dt + timedelta(days=_MAX_LAG_DAYS)
        start_str = event_date
        end_str = end_dt.strftime("%Y-%m-%d")

        try:
            prices = db.get_price_data_range(ticker, start_str, end_str)
        except Exception:
            logger.debug("No price data for %s in range %s-%s", ticker, start_str, end_str)
            event_lags.append({
                "ticker": ticker,
                "date": event_date,
                "lag_days": None,
                "reaction_pct": 0.0,
                "reacted": False,
                "price_direction": "flat",
                "sentiment": sentiment,
                "direction_alignment": "unknown",
            })
            continue

        if len(prices) < 2:
            event_lags.append({
                "ticker": ticker,
                "date": event_date,
                "lag_days": None,
                "reaction_pct": 0.0,
                "reacted": False,
                "price_direction": "flat",
                "sentiment": sentiment,
                "direction_alignment": "unknown",
            })
            continue

        lag_days = None
        reaction_pct = 0.0
        for i in range(1, len(prices)):
            prev_close = prices[i - 1].get("close")
            curr_close = prices[i].get("close")
            if prev_close is None or curr_close is None or prev_close == 0:
                continue
            daily_return = abs((curr_close - prev_close) / prev_close) * 100
            if daily_return >= _REACTION_THRESHOLD_PCT:
                lag_days = i
                reaction_pct = (curr_close - prev_close) / prev_close * 100
                break

        # Determine price direction from signed reaction_pct
        if reaction_pct > 0:
            price_direction = "up"
        elif reaction_pct < 0:
            price_direction = "down"
        else:
            price_direction = "flat"

        # Determine direction alignment
        direction_alignment = _compute_alignment(sentiment, price_direction)

        event_lags.append({
            "ticker": ticker,
            "date": event_date,
            "lag_days": lag_days,
            "reaction_pct": round(reaction_pct, 2),
            "reacted": lag_days is not None,
            "price_direction": price_direction,
            "sentiment": sentiment,
            "direction_alignment": direction_alignment,
        })

    # Compute stats
    reacted_lags = [el["lag_days"] for el in event_lags if el["reacted"]]
    total = len(event_lags)

    if total == 0:
        return empty

    if reacted_lags:
        avg_lag = sum(reacted_lags) / len(reacted_lags)
        sorted_lags = sorted(reacted_lags)
        mid = len(sorted_lags) // 2
        if len(sorted_lags) % 2 == 0 and len(sorted_lags) >= 2:
            median_lag = (sorted_lags[mid - 1] + sorted_lags[mid]) / 2
        else:
            median_lag = sorted_lags[mid]
    else:
        avg_lag = 0.0
        median_lag = 0.0

    immediate_count = sum(1 for el in event_lags if el["reacted"] and el["lag_days"] <= 1)
    delayed_count = sum(1 for el in event_lags if el["reacted"] and el["lag_days"] >= 3)
    no_reaction_count = sum(1 for el in event_lags if not el["reacted"])

    # Direction alignment stats (exclude "unknown")
    aligned_count = sum(
        1 for el in event_lags if el.get("direction_alignment") == "aligned"
    )
    contrarian_count = sum(
        1 for el in event_lags if el.get("direction_alignment") == "contrarian"
    )
    known_alignment = aligned_count + contrarian_count

    stats = {
        "avg_lag": round(avg_lag, 1),
        "median_lag": round(median_lag, 1),
        "immediate_rate": round(immediate_count / total, 3),
        "delayed_rate": round(delayed_count / total, 3),
        "no_reaction_rate": round(no_reaction_count / total, 3),
        "total_events": total,
        "aligned_rate": (
            round(aligned_count / known_alignment, 3)
            if known_alignment > 0 else 0.0
        ),
        "contrarian_rate": (
            round(contrarian_count / known_alignment, 3)
            if known_alignment > 0 else 0.0
        ),
    }

    # Build histogram
    histogram: dict[str, int] = {b: 0 for b in _HISTOGRAM_BUCKETS}
    for el in event_lags:
        if not el["reacted"]:
            histogram["未反応"] += 1
        elif el["lag_days"] <= 5:
            histogram[f"{el['lag_days']}日"] += 1
        elif el["lag_days"] <= 10:
            histogram["6-10日"] += 1
        else:
            histogram["11+日"] += 1

    histogram_data = [(b, histogram[b]) for b in _HISTOGRAM_BUCKETS]

    return {
        "event_lags": event_lags,
        "stats": stats,
        "histogram_data": histogram_data,
    }


# ---------------------------------------------------------------------------
# PHASE 2: Watch Ticker Follow-up
# ---------------------------------------------------------------------------


def _get_previous_watch_tickers(
    db: Any,
    days: int,
    prev_ref: str,
) -> list[dict[str, Any]]:
    """Extract watch tickers from previous period without full monthly analysis.

    Lightweight extraction: gets core tickers + new tickers from previous
    month's enriched events and structural persistence data.

    Args:
        db: Database instance.
        days: Period length in days.
        prev_ref: Previous period reference date.

    Returns:
        List of watch ticker dicts with 'ticker' and 'reason'.
    """
    try:
        prev_enriched = db.get_enriched_events_history(
            days=days, reference_date=prev_ref,
        )
    except Exception:
        return []

    if not prev_enriched:
        return []

    # Identify tickers with high SPP or frequent appearance
    ticker_data: dict[str, dict[str, Any]] = {}
    dates = set()
    for e in prev_enriched:
        ticker = e.get("ticker", "")
        if not ticker:
            continue
        date = e.get("date", "")
        dates.add(date)
        if ticker not in ticker_data:
            ticker_data[ticker] = {
                "dates": set(),
                "spp_values": [],
            }
        ticker_data[ticker]["dates"].add(date)
        spp = e.get("spp")
        if spp is not None:
            ticker_data[ticker]["spp_values"].append(spp)

    total_days = len(dates) or 1
    watch: list[dict[str, Any]] = []
    for ticker, td in ticker_data.items():
        ratio = len(td["dates"]) / total_days
        avg_spp = (
            sum(td["spp_values"]) / len(td["spp_values"])
            if td["spp_values"]
            else 0.0
        )
        if ratio >= 0.6 or avg_spp >= 0.5:
            watch.append({
                "ticker": ticker,
                "reason": "コア銘柄" if ratio >= 0.6 else "高SPP",
                "prev_spp": round(avg_spp, 3),
            })

    return watch


def compute_watch_ticker_followup(
    db: Any,
    days: int = 30,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Evaluate previous month's watch tickers against current data.

    Args:
        db: Database instance.
        days: Analysis window in days.
        reference_date: Reference date (YYYY-MM-DD).

    Returns:
        Dict with available flag, followups list, and outcome distribution.
    """
    empty: dict[str, Any] = {
        "available": False,
        "followups": [],
        "outcome_distribution": {},
    }

    if reference_date:
        ref_dt = datetime.strptime(reference_date, "%Y-%m-%d")
    else:
        ref_dt = datetime.utcnow()
    prev_ref = (ref_dt - timedelta(days=days)).strftime("%Y-%m-%d")

    prev_watch = _get_previous_watch_tickers(db, days, prev_ref)
    if not prev_watch:
        return empty

    # Get current period enriched events
    try:
        curr_enriched = db.get_enriched_events_history(
            days=days, reference_date=reference_date,
        )
    except Exception:
        return empty

    # Build current ticker SPP map
    curr_spp_map: dict[str, list[float]] = {}
    curr_tickers: set[str] = set()
    for e in curr_enriched:
        ticker = e.get("ticker", "")
        if not ticker:
            continue
        curr_tickers.add(ticker)
        spp = e.get("spp")
        if spp is not None:
            curr_spp_map.setdefault(ticker, []).append(spp)

    # Get current and previous narrative share
    try:
        curr_narrative = db.get_narrative_history(
            days=days, reference_date=reference_date,
        )
        prev_narrative = db.get_narrative_history(
            days=days, reference_date=prev_ref,
        )
    except Exception:
        curr_narrative = []
        prev_narrative = []

    def _narrative_share_for_ticker(enriched: list[dict], ticker: str) -> float:
        """Approximate narrative share as count of events for ticker / total."""
        total = len(enriched) or 1
        ticker_count = sum(1 for e in enriched if e.get("ticker") == ticker)
        return ticker_count / total

    # Get price changes
    def _get_price_change(ticker: str) -> float | None:
        """Get price change percentage over the period."""
        try:
            ref_str = reference_date or ref_dt.strftime("%Y-%m-%d")
            start_str = prev_ref
            prices = db.get_price_data_range(ticker, start_str, ref_str)
            if prices and len(prices) >= 2:
                first_close = prices[0].get("close")
                last_close = prices[-1].get("close")
                if first_close and first_close != 0:
                    return ((last_close - first_close) / first_close) * 100
        except Exception:
            pass
        return None

    followups: list[dict[str, Any]] = []
    outcome_counts: Counter = Counter()

    for watch in prev_watch:
        ticker = watch["ticker"]
        prev_spp = watch.get("prev_spp", 0.0)

        curr_spp_values = curr_spp_map.get(ticker, [])
        curr_spp = (
            sum(curr_spp_values) / len(curr_spp_values)
            if curr_spp_values
            else 0.0
        )

        price_change = _get_price_change(ticker)
        price_change_pct = price_change if price_change is not None else 0.0

        prev_enriched_list = db.get_enriched_events_history(
            days=days, reference_date=prev_ref,
        )
        prev_share = _narrative_share_for_ticker(prev_enriched_list, ticker)
        curr_share = _narrative_share_for_ticker(curr_enriched, ticker)
        narrative_share_change = curr_share - prev_share

        # Determine outcome
        if ticker not in curr_tickers:
            outcome = "再編連鎖"
        elif (
            curr_spp > prev_spp
            and (price_change_pct > 0 or narrative_share_change > 0)
        ):
            outcome = "仮説強化"
        elif (
            curr_spp < prev_spp
            and narrative_share_change < 0
            and abs(price_change_pct) < 2.0
        ):
            outcome = "収束"
        elif price_change is not None and (
            (price_change_pct > 2.0 and prev_spp < 0.3)
            or (price_change_pct < -2.0 and prev_spp > 0.5)
        ):
            outcome = "反転"
        else:
            outcome = "仮説強化"

        followups.append({
            "ticker": ticker,
            "prev_spp": round(prev_spp, 3),
            "curr_spp": round(curr_spp, 3),
            "price_change_pct": round(price_change_pct, 2),
            "narrative_share_change": round(narrative_share_change, 3),
            "outcome": outcome,
        })
        outcome_counts[outcome] += 1

    return {
        "available": True,
        "followups": followups,
        "outcome_distribution": dict(outcome_counts),
    }


# ---------------------------------------------------------------------------
# PHASE 3: Narrative Extinction / Reorganization Chain
# ---------------------------------------------------------------------------


def _extract_bigrams(text: str) -> Counter:
    """Extract word bigrams from text (supports ASCII and CJK).

    Args:
        text: Input text string.

    Returns:
        Counter of bigram strings like "word1_word2".
    """
    if not text:
        return Counter()
    words = re.findall(
        r'[a-zA-Z]{2,}|[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]+',
        text.lower(),
    )
    if len(words) < 2:
        return Counter()
    return Counter(
        f"{words[i]}_{words[i + 1]}" for i in range(len(words) - 1)
    )


def detect_narrative_extinction_chain(
    db: Any,
    days: int = 30,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Detect narrative categories that declined and may have reorganized.

    Splits the analysis period into first/second half, identifies
    declining and rising categories, then checks for shared bigrams
    in event summaries as evidence of reorganization.

    Args:
        db: Database instance.
        days: Analysis window in days.
        reference_date: Reference date (YYYY-MM-DD).

    Returns:
        Dict with chains list and reorganization_map.
    """
    empty: dict[str, Any] = {
        "chains": [],
        "reorganization_map": {},
    }

    try:
        narrative_history = db.get_narrative_history(
            days=days, reference_date=reference_date,
        )
    except Exception:
        logger.debug("Failed to fetch narrative history for extinction chain")
        return empty

    if not narrative_history:
        return empty

    # Group by date
    daily_data: dict[str, dict[str, float]] = {}
    for row in narrative_history:
        date = row.get("date", "")
        cat = row.get("category", "")
        pct = row.get("event_pct", 0.0)
        if date not in daily_data:
            daily_data[date] = {}
        daily_data[date][cat] = pct

    sorted_dates = sorted(daily_data.keys())
    if len(sorted_dates) < 4:
        return empty

    mid = len(sorted_dates) // 2
    first_half_dates = sorted_dates[:mid]
    second_half_dates = sorted_dates[mid:]

    # Compute average pct per category for each half
    all_categories = set()
    for cats in daily_data.values():
        all_categories.update(cats.keys())

    first_avg: dict[str, float] = {}
    second_avg: dict[str, float] = {}
    for cat in all_categories:
        first_values = [daily_data[d].get(cat, 0.0) for d in first_half_dates]
        second_values = [daily_data[d].get(cat, 0.0) for d in second_half_dates]
        first_avg[cat] = (
            sum(first_values) / len(first_values)
            if first_values
            else 0.0
        )
        second_avg[cat] = (
            sum(second_values) / len(second_values)
            if second_values
            else 0.0
        )

    # Identify declining and rising categories (5pt = 0.05 threshold)
    declining = [
        cat for cat in all_categories
        if first_avg.get(cat, 0.0) - second_avg.get(cat, 0.0) >= 0.05
    ]
    rising = [
        cat for cat in all_categories
        if second_avg.get(cat, 0.0) - first_avg.get(cat, 0.0) >= 0.05
    ]

    if not declining or not rising:
        return empty

    # Get enriched events for bigram analysis
    try:
        enriched = db.get_enriched_events_history(
            days=days, reference_date=reference_date,
        )
    except Exception:
        enriched = []

    # Build per-category bigram collections from event summaries
    cat_bigrams: dict[str, Counter] = {}
    cat_events: dict[str, list[dict]] = {}
    for e in enriched:
        cat = e.get("narrative_category", "")
        summary = e.get("summary", "")
        if not cat or not summary:
            continue
        if cat not in cat_bigrams:
            cat_bigrams[cat] = Counter()
            cat_events[cat] = []
        cat_bigrams[cat] += _extract_bigrams(summary)
        cat_events[cat].append(e)

    # Find reorganization chains
    chains: list[dict[str, Any]] = []
    reorg_map: dict[str, list[str]] = {}

    for d_cat in declining:
        d_bigrams = cat_bigrams.get(d_cat, Counter())
        if not d_bigrams:
            continue
        candidates: list[str] = []
        for r_cat in rising:
            r_bigrams = cat_bigrams.get(r_cat, Counter())
            if not r_bigrams:
                continue
            # Find shared bigrams
            shared = set(d_bigrams.keys()) & set(r_bigrams.keys())
            # Count co-occurrences (min count across both)
            overlap_score = sum(
                min(d_bigrams[bg], r_bigrams[bg]) for bg in shared
            )
            if overlap_score >= 2:
                sample_events = []
                for e in cat_events.get(d_cat, [])[:2]:
                    sample_events.append({
                        "ticker": e.get("ticker", ""),
                        "date": e.get("date", ""),
                        "summary": (e.get("summary", "") or "")[:80],
                    })
                chains.append({
                    "declining_cat": d_cat,
                    "rising_cat": r_cat,
                    "shared_keywords": sorted(shared)[:10],
                    "overlap_score": overlap_score,
                    "sample_events": sample_events,
                })
                candidates.append(r_cat)
        if candidates:
            reorg_map[d_cat] = candidates

    return {
        "chains": chains,
        "reorganization_map": reorg_map,
    }


# ---------------------------------------------------------------------------
# PHASE 6: Regime × Reaction Lag Cross Analysis
# ---------------------------------------------------------------------------


def compute_regime_reaction_cross(
    db: Any,
    days: int = 30,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Cross-analyze reaction lag statistics by market regime.

    Groups enriched events by regime (bullish/bearish/neutral) and
    computes per-regime reaction lag statistics.

    Args:
        db: Database instance.
        days: Analysis window in days.
        reference_date: Reference date (YYYY-MM-DD).

    Returns:
        Dict with regime_stats and notable_patterns.
    """
    empty: dict[str, Any] = {
        "regime_stats": {},
        "notable_patterns": [],
    }

    try:
        events = db.get_enriched_events_history(
            days=days, reference_date=reference_date,
        )
    except Exception:
        logger.debug("Failed to fetch enriched events for regime cross")
        return empty

    if not events:
        return empty

    # Build date→regime map from regime_snapshots (authoritative source)
    date_regime_map: dict[str, str] = {}
    try:
        regime_history = db.get_regime_history(
            days=days, reference_date=reference_date,
        )
        for r in regime_history:
            date_regime_map[r.get("date", "")] = r.get("regime", "neutral")
    except Exception:
        logger.debug("Failed to fetch regime history for cross analysis")

    # Map regime keys to Japanese for display
    _regime_ja: dict[str, str] = {
        "normal": "平時", "high_vol": "高ボラ", "tightening": "引き締め",
        "bullish": "強気", "bearish": "弱気", "neutral": "中立",
    }

    # Group events by regime (using regime_snapshots, falling back to
    # enriched_events.regime, then "neutral")
    regime_events: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        event_date = e.get("date", "")
        raw_regime = (
            date_regime_map.get(event_date)
            or e.get("regime")
            or "neutral"
        )
        regime = _regime_ja.get(raw_regime, raw_regime)
        regime_events.setdefault(regime, []).append(e)

    if not regime_events:
        return empty

    # For each regime group, compute reaction lag
    regime_stats: dict[str, dict[str, Any]] = {}
    for regime, r_events in regime_events.items():
        # Build a temporary DB mock-like call for reaction lag per regime
        lag_results: list[int | None] = []
        reacted_count = 0
        immediate_count = 0
        no_reaction_count = 0

        for event in r_events:
            ticker = event.get("ticker")
            event_date = event.get("date")
            if not ticker or not event_date:
                continue
            try:
                start_dt = datetime.strptime(event_date, "%Y-%m-%d")
            except ValueError:
                continue
            end_dt = start_dt + timedelta(days=_MAX_LAG_DAYS)
            try:
                prices = db.get_price_data_range(
                    ticker, event_date, end_dt.strftime("%Y-%m-%d"),
                )
            except Exception:
                lag_results.append(None)
                no_reaction_count += 1
                continue

            if len(prices) < 2:
                lag_results.append(None)
                no_reaction_count += 1
                continue

            found_lag = None
            for i in range(1, len(prices)):
                prev_close = prices[i - 1].get("close")
                curr_close = prices[i].get("close")
                if prev_close is None or curr_close is None or prev_close == 0:
                    continue
                daily_return = abs((curr_close - prev_close) / prev_close) * 100
                if daily_return >= _REACTION_THRESHOLD_PCT:
                    found_lag = i
                    break

            lag_results.append(found_lag)
            if found_lag is not None:
                reacted_count += 1
                if found_lag <= 1:
                    immediate_count += 1
            else:
                no_reaction_count += 1

        total = len(lag_results)
        if total == 0:
            continue

        reacted_lags = [lag for lag in lag_results if lag is not None]
        avg_lag = (
            round(sum(reacted_lags) / len(reacted_lags), 1)
            if reacted_lags else 0.0
        )

        regime_stats[regime] = {
            "event_count": total,
            "avg_lag": avg_lag,
            "immediate_rate": round(immediate_count / total, 3),
            "no_reaction_rate": round(no_reaction_count / total, 3),
        }

    # Detect notable patterns (regime keys are already Japanese)
    notable_patterns: list[str] = []
    for regime, stats in regime_stats.items():
        if stats["immediate_rate"] >= 0.6:
            notable_patterns.append(
                f"{regime}レジームでは即時反応率が高い ({stats['immediate_rate']*100:.0f}%)"
            )
        if stats["no_reaction_rate"] >= 0.6:
            notable_patterns.append(
                f"{regime}レジームでは未反応率が高い ({stats['no_reaction_rate']*100:.0f}%)"
            )
        if stats["avg_lag"] >= 5.0 and stats["event_count"] >= 3:
            notable_patterns.append(
                f"{regime}レジームでは反応ラグが大きい (平均{stats['avg_lag']}日)"
            )

    return {
        "regime_stats": regime_stats,
        "notable_patterns": notable_patterns,
    }


# ---------------------------------------------------------------------------
# PHASE 7: Narrative Exhaustion Detection
# ---------------------------------------------------------------------------


def detect_narrative_exhaustion(
    db: Any,
    days: int = 30,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Detect narrative categories showing signs of exhaustion.

    Exhaustion criteria (all 3 must be met):
    1. Same narrative occupies ≥30% share for 5+ consecutive days
    2. Median evidence_score ≤ 0.3
    3. Average z_score of related anomalies over last 3 days ≤ 1.0

    Args:
        db: Database instance.
        days: Analysis window in days.
        reference_date: Reference date (YYYY-MM-DD).

    Returns:
        Dict with exhaustion_candidates list and total_detected count.
    """
    empty: dict[str, Any] = {
        "exhaustion_candidates": [],
        "total_detected": 0,
    }

    try:
        narrative_history = db.get_narrative_history(
            days=days, reference_date=reference_date,
        )
    except Exception:
        logger.debug("Failed to fetch narrative history for exhaustion detection")
        return empty

    if not narrative_history:
        return empty

    try:
        enriched = db.get_enriched_events_history(
            days=days, reference_date=reference_date,
        )
    except Exception:
        enriched = []

    # Group narrative data by date, then by category
    daily_cats: dict[str, dict[str, float]] = {}
    for row in narrative_history:
        date = row.get("date", "")
        cat = row.get("category", "")
        pct = row.get("event_pct", 0.0)
        if date and cat:
            daily_cats.setdefault(date, {})[cat] = pct

    sorted_dates = sorted(daily_cats.keys())
    if len(sorted_dates) < 5:
        return empty

    # Collect all categories
    all_categories = set()
    for cats in daily_cats.values():
        all_categories.update(cats.keys())

    # Build evidence scores per category from enriched events
    cat_evidence_scores: dict[str, list[float]] = {}
    cat_tickers: dict[str, set[str]] = {}
    for e in enriched:
        cat = e.get("narrative_category", "")
        ev_score = e.get("evidence_score")
        ticker = e.get("ticker", "")
        if cat:
            if ev_score is not None:
                cat_evidence_scores.setdefault(cat, []).append(ev_score)
            if ticker:
                cat_tickers.setdefault(cat, set()).add(ticker)

    # Check each category for exhaustion
    candidates: list[dict[str, Any]] = []

    for cat in all_categories:
        # Condition 1: 5+ consecutive days with ≥30% share
        consecutive = 0
        max_consecutive = 0
        total_share = 0.0
        dominant_days = 0

        for date in sorted_dates:
            pct = daily_cats.get(date, {}).get(cat, 0.0)
            if pct >= 0.30:
                consecutive += 1
                total_share += pct
                dominant_days += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0

        if max_consecutive < 5:
            continue

        # Condition 2: Median evidence_score ≤ 0.3
        ev_scores = cat_evidence_scores.get(cat, [])
        if ev_scores:
            sorted_scores = sorted(ev_scores)
            mid = len(sorted_scores) // 2
            if len(sorted_scores) % 2 == 0 and len(sorted_scores) >= 2:
                median_evidence = (sorted_scores[mid - 1] + sorted_scores[mid]) / 2
            else:
                median_evidence = sorted_scores[mid]
        else:
            median_evidence = 0.0

        if median_evidence > 0.3:
            continue

        # Condition 3: Average z_score over last 3 days ≤ 1.0
        last_3_dates = sorted_dates[-3:]
        tickers = cat_tickers.get(cat, set())
        z_scores: list[float] = []

        if tickers and last_3_dates:
            start_date = last_3_dates[0]
            end_date = last_3_dates[-1]
            for ticker in tickers:
                try:
                    anomalies = db.get_anomalies_by_date_range(
                        ticker, start_date, end_date,
                    )
                    for a in anomalies:
                        z = a.get("z_score")
                        if z is not None:
                            z_scores.append(z)
                except Exception:
                    pass

        avg_z_score = (
            sum(z_scores) / len(z_scores) if z_scores else 0.0
        )

        if avg_z_score > 1.0:
            continue

        # All 3 conditions met → exhaustion candidate
        avg_share = (
            total_share / dominant_days if dominant_days > 0 else 0.0
        )
        candidates.append({
            "narrative_category": cat,
            "dominant_days": max_consecutive,
            "avg_share": round(avg_share, 3),
            "median_evidence": round(median_evidence, 3),
            "avg_z_score": round(avg_z_score, 2),
            "related_tickers": sorted(tickers),
        })

    return {
        "exhaustion_candidates": candidates,
        "total_detected": len(candidates),
    }


def evaluate_exhaustion_outcomes(
    db: Any,
    exhaustion_result: dict[str, Any],
    reference_date: str | None = None,
    followup_days: int = 14,
) -> dict[str, Any]:
    """Evaluate outcomes of previously detected exhaustion candidates.

    Checks whether narrative share dropped by ≥20pt within followup_days.
    If so, marks as "衰退確認"; otherwise "継続中".

    Args:
        db: Database instance.
        exhaustion_result: Output from detect_narrative_exhaustion().
        reference_date: Date when exhaustion was detected.
        followup_days: Days after detection to check outcome.

    Returns:
        Dict with evaluations list and stats.
    """
    empty: dict[str, Any] = {
        "evaluations": [],
        "stats": {"total": 0, "decay_rate": 0.0},
    }

    candidates = exhaustion_result.get("exhaustion_candidates", [])
    if not candidates:
        return empty

    if reference_date:
        ref_dt = datetime.strptime(reference_date, "%Y-%m-%d")
    else:
        ref_dt = datetime.utcnow()

    followup_ref = (ref_dt + timedelta(days=followup_days)).strftime("%Y-%m-%d")

    try:
        followup_narrative = db.get_narrative_history(
            days=followup_days, reference_date=followup_ref,
        )
    except Exception:
        return empty

    # Build average share per category in followup period
    cat_shares: dict[str, list[float]] = {}
    for row in followup_narrative:
        cat = row.get("category", "")
        pct = row.get("event_pct", 0.0)
        if cat:
            cat_shares.setdefault(cat, []).append(pct)

    evaluations: list[dict[str, Any]] = []
    decay_count = 0

    for cand in candidates:
        cat = cand["narrative_category"]
        detected_share = cand["avg_share"]

        shares = cat_shares.get(cat, [])
        current_share = (
            sum(shares) / len(shares) if shares else 0.0
        )

        change_pt = current_share - detected_share

        if change_pt <= -0.20:
            outcome = "衰退確認"
            decay_count += 1
        else:
            outcome = "継続中"

        evaluations.append({
            "category": cat,
            "detected_share": round(detected_share, 3),
            "current_share": round(current_share, 3),
            "change_pt": round(change_pt, 3),
            "outcome": outcome,
        })

    total = len(evaluations)
    return {
        "evaluations": evaluations,
        "stats": {
            "total": total,
            "decay_rate": round(decay_count / total, 3) if total > 0 else 0.0,
        },
    }


# ---------------------------------------------------------------------------
# PHASE 4: Early Drift Persistent Tracking
# ---------------------------------------------------------------------------


def track_early_drift_persistent(
    db: Any,
    drift_candidates: list[dict[str, Any]],
    reference_date: str | None = None,
) -> int:
    """Persist early drift candidates as hypothesis_logs with status='drift_pending'.

    Args:
        db: Database instance.
        drift_candidates: Early drift detection results from daily pipeline.
        reference_date: Date string (YYYY-MM-DD).

    Returns:
        Number of drift entries persisted.
    """
    if not drift_candidates:
        return 0

    today = reference_date or datetime.utcnow().strftime("%Y-%m-%d")
    count = 0

    for d in drift_candidates:
        try:
            db.insert_hypothesis_log({
                "date": today,
                "ticker": d.get("ticker", ""),
                "hypothesis": (
                    f"Early Drift: {d.get('narrative_category', '')} "
                    f"(z={d.get('z_score', 0):.2f}, "
                    f"diffusion={d.get('diffusion_pattern', '')})"
                ),
                "evidence": d.get("summary", ""),
                "confidence": 0.3,
                "status": "drift_pending",
            })
            count += 1
        except Exception:
            logger.debug("Failed to persist drift for %s", d.get("ticker"))

    return count


def evaluate_drift_followups(
    db: Any,
    reference_date: str | None = None,
    followup_days: int = 30,
) -> dict[str, Any]:
    """Evaluate drift_pending hypotheses older than followup_days.

    Checks whether each drift candidate reached Tier1 coverage
    or triggered a price reaction.

    Args:
        db: Database instance.
        reference_date: Reference date (YYYY-MM-DD).
        followup_days: Minimum age in days before evaluation.

    Returns:
        Dict with evaluations list and aggregate stats.
    """
    empty: dict[str, Any] = {
        "evaluations": [],
        "stats": {
            "total": 0,
            "tier1_arrival_rate": 0.0,
            "price_reaction_rate": 0.0,
            "drift_success_rate": 0.0,
        },
    }

    try:
        drift_hyps = db.get_drift_hypotheses(followup_days, reference_date)
    except Exception:
        logger.debug("Failed to fetch drift hypotheses")
        return empty

    if not drift_hyps:
        return empty

    evaluations: list[dict[str, Any]] = []

    for hyp in drift_hyps:
        ticker = hyp.get("ticker", "")
        hyp_date = hyp.get("date", "")
        hyp_id = hyp.get("id")

        # Check Tier1 arrival: look at enriched events after drift date
        tier1_arrived = False
        price_reacted = False

        try:
            later_events = db.get_enriched_events_history(
                days=followup_days, reference_date=reference_date,
            )
            for e in later_events:
                if e.get("ticker") == ticker:
                    if (e.get("tier1_count") or 0) > 0:
                        tier1_arrived = True
                    break
        except Exception:
            pass

        # Check price reaction
        try:
            ref_str = reference_date or datetime.utcnow().strftime("%Y-%m-%d")
            prices = db.get_price_data_range(ticker, hyp_date, ref_str)
            if prices and len(prices) >= 2:
                first_close = prices[0].get("close")
                last_close = prices[-1].get("close")
                if first_close and first_close != 0:
                    change = abs((last_close - first_close) / first_close) * 100
                    if change >= _REACTION_THRESHOLD_PCT:
                        price_reacted = True
        except Exception:
            pass

        outcome = "成功" if tier1_arrived or price_reacted else "未到達"

        evaluations.append({
            "id": hyp_id,
            "ticker": ticker,
            "date": hyp_date,
            "tier1_arrived": tier1_arrived,
            "price_reacted": price_reacted,
            "outcome": outcome,
        })

    total = len(evaluations)
    tier1_count = sum(1 for e in evaluations if e["tier1_arrived"])
    price_count = sum(1 for e in evaluations if e["price_reacted"])
    success_count = sum(1 for e in evaluations if e["outcome"] == "成功")

    return {
        "evaluations": evaluations,
        "stats": {
            "total": total,
            "tier1_arrival_rate": round(tier1_count / total, 3) if total else 0.0,
            "price_reaction_rate": round(price_count / total, 3) if total else 0.0,
            "drift_success_rate": round(success_count / total, 3) if total else 0.0,
        },
    }


# ---------------------------------------------------------------------------
# PHASE 5: Market Response Profile
# ---------------------------------------------------------------------------


_RESPONSE_TYPES = [
    "再編型",
    "疲弊型",
    "無反応型",
    "逆行型",
    "一時的過熱型",
    "即時反応型",
    "遅延持続型",
]


def compute_response_profile(
    db: Any,
    days: int = 30,
    reference_date: str | None = None,
    reaction_lag_result: dict[str, Any] | None = None,
    extinction_result: dict[str, Any] | None = None,
    exhaustion_result: dict[str, Any] | None = None,
    direction_data: dict[tuple[str, str], dict] | None = None,
) -> dict[str, Any]:
    """Classify each event's market response type (7 types).

    Classification rules (priority order):
    1. Ticker in extinction chain's declining category → 再編型
    2. Ticker's category is exhaustion candidate → 疲弊型
    3. No lag info or no reaction → 無反応型
    4. direction_alignment == "contrarian" → 逆行型
    5. lag_days <= 1 AND SPP < 0.3 → 一時的過熱型
    6. lag_days <= 1 AND SPP >= 0.3 → 即時反応型
    7. lag_days >= 3 AND SPP > 0.5 → 遅延持続型
    Default → 即時反応型

    Args:
        db: Database instance.
        days: Analysis window.
        reference_date: Reference date.
        reaction_lag_result: Output from compute_reaction_lag().
        extinction_result: Output from detect_narrative_extinction_chain().
        exhaustion_result: Output from detect_narrative_exhaustion().
        direction_data: Mapping of (ticker, date) to alignment info from
            reaction lag event_lags.

    Returns:
        Dict with event_profiles, distribution, distribution_pct.
    """
    empty: dict[str, Any] = {
        "event_profiles": [],
        "distribution": {t: 0 for t in _RESPONSE_TYPES},
        "distribution_pct": {t: 0.0 for t in _RESPONSE_TYPES},
    }

    if reaction_lag_result is None:
        reaction_lag_result = compute_reaction_lag(
            db, days=days, reference_date=reference_date,
        )

    event_lags = reaction_lag_result.get("event_lags", [])
    if not event_lags:
        return empty

    # Build lag lookup: (ticker, date) -> lag info
    lag_lookup: dict[tuple[str, str], dict] = {}
    for el in event_lags:
        key = (el.get("ticker", ""), el.get("date", ""))
        lag_lookup[key] = el

    # Build declining tickers set from extinction chains
    declining_tickers: set[str] = set()
    if extinction_result:
        for chain in extinction_result.get("chains", []):
            for se in chain.get("sample_events", []):
                declining_tickers.add(se.get("ticker", ""))

    # Also build declining categories for matching
    declining_cats: set[str] = set()
    if extinction_result:
        for chain in extinction_result.get("chains", []):
            declining_cats.add(chain.get("declining_cat", ""))

    # Build exhaustion categories set
    exhaustion_cats: set[str] = set()
    if exhaustion_result:
        for cand in exhaustion_result.get("exhaustion_candidates", []):
            exhaustion_cats.add(cand.get("narrative_category", ""))

    # Build direction alignment lookup from event_lags or direction_data
    alignment_lookup: dict[tuple[str, str], str] = {}
    if direction_data:
        for key, info in direction_data.items():
            alignment_lookup[key] = info.get("direction_alignment", "unknown")
    else:
        # Fall back to event_lags alignment data
        for el in event_lags:
            key = (el.get("ticker", ""), el.get("date", ""))
            alignment_lookup[key] = el.get("direction_alignment", "unknown")

    # Get enriched events for SPP data
    try:
        enriched = db.get_enriched_events_history(
            days=days, reference_date=reference_date,
        )
    except Exception:
        enriched = []

    # Build SPP lookup
    spp_lookup: dict[tuple[str, str], float] = {}
    cat_lookup: dict[tuple[str, str], str] = {}
    for e in enriched:
        key = (e.get("ticker", ""), e.get("date", ""))
        spp_lookup[key] = e.get("spp") or 0.0
        cat_lookup[key] = e.get("narrative_category", "")

    profiles: list[dict[str, Any]] = []
    distribution: Counter = Counter()

    for el in event_lags:
        ticker = el.get("ticker", "")
        date = el.get("date", "")
        key = (ticker, date)
        lag_days = el.get("lag_days")
        reacted = el.get("reacted", False)
        spp = spp_lookup.get(key, 0.0)
        cat = cat_lookup.get(key, "")
        alignment = alignment_lookup.get(key, "unknown")

        # Classification (priority order — 7 types)
        if cat in declining_cats or ticker in declining_tickers:
            response_type = "再編型"
            evidence = "ナラティブ消滅チェーンの衰退カテゴリに該当"
        elif cat in exhaustion_cats:
            response_type = "疲弊型"
            evidence = f"ナラティブ疲弊候補カテゴリ({cat})に該当"
        elif not reacted or lag_days is None:
            response_type = "無反応型"
            evidence = f"分析期間内に±{_REACTION_THRESHOLD_PCT}%超の反応なし"
        elif alignment == "contrarian":
            response_type = "逆行型"
            sentiment = el.get("sentiment", "unclear")
            direction = el.get("price_direction", "flat")
            evidence = (
                f"センチメント({sentiment})と価格方向({direction})が逆行"
            )
        elif lag_days <= 1 and spp < 0.3:
            response_type = "一時的過熱型"
            evidence = f"即時反応(lag={lag_days}日)だが低持続性(SPP={spp:.2f})"
        elif lag_days <= 1 and spp >= 0.3:
            response_type = "即時反応型"
            evidence = f"即時反応(lag={lag_days}日)かつ持続性あり(SPP={spp:.2f})"
        elif lag_days >= 3 and spp > 0.5:
            response_type = "遅延持続型"
            evidence = f"遅延反応(lag={lag_days}日)で高持続性(SPP={spp:.2f})"
        else:
            response_type = "即時反応型"
            evidence = f"lag={lag_days}日, SPP={spp:.2f}"

        profiles.append({
            "ticker": ticker,
            "date": date,
            "response_type": response_type,
            "evidence": evidence,
        })
        distribution[response_type] += 1

    total = len(profiles)
    dist_dict = {t: distribution.get(t, 0) for t in _RESPONSE_TYPES}
    dist_pct = {
        t: round(distribution.get(t, 0) / total, 3) if total else 0.0
        for t in _RESPONSE_TYPES
    }

    return {
        "event_profiles": profiles,
        "distribution": dist_dict,
        "distribution_pct": dist_pct,
    }

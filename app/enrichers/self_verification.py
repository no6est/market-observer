"""Self-verification for the narrative overheat detection system.

Provides functions to log daily prediction snapshots and retrospectively
verify whether overheat alerts were accurate, computing precision/recall
metrics over a rolling window.

Verdict logic:
- TP: Overheat triggered and AI events did NOT continue / price NOT sustained
  (correctly warned about a transient narrative bubble).
- FP: Overheat triggered but AI events continued and price sustained
  (events were real, warning was a false alarm).
- TN: No overheat triggered and conditions remained normal.
- FN: No overheat triggered but AI events continued unsupported
  (should have warned but didn't).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def save_prediction_log(
    db: Any,
    date: str,
    narrative_index: dict[str, Any],
    overheat_alert: dict[str, Any] | None,
    top_events: list[dict[str, Any]],
) -> None:
    """Save a daily prediction snapshot to the prediction_logs table.

    Persists the current day's narrative concentration metrics, overheat
    alert status, and top event tickers so that they can be verified
    against subsequent market data.

    Args:
        db: Database instance with a ``_connect()`` context manager.
        date: Date string in YYYY-MM-DD format.
        narrative_index: Dict from ``compute_narrative_concentration()`` with
            ai_ratio, category_distribution, etc.
        overheat_alert: Alert dict from ``detect_narrative_overheat()`` or None.
        top_events: List of top enriched events (up to 5) for the day.
    """
    ai_ratio = narrative_index.get("ai_ratio", 0.0)

    # Compute median evidence score from top events
    evidence_scores = [
        e.get("evidence_score") or 0.0 for e in top_events
    ]
    median_evidence = _median(evidence_scores) if evidence_scores else 0.0

    overheat_triggered = overheat_alert is not None

    # Extract tickers from top events
    top_tickers = [e.get("ticker", "") for e in top_events[:5]]
    top_tickers_json = json.dumps(top_tickers, ensure_ascii=False)

    # Snapshot of category distribution
    category_snapshot = json.dumps(
        narrative_index.get("category_distribution", {}),
        ensure_ascii=False,
    )

    try:
        with db._connect() as conn:
            # Ensure prediction_logs table exists
            conn.execute(
                """CREATE TABLE IF NOT EXISTS prediction_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    ai_ratio REAL,
                    median_evidence_score REAL,
                    overheat_triggered INTEGER NOT NULL DEFAULT 0,
                    top_tickers TEXT,
                    category_snapshot TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
            conn.execute(
                """INSERT OR REPLACE INTO prediction_logs
                   (date, ai_ratio, median_evidence_score,
                    overheat_triggered, top_tickers, category_snapshot)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    date,
                    ai_ratio,
                    round(median_evidence, 3),
                    int(overheat_triggered),
                    top_tickers_json,
                    category_snapshot,
                ),
            )
        logger.info(
            "Prediction log saved: date=%s, ai_ratio=%.3f, overheat=%s",
            date, ai_ratio, overheat_triggered,
        )
    except Exception:
        logger.exception("Failed to save prediction log for %s", date)


def verify_past_predictions(
    db: Any,
    target_date: str,
    verification_window: int = 3,
) -> dict[str, Any]:
    """Verify a past prediction by checking what happened in the following days.

    Looks at enriched events, anomalies, and articles after ``target_date``
    within the verification window to determine whether an overheat alert
    (or lack thereof) was correct.

    Args:
        db: Database instance with ``_connect()`` context manager and
            ``get_enriched_events_history()``, ``get_recent_articles()`` methods.
        target_date: The prediction date to verify (YYYY-MM-DD).
        verification_window: Number of days after target_date to examine.

    Returns:
        Dict with verification results including verdict (TP/FP/TN/FN)
        and supporting details.
    """
    result: dict[str, Any] = {
        "prediction_date": target_date,
        "overheat_triggered": False,
        "ai_events_continued": False,
        "price_trend_sustained": False,
        "tier1_followup": False,
        "verdict": "TN",
        "details": "",
    }

    try:
        # Load the prediction log for the target date
        prediction = _load_prediction_log(db, target_date)
        if prediction is None:
            result["details"] = f"No prediction log found for {target_date}"
            return result

        overheat_triggered = bool(prediction["overheat_triggered"])
        result["overheat_triggered"] = overheat_triggered

        top_tickers = _parse_json_field(prediction.get("top_tickers"), [])

        # Compute the date range for the verification window
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        window_start = (target_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        window_end = (
            target_dt + timedelta(days=verification_window)
        ).strftime("%Y-%m-%d")

        # Check condition 1: AI events continued after the prediction date
        ai_events_continued = _check_ai_events_continued(
            db, window_start, window_end,
        )
        result["ai_events_continued"] = ai_events_continued

        # Check condition 2: price trend sustained for top tickers
        price_trend_sustained = _check_price_trend_sustained(
            db, top_tickers, window_start, window_end,
        )
        result["price_trend_sustained"] = price_trend_sustained

        # Check condition 3: Tier1 media followed up
        tier1_followup = _check_tier1_followup(
            db, top_tickers, window_start, window_end,
        )
        result["tier1_followup"] = tier1_followup

        # Determine verdict
        verdict, details = _compute_verdict(
            overheat_triggered,
            ai_events_continued,
            price_trend_sustained,
        )
        result["verdict"] = verdict
        result["details"] = details

        logger.info(
            "Verification for %s: verdict=%s, overheat=%s, ai_cont=%s, "
            "price_sust=%s, tier1=%s",
            target_date, verdict, overheat_triggered,
            ai_events_continued, price_trend_sustained, tier1_followup,
        )

    except Exception:
        logger.exception("Failed to verify prediction for %s", target_date)
        result["details"] = f"Error verifying prediction for {target_date}"

    return result


def compute_verification_summary(
    db: Any,
    days: int = 7,
) -> dict[str, Any]:
    """Compute precision/recall summary over recent prediction logs.

    Verifies each prediction log from the last ``days`` days and
    aggregates the results into a confusion matrix with precision
    and recall metrics.

    Args:
        db: Database instance.
        days: Number of days of prediction history to summarize.

    Returns:
        Dict with total_predictions, TP/FP/TN/FN counts,
        precision, recall, and individual verdict details.
    """
    summary: dict[str, Any] = {
        "total_predictions": 0,
        "tp": 0,
        "fp": 0,
        "tn": 0,
        "fn": 0,
        "precision": None,
        "recall": None,
        "verdicts": [],
    }

    try:
        # Load prediction logs for the period
        prediction_dates = _load_prediction_dates(db, days)

        if not prediction_dates:
            logger.info("No prediction logs found for the last %d days", days)
            return summary

        verdicts: list[dict[str, Any]] = []
        for pred_date in prediction_dates:
            v = verify_past_predictions(db, pred_date)
            verdicts.append(v)

        summary["total_predictions"] = len(verdicts)
        summary["verdicts"] = verdicts

        # Count verdicts
        for v in verdicts:
            verdict = v.get("verdict", "TN")
            if verdict == "TP":
                summary["tp"] += 1
            elif verdict == "FP":
                summary["fp"] += 1
            elif verdict == "TN":
                summary["tn"] += 1
            elif verdict == "FN":
                summary["fn"] += 1

        # Compute precision: TP / (TP + FP)
        tp = summary["tp"]
        fp = summary["fp"]
        fn = summary["fn"]

        if tp + fp > 0:
            summary["precision"] = round(tp / (tp + fp), 3)

        # Compute recall: TP / (TP + FN)
        if tp + fn > 0:
            summary["recall"] = round(tp / (tp + fn), 3)

        logger.info(
            "Verification summary (%d days): total=%d, TP=%d, FP=%d, TN=%d, FN=%d, "
            "precision=%s, recall=%s",
            days, summary["total_predictions"],
            tp, fp, summary["tn"], fn,
            summary["precision"], summary["recall"],
        )

    except Exception:
        logger.exception("Failed to compute verification summary")

    return summary


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _median(values: list[float]) -> float:
    """Compute the median of a list of floats.

    Avoids importing statistics for this single utility.
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 0:
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0
    return sorted_vals[mid]


def _parse_json_field(value: Any, default: Any) -> Any:
    """Safely parse a JSON string field, returning default on failure."""
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _load_prediction_log(
    db: Any,
    date: str,
) -> dict[str, Any] | None:
    """Load a single prediction log row for a given date."""
    try:
        with db._connect() as conn:
            # Ensure table exists before querying
            conn.execute(
                """CREATE TABLE IF NOT EXISTS prediction_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    ai_ratio REAL,
                    median_evidence_score REAL,
                    overheat_triggered INTEGER NOT NULL DEFAULT 0,
                    top_tickers TEXT,
                    category_snapshot TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
            row = conn.execute(
                "SELECT * FROM prediction_logs WHERE date = ?",
                (date,),
            ).fetchone()
            return dict(row) if row else None
    except Exception:
        logger.debug("Failed to load prediction log for %s", date)
        return None


def _load_prediction_dates(
    db: Any,
    days: int,
) -> list[str]:
    """Load distinct prediction dates from the last N days."""
    try:
        cutoff = (
            datetime.utcnow() - timedelta(days=days)
        ).strftime("%Y-%m-%d")
        with db._connect() as conn:
            # Ensure table exists before querying
            conn.execute(
                """CREATE TABLE IF NOT EXISTS prediction_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    ai_ratio REAL,
                    median_evidence_score REAL,
                    overheat_triggered INTEGER NOT NULL DEFAULT 0,
                    top_tickers TEXT,
                    category_snapshot TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
            rows = conn.execute(
                """SELECT date FROM prediction_logs
                   WHERE date >= ?
                   ORDER BY date ASC""",
                (cutoff,),
            ).fetchall()
            return [row["date"] for row in rows]
    except Exception:
        logger.debug("Failed to load prediction dates")
        return []


def _check_ai_events_continued(
    db: Any,
    window_start: str,
    window_end: str,
) -> bool:
    """Check if AI category remained dominant in the verification window.

    Queries enriched_events within the date range and checks whether
    AI/LLM-related events still constituted a significant portion.
    """
    try:
        with db._connect() as conn:
            rows = conn.execute(
                """SELECT narrative_category, COUNT(*) as cnt
                   FROM enriched_events
                   WHERE date >= ? AND date <= ?
                   GROUP BY narrative_category
                   ORDER BY cnt DESC""",
                (window_start, window_end),
            ).fetchall()

        if not rows:
            return False

        total = sum(row["cnt"] for row in rows)
        if total == 0:
            return False

        ai_count = 0
        for row in rows:
            if row["narrative_category"] == "AI/LLM/自動化":
                ai_count = row["cnt"]
                break

        # AI category stayed dominant if it's the top category
        # or accounts for more than 40% of events
        ai_ratio = ai_count / total
        return ai_ratio > 0.4

    except Exception:
        logger.debug(
            "Failed to check AI event continuation for %s to %s",
            window_start, window_end,
        )
        return False


def _check_price_trend_sustained(
    db: Any,
    top_tickers: list[str],
    window_start: str,
    window_end: str,
) -> bool:
    """Check if any top tickers maintained anomaly presence in the window.

    Looks for anomalies (price_change or volume_spike) in the enriched_events
    table for the given tickers within the verification window.
    """
    if not top_tickers:
        return False

    try:
        placeholders = ",".join("?" for _ in top_tickers)
        with db._connect() as conn:
            row = conn.execute(
                f"""SELECT COUNT(*) as cnt
                    FROM enriched_events
                    WHERE date >= ? AND date <= ?
                      AND ticker IN ({placeholders})
                      AND signal_type IN ('price_change', 'volume_spike')""",
                (window_start, window_end, *top_tickers),
            ).fetchone()

        return row["cnt"] > 0 if row else False

    except Exception:
        logger.debug(
            "Failed to check price trend for tickers %s", top_tickers,
        )
        return False


def _check_tier1_followup(
    db: Any,
    top_tickers: list[str],
    window_start: str,
    window_end: str,
) -> bool:
    """Check if Tier1 media covered the story in the verification window.

    Queries the articles table for publications within the date range
    and checks if any match Tier1 source domains and mention
    the top tickers.
    """
    from app.enrichers.evidence_scorer import _TIER1_DOMAINS

    if not top_tickers:
        return False

    try:
        with db._connect() as conn:
            rows = conn.execute(
                """SELECT source, url, title
                   FROM articles
                   WHERE published_at >= ? AND published_at <= ?""",
                (window_start, window_end + " 23:59:59"),
            ).fetchall()

        if not rows:
            return False

        # Normalize ticker names for matching
        ticker_lower = {t.lower() for t in top_tickers if t}

        for article in rows:
            source = (article["source"] or "").lower()
            url = (article["url"] or "").lower()
            title = (article["title"] or "").lower()

            # Check if source is Tier1
            is_tier1 = any(
                domain in source or domain in url
                for domain in _TIER1_DOMAINS
            )
            if not is_tier1:
                continue

            # Check if article mentions any top ticker
            for ticker in ticker_lower:
                if ticker in title:
                    return True

        return False

    except Exception:
        logger.debug(
            "Failed to check Tier1 followup for tickers %s", top_tickers,
        )
        return False


def _compute_verdict(
    overheat_triggered: bool,
    ai_events_continued: bool,
    price_trend_sustained: bool,
) -> tuple[str, str]:
    """Determine the verification verdict based on observed outcomes.

    Args:
        overheat_triggered: Whether the overheat alert was raised on the prediction date.
        ai_events_continued: Whether AI events stayed dominant in the window.
        price_trend_sustained: Whether top tickers had follow-up price signals.

    Returns:
        Tuple of (verdict, details_string).
    """
    if overheat_triggered:
        if not ai_events_continued and not price_trend_sustained:
            return (
                "TP",
                "Overheat correctly warned: AI narrative faded and price "
                "signals did not sustain. The alert was justified.",
            )
        if ai_events_continued and price_trend_sustained:
            return (
                "FP",
                "Overheat was a false alarm: AI events continued with "
                "sustained price signals. The narrative was real.",
            )
        # Mixed signals — default to FP since the narrative had some
        # continuation, suggesting the warning was premature
        return (
            "FP",
            "Overheat alert with mixed follow-up: "
            f"ai_continued={ai_events_continued}, "
            f"price_sustained={price_trend_sustained}. "
            "Classified as false positive (partial continuation).",
        )
    else:
        if ai_events_continued and not price_trend_sustained:
            return (
                "FN",
                "Missed overheat: AI events continued without price "
                "backing. An alert should have been raised.",
            )
        # No overheat and conditions were normal or well-supported
        return (
            "TN",
            "No overheat and conditions normal: "
            f"ai_continued={ai_events_continued}, "
            f"price_sustained={price_trend_sustained}.",
        )

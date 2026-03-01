"""Monthly narrative analysis — lifecycle, retrospective, and structural persistence.

Aggregates 30 days of data to identify narrative lifecycles,
evaluate past hypotheses, trace regime arcs, and separate
structural signals from transient noise.

Reuses helpers from weekly_analysis and narrative_archive where possible.
"""

from __future__ import annotations

import logging
import statistics
from collections import Counter
from typing import Any

from app.enrichers.weekly_analysis import (
    _ALL_CATEGORIES,
    _SHOCK_TYPE_JA,
    _compute_event_persistence,
    _compute_narrative_average,
)

logger = logging.getLogger(__name__)

_REGIME_JA: dict[str, str] = {
    "normal": "平時",
    "high_vol": "高ボラ",
    "tightening": "引き締め",
}

_DIFFUSION_PATTERN_JA: dict[str, str] = {
    "sns_only": "SNSのみ",
    "sns_to_tier2": "SNS→Tier2",
    "sns_to_tier1": "SNS→Tier1",
    "tier1_direct": "Tier1直接",
    "no_coverage": "カバレッジなし",
}

_TRAJECTORY_ORDER = [
    "安定支配", "上昇", "新興", "不安定", "下降", "急騰消滅", "不在",
]


def compute_monthly_analysis(
    db: Any,
    days: int = 30,
    reference_date: str | None = None,
    llm_client: Any | None = None,
) -> dict[str, Any]:
    """Compute monthly narrative analysis from database history.

    Args:
        db: Database instance with narrative history and anomaly data.
        days: Number of days to analyze (default 30).
        reference_date: Reference date string (YYYY-MM-DD).
        llm_client: Optional Gemini client for LLM-enhanced analysis.

    Returns:
        Dict with all section data for the monthly report.
    """
    result: dict[str, Any] = {
        "narrative_lifecycle": {},
        "lifecycle_stats": {},
        "hypothesis_evaluations": [],
        "hypothesis_scorecard": {},
        "regime_arc": {
            "transitions": [],
            "dominant": "unknown",
            "stability_score": 0.0,
            "volatility_trend": "不明",
            "regime_composition": {},
        },
        "structural_persistence": {
            "core_tickers": [],
            "transient_tickers": [],
            "turnover_rate": 0.0,
        },
        "month_over_month": {"available": False},
        "shock_type_distribution": {},
        "propagation_structure": {},
        "forward_posture": {
            "attention_reallocation": [],
            "watch_tickers": [],
            "regime_outlook": "",
        },
        "narrative_trend": [],
        "regime_history": [],
        "period": f"過去{days}日間",
        # v7: Market response structure
        "reaction_lag": None,
        "watch_ticker_followup": None,
        "extinction_chains": None,
        "drift_evaluation": None,
        "response_profile": None,
        # v8: Direction-aware market response
        "direction_analysis": None,
        "regime_cross": None,
        "exhaustion": None,
        "exhaustion_evaluation": None,
    }

    # --- 1. Fetch base data ---
    enriched_history: list[dict[str, Any]] = []
    try:
        enriched_history = db.get_enriched_events_history(
            days=days, reference_date=reference_date,
        )
    except Exception:
        logger.debug("Failed to fetch enriched events history")

    narrative_history: list[dict[str, Any]] = []
    try:
        narrative_history = db.get_narrative_history(
            days=days, reference_date=reference_date,
        )
    except Exception:
        logger.debug("Failed to fetch narrative history")

    regime_history: list[dict[str, Any]] = []
    try:
        regime_history = db.get_regime_history(
            days=days, reference_date=reference_date,
        )
        result["regime_history"] = regime_history
    except Exception:
        logger.debug("Failed to fetch regime history")

    # Build narrative trend
    daily_data: dict[str, dict[str, float]] = {}
    for row in narrative_history:
        date = row["date"]
        if date not in daily_data:
            daily_data[date] = {}
        daily_data[date][row["category"]] = row["event_pct"]

    narrative_trend = [
        {"date": date, "categories": cats}
        for date, cats in sorted(daily_data.items())
    ]
    result["narrative_trend"] = narrative_trend

    # --- 2. Narrative Lifecycle ---
    try:
        from app.enrichers.narrative_archive import generate_monthly_summary

        monthly_summary = generate_monthly_summary(db, reference_date or "")
        lifecycle_cats = monthly_summary.get("narrative_lifecycle", {})

        # Attach trajectory classification
        sorted_dates = sorted(daily_data.keys())
        period_days = len(sorted_dates)

        for cat, stats in lifecycle_cats.items():
            series = [daily_data[d].get(cat, 0.0) for d in sorted_dates]
            stats["trajectory"] = _classify_trajectory(series, period_days)
            # Add peak_date
            if series:
                peak_idx = series.index(max(series))
                stats["peak_date"] = sorted_dates[peak_idx] if peak_idx < len(sorted_dates) else ""
            else:
                stats["peak_date"] = ""

        result["narrative_lifecycle"] = lifecycle_cats
        result["lifecycle_stats"] = {
            "period_days": monthly_summary.get("period_days", 0),
            "avg_lifespan_days": monthly_summary.get("avg_lifespan_days", 0.0),
            "avg_convergence_days": monthly_summary.get("avg_convergence_days", 0.0),
            "persistence_distribution": monthly_summary.get("persistence_distribution", {}),
        }
    except Exception:
        logger.debug("Failed to compute narrative lifecycle")

    # --- 3. Hypothesis Retrospective ---
    try:
        from app.enrichers.narrative_archive import evaluate_pending_hypotheses

        ref = reference_date or ""
        evaluations = evaluate_pending_hypotheses(db, ref)
        result["hypothesis_evaluations"] = evaluations

        hyp_stats = db.get_hypothesis_stats(days=days)
        result["hypothesis_scorecard"] = _compute_hypothesis_scorecard(
            evaluations, hyp_stats,
        )
    except Exception:
        logger.debug("Failed to compute hypothesis retrospective")

    # --- 4. Regime Arc ---
    try:
        result["regime_arc"] = _compute_regime_arc(regime_history)
    except Exception:
        logger.debug("Failed to compute regime arc")

    # --- 5. Structural Persistence ---
    try:
        result["structural_persistence"] = _compute_structural_persistence(
            enriched_history,
        )
    except Exception:
        logger.debug("Failed to compute structural persistence")

    # --- 6. Month-over-Month ---
    try:
        result["month_over_month"] = _compute_month_over_month(
            db, days, reference_date,
            current_enriched=enriched_history,
            current_narrative_trend=narrative_trend,
            current_regime=regime_history,
        )
    except Exception:
        logger.debug("Failed to compute month-over-month comparison")

    # --- 7. Shock / Propagation aggregation ---
    try:
        shock_counts: Counter = Counter()
        pattern_counts: Counter = Counter()
        for e in enriched_history:
            shock_type = e.get("shock_type") or "Unknown"
            shock_counts[_SHOCK_TYPE_JA.get(shock_type, shock_type)] += 1
            pattern = e.get("diffusion_pattern") or "no_coverage"
            pattern_counts[pattern] += 1

        result["shock_type_distribution"] = dict(shock_counts.most_common())
        result["propagation_structure"] = dict(pattern_counts)
    except Exception:
        logger.debug("Failed to compute shock/propagation distribution")

    # --- 8. Forward Posture (depends on sections 1-6) ---
    try:
        result["forward_posture"] = _generate_forward_posture(
            lifecycle=result,
            regime_arc=result["regime_arc"],
            persistence=result["structural_persistence"],
            mom=result["month_over_month"],
        )
    except Exception:
        logger.debug("Failed to generate forward posture")

    # --- 9. Reaction Lag (PHASE 1) + Direction Analysis ---
    try:
        from app.enrichers.market_response import compute_reaction_lag
        result["reaction_lag"] = compute_reaction_lag(
            db, days=days, reference_date=reference_date,
            llm_client=llm_client,
        )
        # Extract direction analysis from reaction lag stats
        rl = result["reaction_lag"]
        if rl and rl.get("stats"):
            result["direction_analysis"] = {
                "aligned_rate": rl["stats"].get("aligned_rate", 0.0),
                "contrarian_rate": rl["stats"].get("contrarian_rate", 0.0),
                "event_lags": rl.get("event_lags", []),
            }
    except Exception:
        logger.debug("Failed to compute reaction lag")

    # --- 10. Watch Ticker Follow-up (PHASE 2) ---
    try:
        from app.enrichers.market_response import compute_watch_ticker_followup
        result["watch_ticker_followup"] = compute_watch_ticker_followup(
            db, days=days, reference_date=reference_date,
        )
    except Exception:
        logger.debug("Failed to compute watch ticker followup")

    # --- 11. Narrative Extinction Chain (PHASE 3) ---
    try:
        from app.enrichers.market_response import detect_narrative_extinction_chain
        result["extinction_chains"] = detect_narrative_extinction_chain(
            db, days=days, reference_date=reference_date,
        )
    except Exception:
        logger.debug("Failed to detect narrative extinction chains")

    # --- 12. Drift Evaluation (PHASE 4) ---
    try:
        from app.enrichers.market_response import evaluate_drift_followups
        result["drift_evaluation"] = evaluate_drift_followups(
            db, reference_date=reference_date,
        )
    except Exception:
        logger.debug("Failed to evaluate drift followups")

    # --- 13. Response Profile (PHASE 5, depends on 9 + 11 + 14 + 15) ---
    try:
        from app.enrichers.market_response import compute_response_profile
        result["response_profile"] = compute_response_profile(
            db, days=days, reference_date=reference_date,
            reaction_lag_result=result.get("reaction_lag"),
            extinction_result=result.get("extinction_chains"),
            exhaustion_result=result.get("exhaustion"),
        )
    except Exception:
        logger.debug("Failed to compute response profile")

    # --- 14. Regime × Reaction Lag Cross Analysis ---
    try:
        from app.enrichers.market_response import compute_regime_reaction_cross
        result["regime_cross"] = compute_regime_reaction_cross(
            db, days=days, reference_date=reference_date,
        )
    except Exception:
        logger.debug("Failed to compute regime cross analysis")

    # --- 15. Narrative Exhaustion Detection ---
    try:
        from app.enrichers.market_response import detect_narrative_exhaustion
        result["exhaustion"] = detect_narrative_exhaustion(
            db, days=days, reference_date=reference_date,
        )
    except Exception:
        logger.debug("Failed to detect narrative exhaustion")

    # --- 16. Exhaustion Post-Evaluation ---
    try:
        from app.enrichers.market_response import evaluate_exhaustion_outcomes
        if result.get("exhaustion"):
            result["exhaustion_evaluation"] = evaluate_exhaustion_outcomes(
                db, result["exhaustion"],
                reference_date=reference_date,
            )
    except Exception:
        logger.debug("Failed to evaluate exhaustion outcomes")

    # Re-compute response profile if exhaustion was computed after initial profile
    if result.get("exhaustion") and result.get("response_profile"):
        try:
            from app.enrichers.market_response import compute_response_profile as _crp
            result["response_profile"] = _crp(
                db, days=days, reference_date=reference_date,
                reaction_lag_result=result.get("reaction_lag"),
                extinction_result=result.get("extinction_chains"),
                exhaustion_result=result.get("exhaustion"),
            )
        except Exception:
            pass

    logger.info(
        "Monthly analysis: %d lifecycle cats, %d evaluations, %d transitions, "
        "%d core tickers, MoM=%s",
        len(result["narrative_lifecycle"]),
        len(result["hypothesis_evaluations"]),
        len(result["regime_arc"].get("transitions", [])),
        len(result["structural_persistence"].get("core_tickers", [])),
        result["month_over_month"].get("available", False),
    )
    return result


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _classify_trajectory(
    daily_series: list[float],
    period_days: int,
) -> str:
    """Classify the trajectory of a narrative category over the period.

    Args:
        daily_series: Daily event_pct values for a single category.
        period_days: Total number of observation days.

    Returns:
        One of: "安定支配", "上昇", "下降", "急騰消滅", "新興", "不安定", "不在"
    """
    if not daily_series or period_days == 0:
        return "不在"

    active_days = sum(1 for v in daily_series if v >= 0.10)
    persistence_ratio = active_days / period_days

    # Rule 1: absent
    if persistence_ratio < 0.1:
        return "不在"

    # Rule 2: stable dominance (high persistence + low variance)
    if persistence_ratio >= 0.8:
        if len(daily_series) >= 2:
            var = statistics.variance(daily_series)
        else:
            var = 0.0
        if var < 0.01:
            return "安定支配"

    # Split into halves for trend detection
    mid = len(daily_series) // 2
    if mid == 0:
        mid = 1
    first_half = daily_series[:mid]
    second_half = daily_series[mid:]

    first_avg = sum(first_half) / len(first_half) if first_half else 0.0
    second_avg = sum(second_half) / len(second_half) if second_half else 0.0

    # Rule 3: emerging (absent in first half, present in second half)
    # Check before rising/falling — a category that didn't exist is "emerging",
    # not merely "rising".
    first_present = any(v >= 0.10 for v in first_half)
    second_present = any(v >= 0.10 for v in second_half)
    if not first_present and second_present and second_avg >= 0.10:
        return "新興"

    # Rule 4: rising
    if second_avg > first_avg + 0.10:
        return "上昇"

    # Rule 5: falling
    if first_avg > second_avg + 0.10:
        return "下降"

    # Rule 6: spike and fade
    avg = sum(daily_series) / len(daily_series)
    peak = max(daily_series)
    if avg > 0 and peak > avg * 2.0:
        peak_idx = daily_series.index(peak)
        convergence = 0
        if peak_idx < len(daily_series) - 1:
            for i in range(peak_idx + 1, len(daily_series)):
                convergence += 1
                if daily_series[i] < 0.05:
                    break
        if 0 < convergence < 5:
            return "急騰消滅"

    # Default
    return "不安定"


def _compute_regime_arc(
    regime_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute regime arc: transitions, dominant regime, stability, volatility trend.

    Args:
        regime_history: Daily regime snapshots from DB.

    Returns:
        Dict with transitions, dominant, stability_score, volatility_trend,
        regime_composition.
    """
    empty = {
        "transitions": [],
        "dominant": "unknown",
        "stability_score": 0.0,
        "volatility_trend": "不明",
        "regime_composition": {},
    }
    if not regime_history:
        return empty

    sorted_history = sorted(regime_history, key=lambda r: r.get("date", ""))
    total_days = len(sorted_history)

    # Regime counts
    regime_counts: Counter = Counter()
    for r in sorted_history:
        regime_counts[r.get("regime", "unknown")] += 1

    dominant = regime_counts.most_common(1)[0][0]
    stability_score = regime_counts[dominant] / total_days if total_days > 0 else 0.0

    # Transitions
    transitions: list[dict[str, str]] = []
    for i in range(1, len(sorted_history)):
        prev = sorted_history[i - 1]
        curr = sorted_history[i]
        if prev.get("regime") != curr.get("regime"):
            transitions.append({
                "date": curr.get("date", ""),
                "from": prev.get("regime", "unknown"),
                "to": curr.get("regime", "unknown"),
            })

    # Volatility trend (first half vs second half)
    vols = [
        r.get("avg_volatility", 0)
        for r in sorted_history
        if r.get("avg_volatility") is not None
    ]
    if len(vols) >= 2:
        mid = len(vols) // 2
        first_avg_vol = sum(vols[:mid]) / mid
        second_avg_vol = sum(vols[mid:]) / (len(vols) - mid)
        diff = second_avg_vol - first_avg_vol
        if abs(diff) < 0.005:
            volatility_trend = "横ばい"
        elif diff > 0:
            volatility_trend = "上昇"
        else:
            volatility_trend = "下降"
    else:
        volatility_trend = "不明"

    # Regime composition
    regime_composition = {
        regime: {"days": count, "pct": round(count / total_days, 3)}
        for regime, count in regime_counts.most_common()
    }

    return {
        "transitions": transitions,
        "dominant": dominant,
        "stability_score": round(stability_score, 3),
        "volatility_trend": volatility_trend,
        "regime_composition": regime_composition,
    }


def _compute_structural_persistence(
    enriched_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Partition tickers into core (60%+), mid, and transient (<20%).

    Args:
        enriched_history: 30 days of enriched events.

    Returns:
        Dict with core_tickers, transient_tickers, turnover_rate,
        all_persistence.
    """
    persistence = _compute_event_persistence(enriched_history)
    if not persistence:
        return {
            "core_tickers": [],
            "transient_tickers": [],
            "turnover_rate": 0.0,
            "all_persistence": [],
        }

    total_days = persistence[0]["total_days"] if persistence else 1

    core: list[dict[str, Any]] = []
    transient: list[dict[str, Any]] = []
    for ep in persistence:
        ratio = ep["days_appeared"] / total_days if total_days > 0 else 0.0
        ep["appearance_ratio"] = round(ratio, 3)
        if ratio >= 0.6:
            core.append(ep)
        elif ratio < 0.2:
            transient.append(ep)

    all_tickers = len(persistence)
    turnover_rate = len(transient) / all_tickers if all_tickers > 0 else 0.0

    return {
        "core_tickers": core,
        "transient_tickers": transient,
        "turnover_rate": round(turnover_rate, 3),
        "all_persistence": persistence,
    }


def _compute_month_over_month(
    db: Any,
    days: int,
    reference_date: str | None,
    *,
    current_enriched: list[dict[str, Any]],
    current_narrative_trend: list[dict[str, Any]],
    current_regime: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare current month with previous month.

    Args:
        db: Database instance.
        days: Period length in days.
        reference_date: Current period reference date.
        current_enriched: Current period enriched events.
        current_narrative_trend: Current period narrative trend.
        current_regime: Current period regime history.

    Returns:
        Dict with narrative_delta, shock_delta, regime comparison,
        ticker turnover. available=False if insufficient previous data.
    """
    from datetime import datetime, timedelta

    if reference_date:
        ref_dt = datetime.strptime(reference_date, "%Y-%m-%d")
    else:
        ref_dt = datetime.utcnow()
    prev_ref = (ref_dt - timedelta(days=days)).strftime("%Y-%m-%d")

    # Fetch previous month data
    prev_enriched = db.get_enriched_events_history(
        days=days, reference_date=prev_ref,
    )
    prev_narrative_raw = db.get_narrative_history(
        days=days, reference_date=prev_ref,
    )
    prev_regime = db.get_regime_history(days=days, reference_date=prev_ref)

    # Check data sufficiency
    prev_dates = {r["date"] for r in prev_narrative_raw if r.get("date")}
    if len(prev_dates) < 2:
        return {"available": False}

    # Build previous narrative trend
    prev_daily: dict[str, dict[str, float]] = {}
    for row in prev_narrative_raw:
        date = row["date"]
        if date not in prev_daily:
            prev_daily[date] = {}
        prev_daily[date][row["category"]] = row["event_pct"]
    prev_narrative_trend = [
        {"date": d, "categories": cats}
        for d, cats in sorted(prev_daily.items())
    ]

    sorted_prev_dates = sorted(prev_dates)
    prev_period = (
        f"{sorted_prev_dates[0]}〜{sorted_prev_dates[-1]} "
        f"({len(sorted_prev_dates)}日分)"
    )

    # --- Narrative delta ---
    curr_avg = _compute_narrative_average(current_narrative_trend)
    prev_avg = _compute_narrative_average(prev_narrative_trend)
    all_cats = set(curr_avg.keys()) | set(prev_avg.keys())
    narrative_delta = {}
    for cat in sorted(all_cats):
        curr_pct = curr_avg.get(cat, 0.0)
        prev_pct = prev_avg.get(cat, 0.0)
        narrative_delta[cat] = {
            "current_pct": round(curr_pct, 4),
            "previous_pct": round(prev_pct, 4),
            "delta_pt": round(curr_pct - prev_pct, 4),
        }

    # --- Shock type delta ---
    prev_shock_counts: Counter = Counter()
    for e in prev_enriched:
        st = e.get("shock_type") or "Unknown"
        prev_shock_counts[_SHOCK_TYPE_JA.get(st, st)] += 1
    curr_shock_counts: Counter = Counter()
    for e in current_enriched:
        st = e.get("shock_type") or "Unknown"
        curr_shock_counts[_SHOCK_TYPE_JA.get(st, st)] += 1
    all_shocks = set(prev_shock_counts.keys()) | set(curr_shock_counts.keys())
    shock_type_delta = {}
    for st in sorted(all_shocks):
        curr_c = curr_shock_counts.get(st, 0)
        prev_c = prev_shock_counts.get(st, 0)
        shock_type_delta[st] = {
            "current": curr_c,
            "previous": prev_c,
            "delta": curr_c - prev_c,
        }

    # --- Regime comparison ---
    def _dominant_regime(regime_list: list[dict[str, Any]]) -> str:
        if not regime_list:
            return "unknown"
        counts: Counter = Counter()
        for r in regime_list:
            counts[r.get("regime", "unknown")] += 1
        return counts.most_common(1)[0][0]

    curr_dom = _dominant_regime(current_regime)
    prev_dom = _dominant_regime(prev_regime)

    # --- Ticker turnover ---
    curr_tickers = {e.get("ticker") for e in current_enriched if e.get("ticker")}
    prev_tickers = {e.get("ticker") for e in prev_enriched if e.get("ticker")}
    new_tickers = sorted(curr_tickers - prev_tickers)
    gone_tickers = sorted(prev_tickers - curr_tickers)
    continued_tickers = sorted(curr_tickers & prev_tickers)

    # --- Event count delta ---
    event_count_delta = {
        "current": len(current_enriched),
        "previous": len(prev_enriched),
        "delta": len(current_enriched) - len(prev_enriched),
    }

    return {
        "available": True,
        "narrative_delta": narrative_delta,
        "shock_type_delta": shock_type_delta,
        "regime_comparison": {
            "changed": curr_dom != prev_dom,
            "previous_regime": prev_dom,
            "current_regime": curr_dom,
        },
        "ticker_turnover": {
            "new": new_tickers,
            "gone": gone_tickers,
            "continued": continued_tickers,
        },
        "event_count_delta": event_count_delta,
        "previous_period": prev_period,
    }


def _compute_hypothesis_scorecard(
    evaluations: list[dict[str, Any]],
    stats: dict[str, Any],
) -> dict[str, Any]:
    """Compute hypothesis evaluation scorecard.

    Args:
        evaluations: List of evaluation result dicts from
            evaluate_pending_hypotheses().
        stats: Hypothesis stats dict from db.get_hypothesis_stats().

    Returns:
        Dict with confirmed, expired, inconclusive counts and
        confirmation_rate.
    """
    if not evaluations and not stats:
        return {}

    confirmed = sum(1 for e in evaluations if e.get("evaluation") == "confirmed")
    expired = sum(1 for e in evaluations if e.get("evaluation") == "expired")
    inconclusive = sum(1 for e in evaluations if e.get("evaluation") == "inconclusive")
    total_evaluated = len(evaluations)
    pending = stats.get("pending", 0) if stats else 0

    confirmation_rate = confirmed / total_evaluated if total_evaluated > 0 else 0.0

    return {
        "total_evaluated": total_evaluated,
        "confirmed": confirmed,
        "expired": expired,
        "inconclusive": inconclusive,
        "confirmation_rate": round(confirmation_rate, 3),
        "pending": pending,
    }


def _generate_forward_posture(
    lifecycle: dict[str, Any],
    regime_arc: dict[str, Any],
    persistence: dict[str, Any],
    mom: dict[str, Any],
) -> dict[str, Any]:
    """Generate forward-looking attention allocation for next month.

    Args:
        lifecycle: Full analysis result dict (contains narrative_lifecycle).
        regime_arc: Regime arc analysis.
        persistence: Structural persistence analysis.
        mom: Month-over-month comparison.

    Returns:
        Dict with attention_reallocation, watch_tickers, regime_outlook.
    """
    attention_reallocation: list[dict[str, str]] = []
    watch_tickers: list[dict[str, str]] = []

    # From lifecycle: rising/emerging categories deserve more attention
    categories = lifecycle.get("narrative_lifecycle", {})
    for cat in _ALL_CATEGORIES:
        data = categories.get(cat)
        if data is None:
            continue
        trajectory = data.get("trajectory", "")
        avg_pct = data.get("avg_pct", 0.0)
        if trajectory == "上昇":
            attention_reallocation.append({
                "category": cat,
                "action": "注目度を引き上げ",
                "reason": f"上昇トレンド（月平均{avg_pct * 100:.0f}%）",
            })
        elif trajectory == "新興":
            attention_reallocation.append({
                "category": cat,
                "action": "新規監視対象として追加",
                "reason": "今月新たに出現したカテゴリ",
            })
        elif trajectory == "下降":
            attention_reallocation.append({
                "category": cat,
                "action": "見落としリスクに注意",
                "reason": "下降トレンドだが構造変化の見逃しに注意",
            })

    # From MoM: new tickers that appeared this month
    if mom.get("available"):
        new_tickers = mom.get("ticker_turnover", {}).get("new", [])
        for t in new_tickers[:3]:
            watch_tickers.append({
                "ticker": t,
                "reason": "今月新たに出現した銘柄",
            })

    # From persistence: core tickers
    for ticker_data in persistence.get("core_tickers", [])[:5]:
        watch_tickers.append({
            "ticker": ticker_data["ticker"],
            "reason": (
                f"コア銘柄（出現{ticker_data['days_appeared']}日、"
                f"SPP推移: {ticker_data['spp_trend']}）"
            ),
        })

    # Regime outlook
    dominant = regime_arc.get("dominant", "unknown")
    stability = regime_arc.get("stability_score", 0.0)
    vol_trend = regime_arc.get("volatility_trend", "不明")
    dominant_ja = _REGIME_JA.get(dominant, dominant)

    if stability >= 0.8:
        regime_outlook = (
            f"{dominant_ja}レジームが安定（安定度{stability * 100:.0f}%）。"
            f"急変リスクは低いが油断せず監視。"
        )
    elif stability >= 0.5:
        regime_outlook = (
            f"{dominant_ja}レジームが主体だが不安定"
            f"（安定度{stability * 100:.0f}%）。"
            f"遷移の可能性に備えた監視を推奨。"
        )
    else:
        regime_outlook = (
            f"レジーム不安定（安定度{stability * 100:.0f}%）。"
            f"複数レジーム間を遷移中。慎重な監視を推奨。"
        )

    if vol_trend == "上昇":
        regime_outlook += " ボラティリティ上昇傾向あり。"

    return {
        "attention_reallocation": attention_reallocation,
        "watch_tickers": watch_tickers,
        "regime_outlook": regime_outlook,
    }

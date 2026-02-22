"""Weekly meta-analysis for structural change observation.

Aggregates 7 days of data to identify longer-term trends,
narrative shifts, and generate organizational impact hypotheses.

v2: Adds bias_correction_actions — suggested monitoring weight
adjustments for the coming week based on distribution imbalances.

v3: Adds propagation_structure (media diffusion pattern counts),
spp_top3 (highest persistence probability events), and
verification_summary placeholder (filled by caller).

v6: Hypothesis Context Integration — hypotheses enriched with
per-ticker context (signal types, shock, regime, article titles).
Max 3 hypotheses with evidence_elements and data_period.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

_SHOCK_TYPE_JA: dict[str, str] = {
    "Tech shock": "テクノロジーショック",
    "Business model shock": "ビジネスモデルショック",
    "Regulation shock": "規制ショック",
    "Narrative shift": "ナラティブシフト",
    "Execution signal": "業績シグナル",
}

# All 8 narrative categories for completeness checking
_ALL_CATEGORIES = [
    "AI/LLM/自動化",
    "規制/政策/地政学",
    "金融/金利/流動性",
    "エネルギー/資源",
    "半導体/供給網",
    "ガバナンス/経営",
    "社会/労働/教育",
    "その他",
]


def compute_weekly_analysis(
    db: Any,
    days: int = 7,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Compute weekly meta-analysis from database history.

    Args:
        db: Database instance with narrative history and anomaly data.
        days: Number of days to analyze.

    Returns:
        Dict with keys:
        - shock_type_distribution: dict of shock type counts
        - narrative_trend: list of daily narrative snapshots
        - non_ai_highlights: list of notable non-AI events
        - turning_point_candidates: list of potential inflection points
        - org_impact_hypotheses: list of organizational impact hypotheses
        - bias_correction_actions: list of suggested monitoring adjustments
        - period: str describing the analysis period
    """
    result: dict[str, Any] = {
        "shock_type_distribution": {},
        "narrative_trend": [],
        "non_ai_highlights": [],
        "turning_point_candidates": [],
        "org_impact_hypotheses": [],
        "bias_correction_actions": [],
        "propagation_structure": {},
        "spp_top3": [],
        "regime_history": [],
        "event_persistence": [],
        "week_over_week": {},
        "regime_narrative_cross": [],
        "early_drift_candidates": [],
        "period": f"過去{days}日間",
    }

    # 1. Shock type distribution from enriched events
    enriched_history: list[dict[str, Any]] = []
    try:
        enriched_history = db.get_enriched_events_history(days=days, reference_date=reference_date)
        shock_counts: Counter = Counter()
        for e in enriched_history:
            shock_type = e.get("shock_type") or "Unknown"
            shock_counts[shock_type] += 1

        result["shock_type_distribution"] = {
            _SHOCK_TYPE_JA.get(k, k): v
            for k, v in shock_counts.most_common()
        }
    except Exception:
        logger.debug("Failed to compute shock type distribution")

    # 2. Narrative trend from snapshots
    try:
        history = db.get_narrative_history(days=days, reference_date=reference_date)
        daily_data: dict[str, dict[str, float]] = {}
        for row in history:
            date = row["date"]
            if date not in daily_data:
                daily_data[date] = {}
            daily_data[date][row["category"]] = row["event_pct"]

        result["narrative_trend"] = [
            {"date": date, "categories": cats}
            for date, cats in sorted(daily_data.items())
        ]
    except Exception:
        logger.debug("Failed to compute narrative trend")

    # 3. Non-AI highlights from enriched events with low ai_centricity
    try:
        non_ai = []
        for e in enriched_history:
            ai_centricity = e.get("ai_centricity") or 0.0
            sis = e.get("sis") or 0.0
            if ai_centricity < 0.3 and sis > 0.0:
                non_ai.append({
                    "ticker": e.get("ticker", ""),
                    "summary": e.get("summary") or "N/A",
                    "score": sis,
                    "narrative_category": e.get("narrative_category", "その他"),
                    "shock_type": e.get("shock_type", ""),
                    "ai_centricity": ai_centricity,
                })
        result["non_ai_highlights"] = sorted(
            non_ai, key=lambda x: x["score"], reverse=True
        )[:5]
    except Exception:
        logger.debug("Failed to extract non-AI highlights")

    # 4. Turning point candidates: persistent max-swing detection
    try:
        trend = result["narrative_trend"]
        if len(trend) >= 3:
            result["turning_point_candidates"] = _detect_turning_points(trend)
        elif len(trend) == 2:
            # Fallback: first-vs-last for short data
            early = trend[0]["categories"]
            late = trend[-1]["categories"]
            all_cats = set(early.keys()) | set(late.keys())
            for cat in all_cats:
                early_pct = early.get(cat, 0)
                late_pct = late.get(cat, 0)
                delta = late_pct - early_pct
                if abs(delta) >= 0.15:
                    direction = "上昇" if delta > 0 else "下降"
                    result["turning_point_candidates"].append({
                        "category": cat,
                        "direction": direction,
                        "delta": round(delta, 3),
                        "description": (
                            f"「{cat}」が{abs(delta)*100:.0f}ポイント{direction}"
                            f"（{early_pct*100:.0f}% → {late_pct*100:.0f}%）"
                        ),
                    })
    except Exception:
        logger.debug("Failed to detect turning points")

    # 5. Organizational impact hypotheses
    try:
        result["org_impact_hypotheses"] = _generate_org_hypotheses(
            result["shock_type_distribution"],
            result["turning_point_candidates"],
        )
    except Exception:
        logger.debug("Failed to generate org impact hypotheses")

    # 6. Bias correction actions
    try:
        result["bias_correction_actions"] = _generate_bias_corrections(
            result["shock_type_distribution"],
            result["narrative_trend"],
            enriched_history,
        )
    except Exception:
        logger.debug("Failed to generate bias correction actions")

    # 7. Propagation structure (media diffusion pattern counts)
    try:
        pattern_counts: Counter = Counter()
        for e in enriched_history:
            pattern = e.get("diffusion_pattern") or "no_coverage"
            pattern_counts[pattern] += 1
        result["propagation_structure"] = dict(pattern_counts)
    except Exception:
        logger.debug("Failed to compute propagation structure")

    # 8. SPP Top 3 (highest structural persistence probability)
    #    Deduplicate by ticker — keep the latest date per ticker.
    try:
        latest_by_ticker: dict[str, dict[str, Any]] = {}
        for e in enriched_history:
            if e.get("spp") is None:
                continue
            ticker = e.get("ticker", "")
            existing = latest_by_ticker.get(ticker)
            if existing is None or (e.get("date", "") > existing.get("date", "")):
                latest_by_ticker[ticker] = e
        deduped = sorted(
            latest_by_ticker.values(),
            key=lambda x: x.get("spp") or 0,
            reverse=True,
        )
        result["spp_top3"] = [
            {
                "ticker": e.get("ticker", ""),
                "spp": e.get("spp", 0.0),
                "summary": e.get("summary") or "N/A",
                "shock_type": e.get("shock_type", ""),
                "diffusion_pattern": e.get("diffusion_pattern", ""),
            }
            for e in deduped[:3]
        ]
    except Exception:
        logger.debug("Failed to compute SPP top3")

    # 9. Regime history
    try:
        regime_history = db.get_regime_history(days=days, reference_date=reference_date)
        result["regime_history"] = regime_history
    except Exception:
        logger.debug("Failed to get regime history")

    # 10. Event persistence tracking
    try:
        result["event_persistence"] = _compute_event_persistence(enriched_history)
        # Attach days_appeared to spp_top3 entries
        persistence_map = {
            ep["ticker"]: ep["days_appeared"]
            for ep in result["event_persistence"]
        }
        for entry in result["spp_top3"]:
            entry["days_appeared"] = persistence_map.get(entry["ticker"], 1)
    except Exception:
        logger.debug("Failed to compute event persistence")

    # 11. Week-over-week comparison
    try:
        result["week_over_week"] = _compute_week_over_week(
            db, days, reference_date,
            current_enriched=enriched_history,
            current_narrative_trend=result["narrative_trend"],
            current_regime=result["regime_history"],
        )
    except Exception:
        logger.debug("Failed to compute week-over-week comparison")

    # 12. Regime × Narrative cross-analysis
    try:
        result["regime_narrative_cross"] = _compute_regime_narrative_cross(
            result["regime_history"],
            result["narrative_trend"],
        )
    except Exception:
        logger.debug("Failed to compute regime-narrative cross analysis")

    # 13. Fetch articles for hypothesis context (best-effort)
    articles: list[dict[str, Any]] = []
    try:
        articles = db.get_articles_by_date_range(days=days, reference_date=reference_date)
    except Exception:
        logger.debug("Failed to fetch articles for hypothesis context")

    # 14. Cross-hypotheses from persistence, regime, and WoW data
    try:
        cross_hyps = _generate_cross_hypotheses(
            event_persistence=result["event_persistence"],
            regime_narrative_cross=result["regime_narrative_cross"],
            week_over_week=result["week_over_week"],
            days=days,
            enriched_history=enriched_history,
            regime_history=result["regime_history"],
            articles=articles,
            reference_date=reference_date,
        )
        result["org_impact_hypotheses"].extend(cross_hyps)
    except Exception:
        logger.debug("Failed to generate cross hypotheses")

    # 15. Early drift detection
    try:
        result["early_drift_candidates"] = _detect_early_drift(
            enriched_history, result["narrative_trend"],
            db, reference_date=reference_date,
        )
    except Exception:
        logger.debug("Failed to detect early drift")

    logger.info(
        "Weekly analysis: %d shock types, %d trend days, %d turning points, %d corrections, %d drifts",
        len(result["shock_type_distribution"]),
        len(result["narrative_trend"]),
        len(result["turning_point_candidates"]),
        len(result["bias_correction_actions"]),
        len(result["early_drift_candidates"]),
    )
    return result


def _compute_event_persistence(
    enriched_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute per-ticker appearance days and SPP trend.

    total_days is the number of distinct observed dates in the dataset,
    not calendar days.
    """
    if not enriched_history:
        return []

    total_days = len({e["date"] for e in enriched_history if e.get("date")})

    # Group by ticker: dates appeared + first/latest SPP
    ticker_data: dict[str, dict[str, Any]] = {}
    for e in enriched_history:
        ticker = e.get("ticker", "")
        if not ticker:
            continue
        if ticker not in ticker_data:
            ticker_data[ticker] = {"dates": set(), "first_spp": None, "latest_spp": None, "first_date": None, "latest_date": None}
        td = ticker_data[ticker]
        td["dates"].add(e.get("date", ""))
        spp = e.get("spp")
        if spp is not None:
            edate = e.get("date", "")
            if td["first_date"] is None or edate < td["first_date"]:
                td["first_date"] = edate
                td["first_spp"] = spp
            if td["latest_date"] is None or edate > td["latest_date"]:
                td["latest_date"] = edate
                td["latest_spp"] = spp

    persistence: list[dict[str, Any]] = []
    for ticker, td in ticker_data.items():
        days_appeared = len(td["dates"])
        first_spp = td["first_spp"]
        latest_spp = td["latest_spp"]
        if first_spp is not None and latest_spp is not None:
            diff = latest_spp - first_spp
            if abs(diff) < 0.05:
                spp_trend = "横ばい"
            elif diff > 0:
                spp_trend = "上昇"
            else:
                spp_trend = "下降"
        else:
            spp_trend = "横ばい"
        persistence.append({
            "ticker": ticker,
            "days_appeared": days_appeared,
            "total_days": total_days,
            "spp_trend": spp_trend,
            "latest_spp": latest_spp or 0.0,
        })

    # Sort by days_appeared desc, then latest_spp desc
    persistence.sort(key=lambda x: (-x["days_appeared"], -x["latest_spp"]))
    return persistence


def _compute_week_over_week(
    db: Any,
    days: int,
    reference_date: str | None,
    *,
    current_enriched: list[dict[str, Any]],
    current_narrative_trend: list[dict[str, Any]],
    current_regime: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare current week with previous week."""
    from datetime import datetime, timedelta

    if reference_date:
        ref_dt = datetime.strptime(reference_date, "%Y-%m-%d")
    else:
        ref_dt = datetime.utcnow()
    prev_ref = (ref_dt - timedelta(days=days)).strftime("%Y-%m-%d")

    # Fetch previous week data
    prev_enriched = db.get_enriched_events_history(days=days, reference_date=prev_ref)
    prev_narrative_raw = db.get_narrative_history(days=days, reference_date=prev_ref)
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

    # Period string
    sorted_prev_dates = sorted(prev_dates)
    prev_period = f"{sorted_prev_dates[0]}〜{sorted_prev_dates[-1]} ({len(sorted_prev_dates)}日分)"

    # Shock type delta
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
        shock_type_delta[st] = {"current": curr_c, "previous": prev_c, "delta": curr_c - prev_c}

    # Narrative delta
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

    # Regime shift — dominant regime (mode)
    def _dominant_regime(regime_list: list[dict[str, Any]]) -> str:
        if not regime_list:
            return "unknown"
        counts: Counter = Counter()
        for r in regime_list:
            counts[r.get("regime", "unknown")] += 1
        return counts.most_common(1)[0][0]

    curr_dom = _dominant_regime(current_regime)
    prev_dom = _dominant_regime(prev_regime)

    # Event count delta
    event_count_delta = {
        "current": len(current_enriched),
        "previous": len(prev_enriched),
        "delta": len(current_enriched) - len(prev_enriched),
    }

    return {
        "available": True,
        "shock_type_delta": shock_type_delta,
        "narrative_delta": narrative_delta,
        "regime_shift": {
            "changed": curr_dom != prev_dom,
            "previous_regime": prev_dom,
            "current_regime": curr_dom,
        },
        "event_count_delta": event_count_delta,
        "previous_period": prev_period,
    }


def _compute_regime_narrative_cross(
    regime_history: list[dict[str, Any]],
    narrative_trend: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect co-movements between regime changes and narrative shifts.

    Findings use co-occurrence language only. Causal terms are prohibited.
    """
    if not regime_history or not narrative_trend:
        return []

    # Index data by date
    regime_by_date: dict[str, str] = {}
    for r in regime_history:
        regime_by_date[r["date"]] = r.get("regime", "unknown")
    narrative_by_date: dict[str, dict[str, float]] = {}
    for n in narrative_trend:
        narrative_by_date[n["date"]] = n["categories"]

    # Find common dates, sorted
    common_dates = sorted(set(regime_by_date.keys()) & set(narrative_by_date.keys()))
    if len(common_dates) < 2:
        return []

    findings: list[dict[str, Any]] = []

    _REGIME_JA = {"normal": "平時", "high_vol": "高ボラ", "tightening": "引き締め"}

    for i in range(1, len(common_dates)):
        prev_date = common_dates[i - 1]
        curr_date = common_dates[i]
        prev_regime = regime_by_date[prev_date]
        curr_regime = regime_by_date[curr_date]

        # Check regime transition
        if prev_regime != curr_regime:
            prev_cats = narrative_by_date.get(prev_date, {})
            curr_cats = narrative_by_date.get(curr_date, {})
            for cat in set(prev_cats.keys()) | set(curr_cats.keys()):
                delta = curr_cats.get(cat, 0.0) - prev_cats.get(cat, 0.0)
                if abs(delta) >= 0.10:
                    direction = "増加" if delta > 0 else "減少"
                    findings.append({
                        "date": curr_date,
                        "finding": (
                            f"レジーム変化（{_REGIME_JA.get(prev_regime, prev_regime)}→"
                            f"{_REGIME_JA.get(curr_regime, curr_regime)}）と"
                            f"「{cat}」の{abs(delta)*100:.0f}pt{direction}が同時期に観測"
                        ),
                        "regime_from": prev_regime,
                        "regime_to": curr_regime,
                        "narrative_category": cat,
                        "delta": round(delta, 3),
                    })

        # Check regime anomaly + narrative concentration co-occurrence
        if curr_regime in ("high_vol", "tightening"):
            curr_cats = narrative_by_date.get(curr_date, {})
            for cat, pct in curr_cats.items():
                if pct > 0.60:
                    findings.append({
                        "date": curr_date,
                        "finding": (
                            f"レジーム異常（{_REGIME_JA.get(curr_regime, curr_regime)}）と"
                            f"「{cat}」ナラティブ集中（{pct*100:.0f}%）が共起"
                        ),
                        "regime_from": curr_regime,
                        "regime_to": curr_regime,
                        "narrative_category": cat,
                        "delta": round(pct, 3),
                    })

    return findings


_SIGNAL_TYPE_JA: dict[str, str] = {
    "price_change": "価格変動",
    "volume_spike": "出来高急増",
    "mention_surge": "言及急増",
}

_REGIME_JA: dict[str, str] = {
    "normal": "平時",
    "high_vol": "高ボラ",
    "tightening": "引き締め",
}


def _build_ticker_context(
    enriched_history: list[dict[str, Any]],
    regime_history: list[dict[str, Any]],
    ticker: str,
    articles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build rich context for a ticker from enriched events and regime.

    Returns a dict with structured evidence about what signals were
    detected, what shock type and narrative category they belong to,
    persistence stats, regime context, and related article titles.
    """
    ticker_events = [e for e in enriched_history if e.get("ticker") == ticker]
    if not ticker_events:
        return {}

    signal_types = list({e.get("signal_type", "") for e in ticker_events if e.get("signal_type")})
    shock_types = list({e.get("shock_type", "") for e in ticker_events if e.get("shock_type")})
    categories = list({e.get("narrative_category", "") for e in ticker_events if e.get("narrative_category")})

    dates = sorted({e.get("date", "") for e in ticker_events if e.get("date")})
    days_appeared = len(dates)

    # Deduplicate SPP by date (keep first entry per date, matching
    # _compute_event_persistence logic for consistency)
    first_spp = None
    latest_spp = None
    first_date = None
    latest_date = None
    for e in ticker_events:
        spp = e.get("spp")
        if spp is None:
            continue
        edate = e.get("date", "")
        if first_date is None or edate < first_date:
            first_date = edate
            first_spp = spp
        if latest_date is None or edate > latest_date:
            latest_date = edate
            latest_spp = spp

    summaries = list({e.get("summary", "") for e in ticker_events if e.get("summary")})

    current_regime = "unknown"
    if regime_history:
        current_regime = regime_history[0].get("regime", "unknown")

    # Match articles to ticker if provided
    related_titles: list[str] = []
    if articles:
        try:
            from app.enrichers.ticker_aliases import find_related_content
            related_articles, _ = find_related_content(ticker, articles, [])
            related_titles = [a.get("title", "") for a in related_articles[:5] if a.get("title")]
        except Exception:
            pass

    return {
        "ticker": ticker,
        "signal_types": signal_types,
        "shock_types": shock_types,
        "categories": categories,
        "days_appeared": days_appeared,
        "date_range": f"{dates[0]}〜{dates[-1]}" if len(dates) >= 2 else (dates[0] if dates else ""),
        "latest_spp": latest_spp,
        "first_spp": first_spp,
        "summaries": summaries[:3],
        "current_regime": current_regime,
        "related_article_titles": related_titles,
    }


def _build_evidence_elements(ctx: dict[str, Any]) -> list[str]:
    """Build human-readable evidence element list from ticker context."""
    elements: list[str] = []

    # Signal types
    for st in ctx.get("signal_types", []):
        st_ja = _SIGNAL_TYPE_JA.get(st, st)
        elements.append(st_ja)

    # Shock types
    for sh in ctx.get("shock_types", []):
        sh_ja = _SHOCK_TYPE_JA.get(sh, sh)
        elements.append(f"{sh_ja}型")

    # Persistence
    days = ctx.get("days_appeared", 0)
    if days >= 2:
        elements.append(f"{days}日間持続観測")

    # SPP
    latest = ctx.get("latest_spp")
    first = ctx.get("first_spp")
    if latest is not None and first is not None:
        diff = latest - first
        if abs(diff) >= 0.05:
            direction = "上昇" if diff > 0 else "下降"
            elements.append(f"SPP{direction}（{first:.2f}→{latest:.2f}）")
        else:
            elements.append(f"SPP横ばい（{latest:.2f}）")
    elif latest is not None:
        elements.append(f"SPP={latest:.2f}")

    # Regime
    regime = ctx.get("current_regime", "unknown")
    regime_ja = _REGIME_JA.get(regime, regime)
    if regime != "normal" and regime != "unknown":
        elements.append(f"{regime_ja}レジーム下")

    # Article titles (top 2)
    for title in ctx.get("related_article_titles", [])[:2]:
        elements.append(f"関連: {title}")

    return elements


def _generate_cross_hypotheses(
    *,
    event_persistence: list[dict[str, Any]],
    regime_narrative_cross: list[dict[str, Any]],
    week_over_week: dict[str, Any],
    days: int,
    enriched_history: list[dict[str, Any]] | None = None,
    regime_history: list[dict[str, Any]] | None = None,
    articles: list[dict[str, Any]] | None = None,
    reference_date: str | None = None,
) -> list[dict[str, Any]]:
    """Generate context-aware hypotheses from cross-analysis data.

    Integrates per-ticker context (signals, shock type, regime, articles)
    to produce meaningful hypotheses. Limited to top 3 by priority.
    Avoids causal assertions — uses observational language only.
    Each hypothesis includes evidence_elements and data_period.
    """
    candidates: list[dict[str, Any]] = []
    enriched_history = enriched_history or []
    regime_history = regime_history or []

    # Compute data_period
    dates = sorted({e.get("date", "") for e in enriched_history if e.get("date")})
    if dates:
        data_period = f"{dates[0]}〜{dates[-1]} ({len(dates)}日間)"
    elif reference_date:
        data_period = f"〜{reference_date} ({days}日間)"
    else:
        data_period = f"過去{days}日間"

    confidence_note = "短期データに基づく暫定的仮説" if days < 7 else None
    wow_available = week_over_week.get("available", False) if week_over_week else False
    if not wow_available and not confidence_note:
        confidence_note = "前週データなしのため方向性は未確定"

    non_assertion = "観測データに基づく示唆であり、因果関係を示すものではありません"

    # 1. Context-enriched persistent ticker hypotheses (highest priority)
    for ep in event_persistence:
        if ep["days_appeared"] < 3:
            continue
        ctx = _build_ticker_context(enriched_history, regime_history, ep["ticker"], articles)
        if not ctx:
            continue

        elements = _build_evidence_elements(ctx)

        # Build contextual hypothesis text
        signals_ja = [_SIGNAL_TYPE_JA.get(s, s) for s in ctx.get("signal_types", [])]
        shock_ja = [_SHOCK_TYPE_JA.get(s, s) for s in ctx.get("shock_types", [])]
        cats = ctx.get("categories", [])
        regime_ja = _REGIME_JA.get(ctx.get("current_regime", ""), "")

        parts = []
        if signals_ja:
            parts.append("・".join(signals_ja[:2]))
        if shock_ja:
            parts.append("・".join(shock_ja[:1]))
        parts.append(f"{ep['days_appeared']}日間持続")
        if regime_ja and ctx.get("current_regime") not in ("normal", "unknown"):
            parts.append(f"{regime_ja}環境")

        context_str = " + ".join(parts)
        cat_str = cats[0] if cats else "不明"

        spp_note = ""
        if ep.get("spp_trend") == "上昇":
            spp_note = "、SPP上昇中"
        elif ep.get("spp_trend") == "下降":
            spp_note = "、SPP下降中"

        hyp: dict[str, Any] = {
            "hypothesis": (
                f"{ep['ticker']}（{cat_str}）: {context_str}"
                f" → 構造的な市場関心の変化の可能性{spp_note}"
            ),
            "evidence": f"出現: {ep['days_appeared']}/{ep['total_days']}日, SPP推移: {ep['spp_trend']}",
            "evidence_elements": elements,
            "data_period": data_period,
            "confidence_note": confidence_note or non_assertion,
            "_priority": ep["days_appeared"] * 10 + (ep.get("latest_spp") or 0) * 5,
        }
        candidates.append(hyp)

    # 2. Regime × Narrative co-occurrence
    if regime_narrative_cross:
        transition_findings = [f for f in regime_narrative_cross if "同時期に観測" in f.get("finding", "")]
        if transition_findings:
            elements = [f.get("finding", "") for f in transition_findings[:3]]
            hyp = {
                "hypothesis": (
                    "レジーム変化とナラティブシフトが同時期に発生 — "
                    "偶然か構造的連動かは継続観測が必要"
                ),
                "evidence": f"同時変動検出: {len(transition_findings)}件",
                "evidence_elements": elements,
                "data_period": data_period,
                "confidence_note": confidence_note or non_assertion,
                "_priority": 15,
            }
            candidates.append(hyp)

    # 3. WoW regime transition
    if wow_available:
        rs = week_over_week.get("regime_shift", {})
        if rs.get("changed"):
            prev_r = _REGIME_JA.get(rs["previous_regime"], rs["previous_regime"])
            curr_r = _REGIME_JA.get(rs["current_regime"], rs["current_regime"])
            hyp = {
                "hypothesis": (
                    f"レジームが{prev_r}→{curr_r}に変化 — "
                    f"リスク管理基準の見直しを検討する契機"
                ),
                "evidence": f"前週: {prev_r}, 今週: {curr_r}",
                "evidence_elements": [
                    f"前週レジーム: {prev_r}",
                    f"今週レジーム: {curr_r}",
                ],
                "data_period": data_period,
                "confidence_note": confidence_note or non_assertion,
                "_priority": 20,
            }
            candidates.append(hyp)

    # Sort by priority desc and limit to top 3
    candidates.sort(key=lambda x: x.get("_priority", 0), reverse=True)
    top3 = candidates[:3]

    # Remove internal _priority key
    for hyp in top3:
        hyp.pop("_priority", None)

    return top3


def _detect_early_drift(
    enriched_history: list[dict[str, Any]],
    narrative_trend: list[dict[str, Any]],
    db: Any,
    reference_date: str | None = None,
) -> list[dict[str, Any]]:
    """Detect early drift candidates: events emerging but not yet priced in.

    All four conditions must be met for a candidate:
    1. Narrative category ratio < 20% (not dominant yet)
    2. Category z-score >= 1.5 (statistically above baseline)
    3. SNS→Tier2 propagation pattern (spreading from social to media)
    4. No price_change signal for the ticker (market hasn't reacted)
    """
    if not enriched_history or not narrative_trend:
        return []

    # Latest day's narrative distribution
    latest_day = narrative_trend[-1]
    latest_cats = latest_day.get("categories", {})

    # Compute z-scores using 30-day baselines
    from app.enrichers.narrative_baseline import (
        compute_category_baselines,
        compute_category_zscore,
    )

    baselines = compute_category_baselines(
        db, reference_date=reference_date, windows=[30],
    )

    cat_zscores: dict[str, float | None] = {}
    for cat, pct in latest_cats.items():
        z_info = compute_category_zscore(pct, baselines, window=30, category=cat)
        cat_zscores[cat] = z_info.get("z_score")

    # Find tickers with price_change signal (price already reacted)
    price_reacted_tickers = {
        e.get("ticker") for e in enriched_history
        if e.get("signal_type") == "price_change"
    }

    # Scan for early drift candidates
    candidates: list[dict[str, Any]] = []
    seen_tickers: set[str] = set()
    for e in enriched_history:
        ticker = e.get("ticker", "")
        if ticker in seen_tickers:
            continue

        cat = e.get("narrative_category", "")
        cat_pct = latest_cats.get(cat, 0.0)
        cat_zscore = cat_zscores.get(cat)
        diff_pattern = e.get("diffusion_pattern", "")

        # All 4 conditions must be met
        if (
            cat_pct < 0.20
            and cat_zscore is not None
            and cat_zscore >= 1.5
            and diff_pattern == "sns_to_tier2"
            and ticker not in price_reacted_tickers
        ):
            seen_tickers.add(ticker)
            candidates.append({
                "ticker": ticker,
                "narrative_category": cat,
                "category_pct": round(cat_pct, 3),
                "z_score": round(cat_zscore, 2),
                "diffusion_pattern": "SNS→Tier2",
                "price_unreacted": True,
                "summary": e.get("summary", ""),
                "shock_type": e.get("shock_type", ""),
            })

    return candidates


def _detect_turning_points(
    trend: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect turning points with persistence requirement.

    Scans all adjacent-day pairs for max swing per category.
    A swing is only accepted if the day before or after shows
    a change in the same direction (1-day spike exclusion).
    """
    candidates: list[dict[str, Any]] = []
    all_cats: set[str] = set()
    for day in trend:
        all_cats.update(day["categories"].keys())

    for cat in all_cats:
        # Build per-day series for this category
        series = [(d["date"], d["categories"].get(cat, 0.0)) for d in trend]

        # Find the adjacent pair with the largest absolute delta
        best_idx = -1
        best_delta = 0.0
        for i in range(len(series) - 1):
            delta = series[i + 1][1] - series[i][1]
            if abs(delta) > abs(best_delta):
                best_delta = delta
                best_idx = i

        if abs(best_delta) < 0.15:
            continue

        # Persistence check: day before or day after must move in same direction
        direction_sign = 1 if best_delta > 0 else -1
        persistent = False
        # Check day before the swing start
        if best_idx >= 1:
            prev_delta = series[best_idx][1] - series[best_idx - 1][1]
            if prev_delta * direction_sign > 0:
                persistent = True
        # Check day after the swing end
        if best_idx + 2 < len(series):
            next_delta = series[best_idx + 2][1] - series[best_idx + 1][1]
            if next_delta * direction_sign > 0:
                persistent = True

        if not persistent:
            continue

        direction = "上昇" if best_delta > 0 else "下降"
        from_date = series[best_idx][0]
        to_date = series[best_idx + 1][0]
        from_pct = series[best_idx][1]
        to_pct = series[best_idx + 1][1]
        candidates.append({
            "category": cat,
            "direction": direction,
            "delta": round(best_delta, 3),
            "description": (
                f"「{cat}」が{from_date}→{to_date}で"
                f"{abs(best_delta)*100:.0f}ポイント{direction}"
                f"（{from_pct*100:.0f}% → {to_pct*100:.0f}%）"
            ),
        })

    return candidates


def _compute_narrative_average(
    narrative_trend: list[dict[str, Any]],
) -> dict[str, float]:
    """Compute week-average narrative distribution across all days."""
    if not narrative_trend:
        return {}
    totals: dict[str, float] = {}
    count = len(narrative_trend)
    for day in narrative_trend:
        for cat, pct in day["categories"].items():
            totals[cat] = totals.get(cat, 0.0) + pct
    return {cat: total / count for cat, total in totals.items()}


def _generate_org_hypotheses(
    shock_distribution: dict[str, int],
    turning_points: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Generate organizational impact hypotheses from weekly data."""
    hypotheses: list[dict[str, str]] = []

    total_shocks = sum(shock_distribution.values())
    if total_shocks == 0:
        return hypotheses

    # Hypothesis from dominant shock type
    if shock_distribution:
        top_shock = max(shock_distribution, key=shock_distribution.get)
        top_pct = shock_distribution[top_shock] / total_shocks
        if top_pct > 0.4:
            hypotheses.append({
                "hypothesis": (
                    f"今週の構造変化は「{top_shock}」に集中（{top_pct*100:.0f}%）。"
                    f"この領域の専門知識・人材の重要性が高まっている可能性。"
                ),
                "evidence": f"ショックタイプ分布: {top_shock}が{shock_distribution[top_shock]}件",
            })

    # Hypotheses from turning points
    for tp in turning_points:
        if tp["direction"] == "上昇":
            hypotheses.append({
                "hypothesis": (
                    f"「{tp['category']}」ナラティブの急上昇は、"
                    f"この分野への注目シフトを示唆。"
                    f"関連するリスク管理体制の見直しが必要かもしれません。"
                ),
                "evidence": tp["description"],
            })
        else:
            hypotheses.append({
                "hypothesis": (
                    f"「{tp['category']}」ナラティブの下降は、"
                    f"市場の関心が他分野に移行中であることを示唆。"
                    f"この分野の見落としリスクに注意が必要です。"
                ),
                "evidence": tp["description"],
            })

    return hypotheses


def _generate_bias_corrections(
    shock_distribution: dict[str, int],
    narrative_trend: list[dict[str, Any]],
    enriched_history: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Generate monitoring weight adjustment suggestions for next week.

    Identifies under-represented categories and suggests increasing
    attention, citing shock type distribution and narrative trend as evidence.
    """
    actions: list[dict[str, Any]] = []

    if not narrative_trend:
        return actions

    # Use week-average distribution instead of last-day only
    week_avg = _compute_narrative_average(narrative_trend)
    if not week_avg:
        return actions

    # Detect surge: latest day diverging from week average by >=15pt
    latest = narrative_trend[-1]["categories"] if narrative_trend else {}
    surge_cats: dict[str, float] = {}
    for cat in _ALL_CATEGORIES:
        latest_pct = latest.get(cat, 0.0)
        avg_val = week_avg.get(cat, 0.0)
        if abs(latest_pct - avg_val) >= 0.15:
            surge_cats[cat] = latest_pct

    # Identify over-represented and under-represented categories
    # Use all 8 categories as baseline, not just those present
    avg_pct = 1.0 / len(_ALL_CATEGORIES)

    # Find categories significantly below average
    under_represented = []
    over_represented = []
    for cat in _ALL_CATEGORIES:
        pct = week_avg.get(cat, 0.0)
        if pct < avg_pct * 0.5 and cat != "その他":
            under_represented.append((cat, pct))
        elif pct > avg_pct * 2.0:
            over_represented.append((cat, pct))

    # Check if any under-represented categories had actual events (SIS > 0)
    cat_has_events: dict[str, int] = Counter()
    for e in enriched_history:
        cat = e.get("narrative_category", "その他")
        if (e.get("sis") or 0) > 0:
            cat_has_events[cat] += 1

    # Generate actions for under-represented categories with real activity
    for cat, pct in sorted(under_represented, key=lambda x: x[1]):
        event_count = cat_has_events.get(cat, 0)
        action_dict: dict[str, Any] = {
            "category": cat,
            "current_pct": round(pct, 3),
        }
        if cat in surge_cats:
            action_dict["recent_surge"] = True
            action_dict["latest_pct"] = round(surge_cats[cat], 3)
        if event_count > 0:
            action_dict["action"] = f"「{cat}」の監視比重を引き上げ"
            action_dict["reason"] = (
                f"週平均ナラティブ比率{pct*100:.0f}%と低いが、"
                f"過去7日で{event_count}件のイベントが検出されており、"
                f"見落としリスクがあります。"
            )
            actions.append(action_dict)
        elif cat in ("規制/政策/地政学", "金融/金利/流動性", "エネルギー/資源"):
            # System-critical categories deserve attention even without events
            action_dict["action"] = f"「{cat}」の監視比重を維持・注視"
            action_dict["reason"] = (
                f"週平均ナラティブ比率{pct*100:.0f}%と低く、"
                f"イベント未検出だが、構造的に重要なカテゴリのため"
                f"意図的な監視継続を推奨。"
            )
            actions.append(action_dict)

    # Warn about over-concentration
    for cat, pct in sorted(over_represented, key=lambda x: -x[1]):
        action_dict = {
            "action": f"「{cat}」の過集中に注意",
            "reason": (
                f"週平均ナラティブ比率{pct*100:.0f}%と高く、"
                f"他カテゴリの構造変化を見落とすリスクがあります。"
            ),
            "category": cat,
            "current_pct": round(pct, 3),
        }
        if cat in surge_cats:
            action_dict["recent_surge"] = True
            action_dict["latest_pct"] = round(surge_cats[cat], 3)
        actions.append(action_dict)

    return actions

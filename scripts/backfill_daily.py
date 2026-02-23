#!/usr/bin/env python3
"""Backfill missing daily analyses using existing price data.

Runs detection + enrichment for dates where enriched_events are missing,
using the price_data already stored in the DB. No external API calls needed.

Usage:
    python scripts/backfill_daily.py --start 2026-01-23 --end 2026-02-22
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Ensure app is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config
from app.database import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_existing_dates(db: Database, start: str, end: str) -> set[str]:
    """Get dates that already have enriched events."""
    events = db.get_enriched_events_history(days=60, reference_date=end)
    return {e["date"] for e in events if start <= e["date"] <= end}


def get_missing_weekdays(existing: set[str], start: date, end: date) -> list[str]:
    """Find weekdays in [start, end] that lack enriched events."""
    missing = []
    d = start
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri
            ds = d.strftime("%Y-%m-%d")
            if ds not in existing:
                missing.append(ds)
        d += timedelta(days=1)
    return missing


def get_all_prices(db: Database, start: str, end: str) -> list[dict]:
    """Fetch all price data in range across all tickers."""
    with db._connect() as conn:
        rows = conn.execute(
            """SELECT ticker, timestamp, open, high, low, close, volume
               FROM price_data
               WHERE timestamp >= ? AND timestamp <= ?
               ORDER BY ticker, timestamp""",
            (start, end + "T23:59:59"),
        ).fetchall()
    return [dict(r) for r in rows]


def slice_prices(all_prices: list[dict], ticker: str, up_to: str, lookback: int = 25) -> list[dict]:
    """Get price rows for a ticker up to (inclusive) a date."""
    rows = [
        p for p in all_prices
        if p["ticker"] == ticker and p["timestamp"][:10] <= up_to
    ]
    rows.sort(key=lambda p: p["timestamp"])
    return rows[-lookback:]


# ---------------------------------------------------------------------------
# Detection (self-contained, no DB queries needed)
# ---------------------------------------------------------------------------


def detect_anomalies_for_date(
    prices: list[dict],
    ticker: str,
    z_threshold: float = 2.0,
) -> list[dict]:
    """Detect price and volume anomalies from a price slice."""
    anomalies: list[dict] = []

    # Price anomaly
    closes = [p["close"] for p in prices if p.get("close") is not None]
    if len(closes) >= 3:
        returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] != 0:
                returns.append((closes[i] - closes[i - 1]) / closes[i - 1])
        if len(returns) >= 2:
            latest = returns[-1]
            mean = sum(returns) / len(returns)
            var = sum((r - mean) ** 2 for r in returns) / len(returns)
            std = var ** 0.5
            if std > 0:
                z = (latest - mean) / std
                if abs(z) >= z_threshold:
                    pct = round(latest * 100, 2)
                    sign = "+" if pct >= 0 else ""
                    anomalies.append({
                        "ticker": ticker,
                        "signal_type": "price_change",
                        "score": round(min(abs(z) / 5.0, 1.0), 4),
                        "z_score": round(z, 4),
                        "value": round(latest, 6),
                        "mean": round(mean, 6),
                        "std": round(std, 6),
                        "summary": f"前日比{sign}{pct}%の価格変動",
                        "details": {
                            "latest_close": closes[-1],
                            "prev_close": closes[-2],
                            "return_pct": pct,
                            "window_size": len(returns),
                        },
                    })

    # Volume anomaly
    volumes = [p["volume"] for p in prices if p.get("volume") and p["volume"] > 0]
    if len(volumes) >= 3:
        current = volumes[-1]
        baseline = volumes[:-1]
        mean = sum(baseline) / len(baseline)
        var = sum((v - mean) ** 2 for v in baseline) / len(baseline)
        std = var ** 0.5
        if std > 0:
            z = (current - mean) / std
            if abs(z) >= z_threshold:
                ratio = round(current / mean, 2) if mean > 0 else 0
                anomalies.append({
                    "ticker": ticker,
                    "signal_type": "volume_spike",
                    "score": round(min(abs(z) / 5.0, 1.0), 4),
                    "z_score": round(z, 4),
                    "value": float(current),
                    "mean": round(mean, 2),
                    "std": round(std, 2),
                    "summary": f"出来高が平均の{ratio}倍",
                    "details": {
                        "current_volume": current,
                        "avg_volume": round(mean, 0),
                        "volume_ratio": ratio,
                        "window_size": len(baseline),
                    },
                })

    return anomalies


# ---------------------------------------------------------------------------
# Enrichment (no API calls)
# ---------------------------------------------------------------------------


def enrich_anomalies(
    anomalies: list[dict],
    articles: list[dict],
    posts: list[dict],
    sector_map: dict[str, list[str]],
    db: Database | None = None,
    up_to_date: str | None = None,
) -> list[dict]:
    """Enrich detected anomalies into full structural events."""
    from app.enrichers.shock_classifier import classify_shock_type
    from app.enrichers.impact_scorer import compute_structure_impact_score
    from app.enrichers.narrative_classifier import classify_narrative_category
    from app.enrichers.ai_centricity import compute_ai_centricity
    from app.enrichers.evidence_scorer import compute_evidence_score
    from app.enrichers.media_tier import compute_media_tier_distribution
    from app.enrichers.spp import compute_spp
    from app.enrichers.ticker_aliases import find_related_content
    from app.enrichers.propagation import find_propagation

    # Sector lookup
    ticker_to_sector: dict[str, str] = {}
    for sector, members in sector_map.items():
        for t in members:
            ticker_to_sector[t] = sector

    sector_anomaly_counts: dict[str, int] = {}
    for a in anomalies:
        sec = ticker_to_sector.get(a["ticker"], "Other")
        sector_anomaly_counts[sec] = sector_anomaly_counts.get(sec, 0) + 1

    propagation_list = find_propagation(anomalies, sector_map, db=db)
    ticker_to_propagation: dict[str, list[str]] = {}
    for p in propagation_list:
        ticker_to_propagation[p["source_ticker"]] = p["related_tickers"]

    enriched = []
    for anomaly in anomalies:
        ticker = anomaly["ticker"]
        sector = ticker_to_sector.get(ticker, "Other")

        related_articles, related_posts = find_related_content(ticker, articles, posts)

        shock_type = classify_shock_type(anomaly, related_articles, related_posts)

        sector_count = sector_anomaly_counts.get(sector, 0)
        sis_result = compute_structure_impact_score(
            anomaly, related_articles, related_posts,
            sector_anomaly_count=sector_count,
        )

        narrative_category = classify_narrative_category(
            anomaly, related_articles, related_posts,
            gemini_client=None,
        )

        event = {
            **anomaly,
            "shock_type": shock_type,
            "sis": sis_result["sis"],
            "sector": sector,
            "evidence_titles": [a.get("title", "") for a in related_articles[:3]],
            "propagation_targets": ticker_to_propagation.get(ticker, []),
            "narrative_category": narrative_category,
        }

        event["ai_centricity"] = compute_ai_centricity(event, related_articles, related_posts)

        ev_result = compute_evidence_score(event, related_articles, related_posts)
        event["evidence_score"] = ev_result["evidence_score"]
        event["market_evidence"] = ev_result["market_evidence"]
        event["media_evidence"] = ev_result["media_evidence"]
        event["official_evidence"] = ev_result["official_evidence"]

        tier_result = compute_media_tier_distribution(event, related_articles, related_posts)
        event["tier1_count"] = tier_result["tier1_count"]
        event["tier2_count"] = tier_result["tier2_count"]
        event["sns_count"] = tier_result["sns_count"]
        event["diffusion_pattern"] = tier_result["diffusion_pattern"]

        # SPP (with reference_date for correct historical lookups)
        event["spp"] = compute_spp(event, db=db, reference_date=up_to_date)

        enriched.append(event)

    enriched.sort(key=lambda e: e.get("sis", 0), reverse=True)
    return enriched


# ---------------------------------------------------------------------------
# Persist
# ---------------------------------------------------------------------------


def save_enriched_events(db: Database, target_date: str, events: list[dict]) -> int:
    """Persist enriched events for a date."""
    count = 0
    for e in events:
        try:
            db.insert_enriched_event(target_date, e)
            count += 1
        except Exception:
            logger.debug("Failed to persist event for %s on %s", e.get("ticker"), target_date)
    return count


def save_narrative_snapshot(db: Database, target_date: str, events: list[dict]) -> None:
    """Compute and persist narrative category distribution for a date."""
    from collections import Counter

    if not events:
        return

    cat_counts: Counter = Counter()
    for e in events:
        cat = e.get("narrative_category", "その他")
        cat_counts[cat] += 1

    total = sum(cat_counts.values())
    for cat, count in cat_counts.items():
        pct = count / total if total > 0 else 0.0
        db.insert_narrative_snapshot(target_date, cat, count, round(pct, 4), total)


def save_regime_snapshot(db: Database, target_date: str, cfg) -> None:
    """Detect and persist regime for a date."""
    from app.enrichers.regime_detector import detect_market_regime, get_spp_weights

    try:
        regime_info = detect_market_regime(
            db, reference_date=target_date,
            vol_threshold=cfg.regime.vol_threshold,
            declining_threshold=cfg.regime.declining_threshold,
        )
        regime_name = regime_info.get("regime", "normal")
        config_weights = getattr(cfg.regime, f"weights_{regime_name}", None)
        spp_weights = get_spp_weights(regime_name, config_weights=config_weights)
        regime_info["spp_weights"] = spp_weights
        db.insert_regime_snapshot(target_date, regime_info)
    except Exception:
        logger.debug("Failed to save regime snapshot for %s", target_date)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Backfill missing daily analyses")
    parser.add_argument("--start", default="2026-01-23", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-02-22", help="End date (YYYY-MM-DD)")
    parser.add_argument("--config", default="configs/config.yaml", help="Config file path")
    args = parser.parse_args()

    cfg = load_config(args.config)
    db = Database(cfg.database_path)

    start_dt = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_dt = datetime.strptime(args.end, "%Y-%m-%d").date()

    # Find missing dates
    existing = get_existing_dates(db, args.start, args.end)
    missing = get_missing_weekdays(existing, start_dt, end_dt)

    logger.info("Existing dates: %d, Missing weekdays: %d", len(existing), len(missing))
    if not missing:
        logger.info("No missing dates — nothing to backfill")
        return

    # Load all price data once
    all_prices = get_all_prices(db, args.start, args.end)
    logger.info("Loaded %d price rows", len(all_prices))

    # Load articles/posts for enrichment context
    articles = db.get_articles_by_date_range(days=60, reference_date=args.end)
    with db._connect() as conn:
        rows = conn.execute(
            """SELECT source, url, title, body, score, num_comments, author, created_at
               FROM community_posts ORDER BY score DESC LIMIT 500"""
        ).fetchall()
    posts = [dict(r) for r in rows]
    logger.info("Context: %d articles, %d posts", len(articles), len(posts))

    tickers = cfg.active_tickers
    total_events = 0

    for target_date in sorted(missing):
        anomalies: list[dict] = []

        for ticker in tickers:
            prices = slice_prices(all_prices, ticker, target_date)
            if len(prices) < 3:
                continue
            detected = detect_anomalies_for_date(prices, ticker, z_threshold=cfg.detection.z_threshold)
            anomalies.extend(detected)

        # Enrich
        enriched = enrich_anomalies(anomalies, articles, posts, cfg.active_sector_map, db=db, up_to_date=target_date)

        # Persist
        event_count = save_enriched_events(db, target_date, enriched)
        save_narrative_snapshot(db, target_date, enriched)
        save_regime_snapshot(db, target_date, cfg)

        total_events += event_count
        logger.info(
            "  %s: %d anomalies → %d enriched events saved",
            target_date, len(anomalies), event_count,
        )

    logger.info("Backfill complete: %d dates, %d total events", len(missing), total_events)


if __name__ == "__main__":
    main()

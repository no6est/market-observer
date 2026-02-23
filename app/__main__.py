"""CLI entrypoint: python -m app run_hourly / run_daily."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from app.config import load_config

logger = logging.getLogger(__name__)
console = Console()
cli = typer.Typer(help="Market Observability System")


def _setup_logging(level: str) -> None:
    """Configure logging to stdout with the given level."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("peewee").setLevel(logging.WARNING)


def _run_collectors(config):
    """Run all collectors and return collected data."""
    from app.collectors.price import create_price_collector
    from app.collectors.rss import collect_rss
    from app.collectors.community import collect_reddit, collect_hackernews

    results = {"price_data": [], "articles": [], "posts": []}

    with console.status("[bold green]価格データ収集中..."):
        try:
            collector = create_price_collector()
            results["price_data"] = collector.collect(config.active_tickers, period="1mo")
        except Exception:
            logger.exception("Price collection failed")

    with console.status("[bold green]RSS記事収集中..."):
        try:
            results["articles"] = collect_rss(config.active_rss_feeds)
        except Exception:
            logger.exception("RSS collection failed")

    with console.status("[bold green]Reddit収集中..."):
        try:
            results["posts"].extend(
                collect_reddit(config.reddit.subreddits, config.reddit.limit_per_sub)
            )
        except Exception:
            logger.exception("Reddit collection failed")

    with console.status("[bold green]HackerNews収集中..."):
        try:
            if config.hackernews.enabled:
                results["posts"].extend(
                    collect_hackernews(config.hackernews.min_score, config.hackernews.limit)
                )
        except Exception:
            logger.exception("HackerNews collection failed")

    return results


def _run_detectors(config, db):
    """Run all detectors and return anomalies."""
    from app.detectors.price_anomaly import detect_price_anomalies
    from app.detectors.volume_anomaly import detect_volume_anomalies
    from app.detectors.mention_anomaly import detect_mention_anomalies
    from app.detectors.combined import compute_combined_scores

    anomalies = []

    try:
        anomalies.extend(detect_price_anomalies(db, config.active_tickers, config.detection))
    except Exception:
        logger.exception("Price anomaly detection failed")

    try:
        anomalies.extend(detect_volume_anomalies(db, config.active_tickers, config.detection))
    except Exception:
        logger.exception("Volume anomaly detection failed")

    try:
        anomalies.extend(detect_mention_anomalies(db, config.active_tickers, config.detection))
    except Exception:
        logger.exception("Mention anomaly detection failed")

    # Apply combined scoring
    anomalies = compute_combined_scores(anomalies)

    return anomalies


def _build_facts(anomalies, articles, posts):
    """Build fact entries from anomalies and recent content."""
    facts = []
    for a in anomalies:
        details = a.get("details", {})
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except (json.JSONDecodeError, TypeError):
                details = {}

        signal = a.get("signal_type", "unknown")
        ticker = a["ticker"]

        if signal == "price_change":
            pct = details.get("return_pct", 0)
            facts.append({
                "text": f"{ticker}: 価格変動 {pct:+.1f}% (z-score={a.get('z_score', 0):.1f})",
                "source": None,
            })
        elif signal == "volume_spike":
            ratio = details.get("volume_ratio", 0)
            facts.append({
                "text": f"{ticker}: 出来高 平均の{ratio:.1f}倍 (z-score={a.get('z_score', 0):.1f})",
                "source": None,
            })
        elif signal == "mention_surge":
            mentions = details.get("current_mentions", 0)
            facts.append({
                "text": f"{ticker}: {mentions}件の言及を検出 (z-score={a.get('z_score', 0):.1f})",
                "source": None,
            })

    for article in articles[:5]:
        facts.append({
            "text": article.get("title", ""),
            "source": article.get("url"),
        })

    return facts


def _build_structural_tracking_queries(events, structural_themes):
    """Generate tracking queries focused on structural change signals."""
    queries = []
    today = datetime.now().strftime("%Y-%m-%d")

    seen_tickers = set()
    for e in events:
        ticker = e["ticker"]
        if ticker not in seen_tickers:
            shock = e.get("shock_type", "")
            if "Tech" in shock:
                queries.append(f'"{ticker}" AND (disruption OR technology OR AI) since:{today}')
            elif "Regulation" in shock:
                queries.append(f'"{ticker}" AND (regulation OR policy OR compliance) since:{today}')
            elif "Business" in shock:
                queries.append(f'"{ticker}" AND (acquisition OR restructuring OR pricing) since:{today}')
            else:
                queries.append(f'"{ticker}" AND (news OR analysis) since:{today}')
            seen_tickers.add(ticker)

    # Add sector-focused queries from themes
    seen_sectors = set()
    for theme in structural_themes:
        sector = theme.get("sector", "")
        if sector and sector not in seen_sectors:
            tickers = theme.get("tickers", [])
            shock = theme.get("shock_type", "")
            tickers_query = " OR ".join(tickers[:3])
            if "Tech" in shock:
                queries.append(f'({tickers_query}) AND (disruption OR "AI" OR technology)')
            elif "Regulation" in shock:
                queries.append(f'({tickers_query}) AND (regulation OR policy)')
            elif "Business" in shock:
                queries.append(f'({tickers_query}) AND (acquisition OR restructuring)')
            else:
                queries.append(f'({tickers_query}) AND (sentiment OR outlook)')
            seen_sectors.add(sector)

    return queries


def _build_tracking_queries(anomalies, themes):
    """Generate tracking queries for follow-up monitoring."""
    queries = []
    today = datetime.now().strftime("%Y-%m-%d")

    seen_tickers = set()
    for a in anomalies:
        ticker = a["ticker"]
        if ticker not in seen_tickers:
            queries.append(f'"{ticker}" AND (earnings OR news) since:{today}')
            seen_tickers.add(ticker)

    for t in themes:
        name = t.get("name", "")
        if name:
            queries.append(f'"{name}" AND (market OR analysis)')

    return queries


def _find_related_content(ticker, articles, posts):
    """Find articles and posts mentioning a ticker or its company name."""
    from app.enrichers.ticker_aliases import find_related_content
    return find_related_content(ticker, articles, posts)


def _enrich_events(config, anomalies, articles, posts, gemini_client=None, db=None):
    """Enrich anomalies into structural change events.

    Adds shock_type, SIS, related content, sector, propagation targets,
    narrative_category, and ai_centricity.
    """
    from app.enrichers.shock_classifier import classify_shock_type
    from app.enrichers.impact_scorer import compute_structure_impact_score
    from app.enrichers.propagation import find_propagation
    from app.enrichers.narrative_classifier import classify_narrative_category
    from app.enrichers.ai_centricity import compute_ai_centricity
    from app.enrichers.evidence_scorer import compute_evidence_score
    from app.enrichers.media_tier import compute_media_tier_distribution
    from app.enrichers.spp import compute_spp

    propagation_list = find_propagation(anomalies, config.active_sector_map, db=db)

    # Build reverse lookup: ticker -> sector
    ticker_to_sector = {}
    for sector, members in config.active_sector_map.items():
        for t in members:
            ticker_to_sector[t] = sector

    # Build reverse lookup: ticker -> propagation targets
    ticker_to_propagation = {}
    for p in propagation_list:
        ticker_to_propagation[p["source_ticker"]] = p["related_tickers"]

    # Count anomalies per sector for competitor involvement
    sector_anomaly_counts = {}
    for a in anomalies:
        sector = ticker_to_sector.get(a["ticker"], "Other")
        sector_anomaly_counts[sector] = sector_anomaly_counts.get(sector, 0) + 1

    enriched_events = []
    for anomaly in anomalies:
        ticker = anomaly["ticker"]
        sector = ticker_to_sector.get(ticker, "Other")

        # Find related content
        related_articles, related_posts = _find_related_content(ticker, articles, posts)

        # Evidence titles
        evidence_titles = []
        for a in related_articles[:3]:
            evidence_titles.append(a.get("title", ""))
        for p in related_posts[:3]:
            evidence_titles.append(p.get("title", ""))
        evidence_titles = [t for t in evidence_titles if t]

        # Classify shock type
        shock_type = classify_shock_type(anomaly, related_articles, related_posts)

        # Compute Structure Impact Score (pass pre-filtered content)
        sector_count = sector_anomaly_counts.get(sector, 0)
        sis_result = compute_structure_impact_score(
            anomaly, related_articles, related_posts,
            sector_anomaly_count=sector_count,
        )

        # Classify narrative category
        narrative_category = classify_narrative_category(
            anomaly, related_articles, related_posts,
            gemini_client=gemini_client,
        )

        event = {
            **anomaly,
            "shock_type": shock_type,
            "sis": sis_result["sis"],
            "sis_breakdown": sis_result,
            "sector": sector,
            "evidence_titles": evidence_titles,
            "propagation_targets": ticker_to_propagation.get(ticker, []),
            "narrative_category": narrative_category,
        }

        # Compute AI centricity (needs narrative_category)
        event["ai_centricity"] = compute_ai_centricity(
            event, related_articles, related_posts,
        )

        # Compute evidence score
        ev_result = compute_evidence_score(event, related_articles, related_posts)
        event["evidence_score"] = ev_result["evidence_score"]
        event["market_evidence"] = ev_result["market_evidence"]
        event["media_evidence"] = ev_result["media_evidence"]
        event["official_evidence"] = ev_result["official_evidence"]

        # Compute media tier distribution
        tier_result = compute_media_tier_distribution(event, related_articles, related_posts)
        event["tier1_count"] = tier_result["tier1_count"]
        event["tier2_count"] = tier_result["tier2_count"]
        event["sns_count"] = tier_result["sns_count"]
        event["diffusion_pattern"] = tier_result["diffusion_pattern"]

        enriched_events.append(event)

    # Re-estimate propagation direction now that shock_type is available
    from app.enrichers.propagation import estimate_propagation_direction
    ticker_to_shock = {e["ticker"]: e.get("shock_type", "") for e in enriched_events}
    for p in propagation_list:
        st = ticker_to_shock.get(p["source_ticker"], "")
        if st and db is not None:
            sector_key = None
            for sk, members in config.active_sector_map.items():
                if p["source_ticker"] in members:
                    sector_key = sk
                    break
            if sector_key:
                dir_info = estimate_propagation_direction(db, sector_key, st)
                p["direction"] = dir_info["direction"]
                p["direction_confidence"] = dir_info["confidence"]
                p["direction_sample_count"] = dir_info["sample_count"]

    # Sort by SIS descending
    enriched_events.sort(key=lambda e: e["sis"], reverse=True)
    return enriched_events, propagation_list


def _run_enrichers(config, db, anomalies, articles, posts, gemini_client=None):
    """Run all enrichers and return enrichment data."""
    from app.enrichers.theme_extractor import extract_themes
    from app.enrichers.hypothesis import generate_hypotheses
    from app.enrichers.propagation import find_propagation

    enriched = {
        "themes": [],
        "facts": [],
        "hypotheses": [],
        "propagation": [],
        "tracking_queries": [],
    }

    try:
        enriched["themes"] = extract_themes(db)
    except Exception:
        logger.exception("Theme extraction failed")

    try:
        enriched["hypotheses"] = generate_hypotheses(
            anomalies, articles, posts, gemini_client=gemini_client
        )
    except Exception:
        logger.exception("Hypothesis generation failed")

    try:
        enriched["propagation"] = find_propagation(anomalies, config.active_sector_map, db=db)
    except Exception:
        logger.exception("Propagation analysis failed")

    enriched["facts"] = _build_facts(anomalies, articles, posts)
    enriched["tracking_queries"] = _build_tracking_queries(
        anomalies, enriched["themes"]
    )

    return enriched


@cli.command()
def run_hourly(
    config: str = typer.Option("configs/config.yaml", help="設定ファイルのパス"),
    log_level: str = typer.Option("INFO", help="ログレベル (DEBUG/INFO/WARNING/ERROR)"),
) -> None:
    """時間単位のデータ収集ジョブ。"""
    _setup_logging(log_level)

    try:
        cfg = load_config(config)
        console.print("[bold cyan][hourly] データ収集を開始します...")
        logger.info("Starting hourly collection")

        from app.database import Database
        db = Database(cfg.database_path)

        collected = _run_collectors(cfg)

        price_count = db.insert_price_data(collected["price_data"])
        article_count = db.insert_articles(collected["articles"])
        post_count = db.insert_community_posts(collected["posts"])

        console.print(
            f"[bold green][hourly] 完了: "
            f"価格 {price_count}行, 記事 {article_count}件, 投稿 {post_count}件"
        )

    except Exception:
        logger.exception("Hourly job failed")
        console.print("[bold red][hourly] エラーが発生しました")
        sys.exit(1)


@cli.command()
def run_daily(
    config: str = typer.Option("configs/config.yaml", help="設定ファイルのパス"),
    log_level: str = typer.Option("INFO", help="ログレベル (DEBUG/INFO/WARNING/ERROR)"),
    date: Optional[str] = typer.Option(None, help="レポート日付 (YYYY-MM-DD)。省略時は今日。"),
) -> None:
    """日次パイプライン: 収集 + 検出 + 分析 + レポート生成。"""
    _setup_logging(log_level)

    try:
        cfg = load_config(config)
        console.print("[bold cyan][daily] パイプラインを開始します...")

        from app.database import Database
        from app.llm.gemini import create_gemini_client

        db = Database(cfg.database_path)
        gemini_client = create_gemini_client(cfg.gemini.api_key, cfg.gemini.model)

        # Phase 1: Collection
        console.print("[bold cyan][daily] Phase 1/4: データ収集...")
        collected = _run_collectors(cfg)
        db.insert_price_data(collected["price_data"])
        db.insert_articles(collected["articles"])
        db.insert_community_posts(collected["posts"])

        # Phase 2: Detection (clear previous anomalies for fresh analysis)
        console.print("[bold cyan][daily] Phase 2/4: 異常検出...")
        db.clear_recent_anomalies(hours=cfg.detection.cooldown_hours)
        anomalies = _run_detectors(cfg, db)
        for anomaly in anomalies:
            # Gemini summary enhancement
            if gemini_client and not anomaly.get("summary"):
                summary = gemini_client.summarize_anomaly_ja(anomaly)
                if summary:
                    anomaly["summary"] = summary
            db.insert_anomaly(anomaly)
        console.print(f"[bold yellow]  {len(anomalies)}件の異常を検出")

        # Phase 3: Structural Change Analysis
        console.print("[bold cyan][daily] Phase 3/5: 構造変化分析...")
        articles = db.get_recent_articles(hours=24)
        posts = db.get_recent_posts(hours=24)

        enriched_events, propagation_list = _enrich_events(
            cfg, anomalies, articles, posts, gemini_client=gemini_client, db=db
        )
        for e in enriched_events:
            console.print(
                f"  [yellow]{e['ticker']}[/yellow]: {e['shock_type']} "
                f"(SIS={e['sis']:.3f})"
            )

        # Phase 4: Enrichment (themes, hypotheses, causal chains, questions, narrative)
        console.print("[bold cyan][daily] Phase 4/5: エンリッチメント...")
        from app.enrichers.hypothesis import generate_hypotheses
        from app.enrichers.theme_extractor import extract_themes, abstract_structural_themes
        from app.enrichers.causal_chain import build_causal_chains
        from app.enrichers.structural_questions import generate_structural_questions
        from app.enrichers.narrative_concentration import compute_narrative_concentration
        from app.enrichers.non_ai_highlights import extract_non_ai_highlights
        from app.enrichers.narrative_overheat import detect_narrative_overheat
        from app.enrichers.spp import compute_spp_batch
        from app.enrichers.self_verification import save_prediction_log
        from app.enrichers.narrative_baseline import compute_category_baselines, evaluate_narrative_health
        from app.enrichers.regime_detector import detect_market_regime, get_spp_weights
        from app.enrichers.echo_chamber import detect_echo_chamber, apply_echo_correction

        hypotheses = generate_hypotheses(
            anomalies, articles, posts, gemini_client=gemini_client
        )
        causal_chains = build_causal_chains(enriched_events)
        structural_themes = abstract_structural_themes(enriched_events, db)
        structural_questions = generate_structural_questions(enriched_events)

        # Resolve report date
        _today = date or datetime.now().strftime("%Y-%m-%d")

        # Narrative balance analysis
        narrative_index = compute_narrative_concentration(
            enriched_events, db,
            ai_warning_pct=cfg.narrative.overheat_ai_pct,
            concentration_warning_pct=cfg.narrative.concentration_warning_pct,
            narrative_basis=cfg.narrative.narrative_basis,
            reference_date=_today,
        )

        # GLOBAL mode: compute market-specific narrative concentration
        narrative_index_us = None
        narrative_index_jp = None
        if cfg.market_scope == "GLOBAL":
            from app.utils.market_utils import split_by_market
            us_events, jp_events = split_by_market(enriched_events)
            if us_events:
                narrative_index_us = compute_narrative_concentration(
                    us_events, db,
                    ai_warning_pct=cfg.narrative.overheat_ai_pct,
                    concentration_warning_pct=cfg.narrative.concentration_warning_pct,
                    narrative_basis=cfg.narrative.narrative_basis,
                    reference_date=_today,
                )
            if jp_events:
                narrative_index_jp = compute_narrative_concentration(
                    jp_events, db,
                    ai_warning_pct=cfg.narrative.overheat_ai_pct,
                    concentration_warning_pct=cfg.narrative.concentration_warning_pct,
                    narrative_basis=cfg.narrative.narrative_basis,
                    reference_date=_today,
                )

        non_ai_highlights = extract_non_ai_highlights(
            enriched_events,
            ai_threshold=cfg.narrative.ai_threshold,
            top_n=cfg.narrative.top_n_non_ai,
        )
        overheat_alert = detect_narrative_overheat(
            enriched_events, narrative_index, db,
            ai_pct_threshold=cfg.narrative.overheat_ai_pct,
            streak_days_threshold=cfg.narrative.overheat_streak_days,
            delta_threshold=cfg.narrative.overheat_delta_threshold,
            evidence_threshold=cfg.narrative.overheat_evidence_threshold,
            reference_date=_today,
        )

        # Baseline layer: statistical baselines for narrative categories
        baselines = compute_category_baselines(
            db, reference_date=_today, windows=cfg.baseline.windows
        )
        narrative_health = None
        if narrative_index.get("category_distribution"):
            narrative_health = evaluate_narrative_health(
                narrative_index["category_distribution"],
                baselines,
                window=cfg.baseline.windows[1] if len(cfg.baseline.windows) > 1 else 30,
            )

        # Regime layer: detect market regime and get adaptive SPP weights
        regime_info = detect_market_regime(
            db, reference_date=_today,
            vol_threshold=cfg.regime.vol_threshold,
            declining_threshold=cfg.regime.declining_threshold,
        )
        regime_name = regime_info.get("regime", "normal")
        config_weights = getattr(cfg.regime, f"weights_{regime_name}", None)
        spp_weights = get_spp_weights(regime_name, config_weights=config_weights)
        regime_info["spp_weights"] = spp_weights
        try:
            db.insert_regime_snapshot(_today, regime_info)
        except Exception:
            logger.debug("Failed to save regime snapshot")

        # GLOBAL mode: compute market-specific regime info
        regime_info_us = None
        regime_info_jp = None
        if cfg.market_scope == "GLOBAL":
            try:
                regime_info_us = detect_market_regime(
                    db, reference_date=_today,
                    tickers=list(cfg.tickers),
                    vol_threshold=cfg.regime.vol_threshold,
                    declining_threshold=cfg.regime.declining_threshold,
                )
                regime_info_jp = detect_market_regime(
                    db, reference_date=_today,
                    tickers=list(cfg.jp_tickers),
                    vol_threshold=cfg.regime.vol_threshold,
                    declining_threshold=cfg.regime.declining_threshold,
                )
            except Exception:
                logger.debug("Failed to compute market-specific regime")

        # Echo chamber correction
        echo_info = detect_echo_chamber(
            articles, posts,
            similarity_threshold=cfg.echo_chamber.similarity_threshold,
        )
        for e in enriched_events:
            apply_echo_correction(e, echo_info)

        # Compute SPP for all enriched events (with regime-adaptive weights)
        compute_spp_batch(enriched_events, db=db, weights=spp_weights)

        # Record reaction patterns for propagation direction estimation
        try:
            for e in enriched_events:
                price_detail = e.get("details", {})
                if isinstance(price_detail, str):
                    import json as _json
                    try:
                        price_detail = _json.loads(price_detail)
                    except Exception:
                        price_detail = {}
                ret_pct = price_detail.get("return_pct", 0.0)
                if ret_pct > 0.5:
                    direction = "positive"
                elif ret_pct < -0.5:
                    direction = "negative"
                else:
                    direction = "neutral"
                db.insert_reaction_pattern({
                    "date": _today,
                    "ticker": e.get("ticker", ""),
                    "sector": e.get("sector", ""),
                    "shock_type": e.get("shock_type", ""),
                    "price_direction": direction,
                    "price_change_pct": ret_pct,
                    "duration_days": 1,
                })
        except Exception:
            logger.debug("Failed to record reaction patterns")

        # Persist enriched events for weekly analysis
        for e in enriched_events:
            try:
                db.insert_enriched_event(_today, e)
            except Exception:
                logger.debug("Failed to persist enriched event for %s", e.get("ticker"))

        # Save prediction log for self-verification
        try:
            save_prediction_log(db, _today, narrative_index, overheat_alert, enriched_events[:5])
        except Exception:
            logger.debug("Failed to save prediction log")

        # Archive hypotheses for lifecycle tracking
        try:
            from app.enrichers.narrative_archive import archive_hypotheses
            archived_ids = archive_hypotheses(db, _today, hypotheses)
            if archived_ids:
                logger.info("Archived %d hypotheses", len(archived_ids))
        except Exception:
            logger.debug("Failed to archive hypotheses")

        if narrative_index.get("warning_flags"):
            for w in narrative_index["warning_flags"]:
                console.print(f"  [bold yellow]WARNING: {w}")
        if overheat_alert:
            console.print(f"  [bold red]OVERHEAT: {overheat_alert['message']}")

        # Early drift detection
        early_drift_candidates: list[dict] = []
        try:
            if narrative_health and narrative_index.get("category_distribution"):
                cat_scores = narrative_health.get("category_scores", {})
                price_reacted = {e["ticker"] for e in enriched_events if e.get("signal_type") == "price_change"}
                for e in enriched_events:
                    ticker = e.get("ticker", "")
                    if ticker in {d["ticker"] for d in early_drift_candidates}:
                        continue
                    cat = e.get("narrative_category", "")
                    cat_info = narrative_index["category_distribution"].get(cat, {})
                    cat_pct = cat_info.get("pct", 0.0)
                    cat_z = cat_scores.get(cat, {}).get("z_score")
                    diff_pattern = e.get("diffusion_pattern", "")
                    if (
                        cat_pct < 0.20
                        and cat_z is not None and cat_z >= 1.5
                        and diff_pattern == "sns_to_tier2"
                        and ticker not in price_reacted
                    ):
                        early_drift_candidates.append({
                            "ticker": ticker,
                            "narrative_category": cat,
                            "category_pct": round(cat_pct, 3),
                            "z_score": round(cat_z, 2),
                            "diffusion_pattern": "SNS→Tier2",
                            "price_unreacted": True,
                            "summary": e.get("summary", ""),
                            "shock_type": e.get("shock_type", ""),
                        })
                if early_drift_candidates:
                    console.print(f"  [bold magenta]EARLY DRIFT: {len(early_drift_candidates)}件の初動候補")
        except Exception:
            logger.debug("Failed to detect early drift")

        # Also extract word-level themes for DB persistence
        word_themes = extract_themes(db)
        for theme in word_themes:
            db.upsert_theme(theme)

        # Build tracking queries from events and keywords
        tracking_queries = _build_structural_tracking_queries(
            enriched_events, structural_themes
        )

        # Phase 5: Report generation
        console.print("[bold cyan][daily] Phase 5/5: レポート生成...")
        from app.reporter.daily_report import generate_structural_report

        today = date or datetime.now().strftime("%Y-%m-%d")

        report_events = enriched_events[: cfg.report.top_n_anomalies]

        report_md = generate_structural_report(
            events=report_events,
            structural_themes=structural_themes,
            causal_chains=causal_chains,
            hypotheses=hypotheses,
            propagation=propagation_list,
            structural_questions=structural_questions,
            tracking_queries=tracking_queries,
            date=today,
            narrative_index=narrative_index,
            narrative_index_us=narrative_index_us,
            narrative_index_jp=narrative_index_jp,
            non_ai_highlights=non_ai_highlights,
            overheat_alert=overheat_alert,
            narrative_health=narrative_health,
            regime_info=regime_info,
            regime_info_us=regime_info_us,
            regime_info_jp=regime_info_jp,
            echo_info=echo_info,
            early_drift_candidates=early_drift_candidates,
            market_scope=cfg.market_scope,
        )

        output_dir = Path(cfg.report.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / f"{today}_structural.md"
        report_path.write_text(report_md, encoding="utf-8")

        console.print(f"[bold green][daily] 構造変化レポート保存: {report_path}")

    except Exception:
        logger.exception("Daily pipeline failed")
        console.print("[bold red][daily] エラーが発生しました")
        sys.exit(1)


@cli.command()
def run_weekly(
    config: str = typer.Option("configs/config.yaml", help="設定ファイルのパス"),
    log_level: str = typer.Option("INFO", help="ログレベル (DEBUG/INFO/WARNING/ERROR)"),
    date: Optional[str] = typer.Option(None, help="レポート日付 (YYYY-MM-DD)。省略時は今日。"),
) -> None:
    """週次メタ分析レポート生成。"""
    _setup_logging(log_level)

    try:
        cfg = load_config(config)
        console.print("[bold cyan][weekly] 週次メタ分析を開始します...")

        from app.database import Database
        from app.enrichers.weekly_analysis import compute_weekly_analysis
        from app.enrichers.self_verification import compute_verification_summary
        from app.enrichers.narrative_chart import generate_charts
        from app.reporter.daily_report import generate_weekly_report

        db = Database(cfg.database_path)

        analysis = compute_weekly_analysis(db, days=7, reference_date=date)

        # Evaluate pending hypotheses (30+ days old)
        try:
            from app.enrichers.narrative_archive import evaluate_pending_hypotheses
            today = date or datetime.now().strftime("%Y-%m-%d")
            eval_results = evaluate_pending_hypotheses(db, today)
            if eval_results:
                analysis["hypothesis_evaluations"] = eval_results
                logger.info("Evaluated %d pending hypotheses", len(eval_results))
        except Exception:
            logger.debug("Failed to evaluate pending hypotheses")

        # Self-verification summary
        try:
            verification = compute_verification_summary(db, days=7)
            analysis["verification_summary"] = verification
        except Exception:
            logger.debug("Failed to compute verification summary")

        # Generate charts
        today = date or datetime.now().strftime("%Y-%m-%d")
        output_dir = Path(cfg.report.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            chart_paths = generate_charts(
                narrative_trend=analysis.get("narrative_trend", []),
                propagation_data=analysis.get("propagation_structure", {}),
                output_dir=output_dir,
                date=today,
            )
            analysis["chart_paths"] = chart_paths
        except Exception:
            logger.debug("Failed to generate charts")

        # Persist early drift candidates from recent daily runs
        try:
            from app.enrichers.market_response import track_early_drift_persistent
            drift_candidates = analysis.get("early_drift_candidates", [])
            if drift_candidates:
                drift_count = track_early_drift_persistent(
                    db, drift_candidates, reference_date=today,
                )
                if drift_count:
                    console.print(
                        f"[bold magenta][weekly] Early Drift {drift_count}件を永続化"
                    )
        except Exception:
            logger.debug("Failed to persist early drift candidates")

        report_md = generate_weekly_report(analysis=analysis, date=today, market_scope=cfg.market_scope)

        report_path = output_dir / f"{today}_weekly.md"
        report_path.write_text(report_md, encoding="utf-8")

        console.print(f"[bold green][weekly] 週次レポート保存: {report_path}")

    except Exception:
        logger.exception("Weekly analysis failed")
        console.print("[bold red][weekly] エラーが発生しました")
        sys.exit(1)


@cli.command()
def run_monthly(
    config: str = typer.Option("configs/config.yaml", help="設定ファイルのパス"),
    log_level: str = typer.Option("INFO", help="ログレベル (DEBUG/INFO/WARNING/ERROR)"),
    date: Optional[str] = typer.Option(None, help="レポート日付 (YYYY-MM-DD)。省略時は今日。"),
) -> None:
    """月次ナラティブ分析レポート生成。"""
    _setup_logging(log_level)

    try:
        cfg = load_config(config)
        console.print("[bold cyan][monthly] 月次ナラティブ分析を開始します...")

        from app.database import Database
        from app.enrichers.monthly_analysis import compute_monthly_analysis
        from app.llm.gemini import create_gemini_client
        from app.reporter.daily_report import generate_monthly_report

        db = Database(cfg.database_path)
        gemini_client = create_gemini_client(cfg.gemini.api_key, cfg.gemini.model)

        today = date or datetime.now().strftime("%Y-%m-%d")

        analysis = compute_monthly_analysis(
            db, days=30, reference_date=today, llm_client=gemini_client,
            market_scope=cfg.market_scope,
        )

        report_md = generate_monthly_report(analysis=analysis, date=today, market_scope=cfg.market_scope)

        output_dir = Path(cfg.report.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / f"{today}_monthly.md"
        report_path.write_text(report_md, encoding="utf-8")

        # Generate reaction lag histogram chart
        try:
            from app.enrichers.narrative_chart import generate_reaction_lag_histogram
            lag_data = analysis.get("reaction_lag")
            if lag_data and lag_data.get("histogram_data"):
                chart_path = generate_reaction_lag_histogram(
                    lag_data["histogram_data"],
                    output_dir / f"{today}_reaction_lag.png",
                )
                if chart_path:
                    console.print(f"[bold green][monthly] 反応ラグチャート保存: {chart_path}")
        except Exception:
            logger.debug("Failed to generate reaction lag histogram")

        console.print(f"[bold green][monthly] 月次レポート保存: {report_path}")

    except Exception:
        logger.exception("Monthly analysis failed")
        console.print("[bold red][monthly] エラーが発生しました")
        sys.exit(1)


if __name__ == "__main__":
    cli()

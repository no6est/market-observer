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
            results["price_data"] = collector.collect(config.tickers, period="1mo")
        except Exception:
            logger.exception("Price collection failed")

    with console.status("[bold green]RSS記事収集中..."):
        try:
            results["articles"] = collect_rss(config.rss_feeds)
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
        anomalies.extend(detect_price_anomalies(db, config.tickers, config.detection))
    except Exception:
        logger.exception("Price anomaly detection failed")

    try:
        anomalies.extend(detect_volume_anomalies(db, config.tickers, config.detection))
    except Exception:
        logger.exception("Volume anomaly detection failed")

    try:
        anomalies.extend(detect_mention_anomalies(db, config.tickers, config.detection))
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


def _enrich_events(config, anomalies, articles, posts, gemini_client=None):
    """Enrich anomalies into structural change events.

    Adds shock_type, SIS, related content, sector, and propagation targets.
    """
    from app.enrichers.shock_classifier import classify_shock_type
    from app.enrichers.impact_scorer import compute_structure_impact_score
    from app.enrichers.propagation import find_propagation

    propagation_list = find_propagation(anomalies, config.sector_map)

    # Build reverse lookup: ticker -> sector
    ticker_to_sector = {}
    for sector, members in config.sector_map.items():
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

        enriched_events.append({
            **anomaly,
            "shock_type": shock_type,
            "sis": sis_result["sis"],
            "sis_breakdown": sis_result,
            "sector": sector,
            "evidence_titles": evidence_titles,
            "propagation_targets": ticker_to_propagation.get(ticker, []),
        })

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
        enriched["propagation"] = find_propagation(anomalies, config.sector_map)
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
            cfg, anomalies, articles, posts, gemini_client=gemini_client
        )
        for e in enriched_events:
            console.print(
                f"  [yellow]{e['ticker']}[/yellow]: {e['shock_type']} "
                f"(SIS={e['sis']:.3f})"
            )

        # Phase 4: Enrichment (themes, hypotheses, causal chains, questions)
        console.print("[bold cyan][daily] Phase 4/5: エンリッチメント...")
        from app.enrichers.hypothesis import generate_hypotheses
        from app.enrichers.theme_extractor import extract_themes, abstract_structural_themes
        from app.enrichers.causal_chain import build_causal_chains
        from app.enrichers.structural_questions import generate_structural_questions

        hypotheses = generate_hypotheses(
            anomalies, articles, posts, gemini_client=gemini_client
        )
        causal_chains = build_causal_chains(enriched_events)
        structural_themes = abstract_structural_themes(enriched_events, db)
        structural_questions = generate_structural_questions(enriched_events)

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

        today = datetime.now().strftime("%Y-%m-%d")

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


if __name__ == "__main__":
    cli()

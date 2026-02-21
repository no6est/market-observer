"""Daily Markdown report generator."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_daily_report(
    anomalies: list[dict[str, Any]],
    themes: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
    propagation: list[dict[str, Any]],
    tracking_queries: list[str],
    date: str | None = None,
) -> str:
    """Generate a daily Markdown report from processed data.

    Args:
        anomalies: List of anomaly dicts with keys: ticker, signal_type, score, summary.
        themes: List of theme dicts with keys: name, novelty, momentum, related_tickers.
        facts: List of fact dicts with keys: text, source (optional URL).
        hypotheses: List of hypothesis dicts with keys: text, evidence_urls,
            confidence (0-1), counterpoints.
        propagation: List of propagation dicts with keys: source_ticker,
            target_tickers, sector, reasoning.
        tracking_queries: List of search query strings for follow-up monitoring.
        date: Report date string (YYYY-MM-DD). Defaults to today.

    Returns:
        Rendered Markdown string.
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        keep_trailing_newline=True,
    )
    template = env.get_template("daily.md.j2")

    rendered = template.render(
        date=date,
        anomalies=anomalies,
        themes=themes,
        facts=facts,
        hypotheses=hypotheses,
        propagation=propagation,
        tracking_queries=tracking_queries,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    logger.info("Generated daily report for %s (%d chars)", date, len(rendered))
    return rendered


def generate_structural_report(
    events: list[dict[str, Any]],
    structural_themes: list[dict[str, Any]],
    causal_chains: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
    propagation: list[dict[str, Any]],
    structural_questions: list[str],
    tracking_queries: list[str],
    date: str | None = None,
) -> str:
    """Generate a structural change observation report.

    Args:
        events: Enriched events with shock_type, sis, etc.
        structural_themes: Theme-level abstractions.
        causal_chains: Causal chain text graphs.
        hypotheses: Hypothesis dicts.
        propagation: Propagation candidate dicts.
        structural_questions: Forward-looking questions.
        tracking_queries: Search query strings.
        date: Report date string (YYYY-MM-DD).

    Returns:
        Rendered Markdown string.
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        keep_trailing_newline=True,
    )
    template = env.get_template("structural.md.j2")

    rendered = template.render(
        date=date,
        events=events,
        structural_themes=structural_themes,
        causal_chains=causal_chains,
        hypotheses=hypotheses,
        propagation=propagation,
        structural_questions=structural_questions,
        tracking_queries=tracking_queries,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    logger.info("Generated structural report for %s (%d chars)", date, len(rendered))
    return rendered

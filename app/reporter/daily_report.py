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
    narrative_index: dict[str, Any] | None = None,
    non_ai_highlights: list[dict[str, Any]] | None = None,
    overheat_alert: dict[str, Any] | None = None,
    narrative_health: dict[str, Any] | None = None,
    regime_info: dict[str, Any] | None = None,
    echo_info: dict[str, Any] | None = None,
    early_drift_candidates: list[dict[str, Any]] | None = None,
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
        narrative_index: Narrative concentration metrics (optional).
        non_ai_highlights: Non-AI structural change highlights (optional).
        overheat_alert: Narrative overheat alert dict (optional).
        early_drift_candidates: Early drift detection results (optional).

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
        narrative_index=narrative_index,
        non_ai_highlights=non_ai_highlights,
        overheat_alert=overheat_alert,
        narrative_health=narrative_health,
        regime_info=regime_info,
        echo_info=echo_info,
        early_drift_candidates=early_drift_candidates or [],
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    logger.info("Generated structural report for %s (%d chars)", date, len(rendered))
    return rendered


def generate_weekly_report(
    analysis: dict[str, Any],
    date: str | None = None,
) -> str:
    """Generate a weekly meta-analysis report.

    Args:
        analysis: Output from compute_weekly_analysis().
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
    template = env.get_template("weekly.md.j2")

    rendered = template.render(
        date=date,
        analysis=analysis,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    logger.info("Generated weekly report for %s (%d chars)", date, len(rendered))
    return rendered


def generate_monthly_report(
    analysis: dict[str, Any],
    date: str | None = None,
) -> str:
    """Generate a monthly narrative analysis report.

    Args:
        analysis: Output from compute_monthly_analysis().
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
    template = env.get_template("monthly.md.j2")

    # Translation dicts for template
    trajectory_ja = {
        "安定支配": "安定支配",
        "上昇": "上昇",
        "下降": "下降",
        "急騰消滅": "急騰消滅",
        "新興": "新興",
        "不安定": "不安定",
        "不在": "不在",
    }
    eval_ja = {
        "confirmed": "確認",
        "expired": "期限切れ",
        "inconclusive": "判定不能",
    }
    regime_ja = {
        "normal": "平時",
        "high_vol": "高ボラ",
        "tightening": "引き締め",
    }
    pattern_ja = {
        "sns_only": "SNSのみ",
        "sns_to_tier2": "SNS→Tier2",
        "sns_to_tier1": "SNS→Tier1",
        "tier1_direct": "Tier1直接",
        "no_coverage": "カバレッジなし",
    }

    response_type_ja = {
        "即時反応型": "即時反応型",
        "遅延持続型": "遅延持続型",
        "一時的過熱型": "一時的過熱型",
        "無反応型": "無反応型",
        "再編型": "再編型",
    }
    outcome_ja = {
        "仮説強化": "仮説強化",
        "収束": "収束",
        "反転": "反転",
        "再編連鎖": "再編連鎖",
    }

    rendered = template.render(
        date=date,
        analysis=analysis,
        trajectory_ja=trajectory_ja,
        eval_ja=eval_ja,
        regime_ja=regime_ja,
        pattern_ja=pattern_ja,
        response_type_ja=response_type_ja,
        outcome_ja=outcome_ja,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    logger.info("Generated monthly report for %s (%d chars)", date, len(rendered))
    return rendered

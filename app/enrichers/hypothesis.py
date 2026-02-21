"""Template-based hypothesis generation matching anomalies with news context."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.enrichers.ticker_aliases import find_related_content as _find_related_content

logger = logging.getLogger(__name__)

# Japanese templates keyed by signal_type (anomaly description only)
_TEMPLATES: dict[str, str] = {
    "price_change": (
        "{ticker}が{return_pct}%の価格変動（z-score={z_score:.2f}）"
    ),
    "volume_spike": (
        "{ticker}の出来高が平均の{volume_ratio}倍（z-score={z_score:.2f}）"
    ),
    "mention_surge": (
        "{ticker}への言及が{current_mentions}件検出"
        "（通常{daily_avg:.1f}件/日、z-score={z_score:.2f}）"
    ),
}

_DEFAULT_TEMPLATE = (
    "{ticker}に{signal_type}の異常を検出"
    "（スコア={score:.2f}、z-score={z_score:.2f}）"
)


def _compute_confidence(
    anomaly: dict[str, Any],
    matched_articles: list[dict[str, Any]],
    matched_posts: list[dict[str, Any]],
) -> float:
    """Estimate confidence based on anomaly score and corroborating evidence."""
    base = anomaly.get("score", 0.0) * 0.5

    # More corroborating evidence increases confidence
    evidence_count = len(matched_articles) + len(matched_posts)
    evidence_bonus = min(evidence_count * 0.1, 0.4)

    # Multiple source types boost confidence
    source_diversity = 0.0
    if matched_articles and matched_posts:
        source_diversity = 0.1

    return round(min(base + evidence_bonus + source_diversity, 1.0), 2)


def generate_hypotheses(
    anomalies: list[dict[str, Any]],
    articles: list[dict[str, Any]],
    posts: list[dict[str, Any]],
    gemini_client: Any | None = None,
) -> list[dict[str, Any]]:
    """Generate explanatory hypotheses for detected anomalies.

    Matches each anomaly ticker against concurrent articles and posts to
    produce a template-based hypothesis with supporting evidence.
    If gemini_client is provided, enhances hypotheses via LLM.

    Args:
        anomalies: List of anomaly dicts from detectors.
        articles: Recent articles from the database.
        posts: Recent community posts from the database.
        gemini_client: Optional GeminiClient for LLM-enhanced hypothesis text.

    Returns:
        List of hypothesis dicts with: hypothesis, evidence, confidence,
        counterpoints.
    """
    hypotheses: list[dict[str, Any]] = []

    for anomaly in anomalies:
        ticker = anomaly["ticker"]
        signal_type = anomaly.get("signal_type", "unknown")
        details = anomaly.get("details", {})
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except (json.JSONDecodeError, TypeError):
                details = {}

        matched_articles, matched_posts = _find_related_content(ticker, articles, posts)

        # Build evidence list (URLs)
        evidence: list[str] = []
        for a in matched_articles[:5]:
            evidence.append(a.get("url", ""))
        for p in matched_posts[:5]:
            evidence.append(p.get("url", ""))
        evidence = [e for e in evidence if e]

        # Summarize evidence for the template
        evidence_titles = []
        for a in matched_articles[:3]:
            evidence_titles.append(a.get("title", "無題の記事"))
        for p in matched_posts[:3]:
            evidence_titles.append(p.get("title", "無題の投稿"))

        if evidence_titles:
            evidence_summary = "; ".join(evidence_titles)
        else:
            evidence_summary = "関連する直近のニュースは特定されていません"

        # Fill template
        template = _TEMPLATES.get(signal_type, _DEFAULT_TEMPLATE)
        template_vars = {
            "ticker": ticker,
            "signal_type": signal_type,
            "score": anomaly.get("score", 0),
            "z_score": anomaly.get("z_score", 0),
            "return_pct": details.get("return_pct", 0),
            "volume_ratio": details.get("volume_ratio", 0),
            "current_mentions": details.get("current_mentions", 0),
            "daily_avg": details.get("daily_avg_mentions", 0),
        }

        try:
            hypothesis_text = template.format(**template_vars)
        except (KeyError, ValueError):
            hypothesis_text = _DEFAULT_TEMPLATE.format(**template_vars)

        # Attempt LLM enhancement if gemini_client is available
        if gemini_client is not None:
            try:
                enhanced = gemini_client.enhance_hypothesis_ja(
                    hypothesis_text, evidence_titles
                )
                if enhanced:
                    hypothesis_text = enhanced
            except Exception:
                logger.warning("Gemini enhancement failed for %s, using template", ticker)

        confidence = _compute_confidence(anomaly, matched_articles, matched_posts)

        # Generate counterpoints in Japanese
        counterpoints: list[str] = []
        if not evidence:
            counterpoints.append(
                "裏付けとなるニュースが見つかりません。テクニカル/アルゴリズム的な動きの可能性があります。"
            )
        if anomaly.get("score", 0) < 0.5:
            counterpoints.append(
                "異常スコアは中程度であり、通常の市場変動の範囲内の可能性があります。"
            )
        if signal_type == "volume_spike" and not matched_articles:
            counterpoints.append(
                "ニュースを伴わない出来高急増は、ブロック取引やインデックスリバランスの可能性があります。"
            )
        if signal_type == "mention_surge" and anomaly.get("z_score", 0) < 3:
            counterpoints.append(
                "言及数の増加は顕著ですが極端ではなく、定期的な報道の可能性があります。"
            )

        # Build context note about evidence
        if evidence_titles:
            context = "関連する記事・投稿が" + str(len(evidence_titles)) + "件見つかりました"
        else:
            context = "関連する直近のニュースは特定されていません"

        hypotheses.append({
            "hypothesis": hypothesis_text,
            "context": context,
            "evidence": evidence,
            "evidence_titles": evidence_titles,
            "confidence": confidence,
            "counterpoints": counterpoints,
        })

        logger.info(
            "Hypothesis for %s (%s): confidence=%.2f, evidence=%d items",
            ticker, signal_type, confidence, len(evidence),
        )

    return hypotheses

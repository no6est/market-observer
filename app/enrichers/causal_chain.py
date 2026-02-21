"""Causal chain builder for structural change events.

Builds trigger → direct impact → structural implication chains
for each detected event, rendered as text-based directed graphs.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_SIGNAL_DIRECT_IMPACT: dict[str, str] = {
    "price_change": "株価の異常変動",
    "volume_spike": "取引量の急増",
    "mention_surge": "メディア・SNSでの注目急上昇",
}

_SHOCK_STRUCTURAL: dict[str, str] = {
    "Tech shock": "既存プレイヤーの競争優位性が変化する可能性",
    "Business model shock": "収益構造・バリューチェーンの再編が始まる可能性",
    "Regulation shock": "業界全体のコスト構造・参入障壁が変化する可能性",
    "Narrative shift": "資金フロー・投資テーマの転換が起こる可能性",
    "Execution signal": "企業固有の評価見直しが進む可能性",
}


def build_causal_chains(
    enriched_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build cause → effect → structural implication chains.

    Args:
        enriched_events: List of anomaly dicts enriched with shock_type,
            evidence_titles, propagation_targets, etc.

    Returns:
        List of causal chain dicts with trigger, direct_impact,
        structural_implication, and text_graph fields.
    """
    chains: list[dict[str, Any]] = []

    for event in enriched_events:
        ticker = event.get("ticker", "?")
        signal = event.get("signal_type", "unknown")
        shock_type = event.get("shock_type", "Narrative shift")
        summary = event.get("summary", "")
        evidence_titles = event.get("evidence_titles", [])
        propagation_targets = event.get("propagation_targets", [])

        # Trigger: the detected event
        trigger = f"{ticker}: {summary}" if summary else f"{ticker}に異常を検出"

        # Direct impact: what happened as immediate effect
        direct = _SIGNAL_DIRECT_IMPACT.get(signal, "市場の注目")
        if evidence_titles:
            # Add the most relevant evidence as context
            context_title = evidence_titles[0][:80]
            direct += f"（{context_title}）"

        # Structural implication: what this could mean long-term
        structural = _SHOCK_STRUCTURAL.get(shock_type, "構造変化の兆候")
        if propagation_targets:
            prop_str = ", ".join(propagation_targets[:3])
            structural += f"。波及先: {prop_str}"

        # Build text graph representation
        text_graph = (
            f"```\n"
            f"{trigger}\n"
            f"  └→ {direct}\n"
            f"    └→ {structural}\n"
            f"```"
        )

        chains.append({
            "ticker": ticker,
            "shock_type": shock_type,
            "trigger": trigger,
            "direct_impact": direct,
            "structural_implication": structural,
            "text_graph": text_graph,
        })

        logger.debug("Causal chain for %s: %s → %s → %s", ticker, trigger, direct, structural)

    return chains

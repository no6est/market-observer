"""Story Generator: LLM-based or template-fallback daily story summary."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_REGIME_JA = {
    "normal": "平時",
    "high_vol": "高ボラティリティ",
    "tightening": "引き締め",
}


def generate_story_summary(
    enriched_events: list[dict[str, Any]],
    regime_info: dict[str, Any] | None = None,
    gemini_client: Any | None = None,
) -> str:
    """Generate a concise daily story summary.

    Uses LLM if available, otherwise falls back to template.
    """
    if not enriched_events:
        return "本日は構造変化イベントが検出されませんでした。"

    # Gather stats for the summary
    event_count = len(enriched_events)
    top_event = enriched_events[0]
    top_ticker = top_event.get("ticker", "N/A")
    top_shock = top_event.get("shock_type", "N/A")
    max_sis = top_event.get("sis", 0.0)
    regime = _REGIME_JA.get(
        (regime_info or {}).get("regime", "normal"), "平時",
    )

    # Dominant category
    cat_counts: dict[str, int] = {}
    for e in enriched_events:
        cat = e.get("narrative_category", "")
        if cat:
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
    dominant_cat = max(cat_counts, key=cat_counts.get) if cat_counts else "不明"

    # Try LLM generation
    if gemini_client is not None:
        try:
            events_summary = "\n".join(
                f"- {e.get('ticker')}: {e.get('shock_type')} (SIS={e.get('sis', 0):.3f}, "
                f"カテゴリ={e.get('narrative_category', '')})"
                for e in enriched_events[:8]
            )
            prompt = (
                "あなたは市場観測システムのレポーターです。以下のデータから、"
                "本日の市場構造変化を3-6行で要約してください。"
                "客観的な観測ベースの記述で、投資助言は含めないこと。\n\n"
                f"イベント数: {event_count}\n"
                f"市場レジーム: {regime}\n"
                f"イベント一覧:\n{events_summary}\n\n"
                "要約（日本語、3-6行）:"
            )
            result = gemini_client.generate(prompt, max_tokens=500)
            if result and len(result.strip()) > 10:
                return result.strip()
        except Exception:
            logger.debug("LLM story generation failed, using template")

    # Template fallback
    shock_ja = {
        "Tech shock": "テクノロジーショック",
        "Business model shock": "ビジネスモデルショック",
        "Regulation shock": "規制ショック",
        "Narrative shift": "ナラティブシフト",
        "Execution signal": "業績シグナル",
    }
    shock_label = shock_ja.get(top_shock, top_shock)

    return (
        f"本日は{dominant_cat}を中心に{event_count}件の構造変化を観測。"
        f"{top_ticker}が{shock_label}で最大SIS {max_sis:.3f}。"
        f"市場レジームは{regime}。"
    )

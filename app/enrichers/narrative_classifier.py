"""Narrative category classification for detected anomaly events.

Classifies each event into one of eight narrative categories:
- AI/LLM/自動化
- 規制/政策/地政学
- 金融/金利/流動性
- エネルギー/資源
- 半導体/供給網
- ガバナンス/経営
- 社会/労働/教育
- その他
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

NARRATIVE_CATEGORIES: list[str] = [
    "AI/LLM/自動化",
    "規制/政策/地政学",
    "金融/金利/流動性",
    "エネルギー/資源",
    "半導体/供給網",
    "ガバナンス/経営",
    "社会/労働/教育",
    "その他",
]

_NARRATIVE_PATTERNS: dict[str, list[str]] = {
    "AI/LLM/自動化": [
        r"\b(AI|artificial\s+intelligence|machine\s+learning|deep\s+learning|neural\s+net)\b",
        r"\b(GPT|LLM|large\s+language\s+model|chatbot|generative|diffusion|transformer)\b",
        r"\b(automat|robot|autonomous|copilot|co-pilot|AGI|openai|anthropic|gemini)\b",
        r"\b(training\s+data|inference|fine.?tun|prompt|token|embedding|RAG)\b",
    ],
    "規制/政策/地政学": [
        r"\b(regulat|SEC|FTC|antitrust|compliance|legislation|ban|sanction)\b",
        r"\b(tariff|trade\s+war|embargo|geopolit|export\s+control|CHIPS\s+Act)\b",
        r"\b(executive\s+order|DOJ|probe|lawsuit|ruling|court|verdict|penalty)\b",
        r"\b(China|EU|NATO|BRICS|sovereignty|national\s+security)\b",
    ],
    "金融/金利/流動性": [
        r"\b(interest\s+rate|Fed|Federal\s+Reserve|rate\s+cut|rate\s+hike|monetary)\b",
        r"\b(inflation|CPI|PPI|bond|yield|treasury|liquidity|quantitative)\b",
        r"\b(credit|lending|bank|financial\s+crisis|recession|GDP|employment)\b",
        r"\b(IPO|SPAC|buyback|dividend|margin\s+call|short\s+selling)\b",
    ],
    "エネルギー/資源": [
        r"\b(energy|oil|gas|petroleum|OPEC|crude|barrel|pipeline)\b",
        r"\b(renewable|solar|wind|nuclear|hydrogen|battery|EV|lithium)\b",
        r"\b(mining|rare\s+earth|cobalt|copper|commodity|resource)\b",
        r"\b(carbon|emission|climate|green\s+energy|sustainability)\b",
    ],
    "半導体/供給網": [
        r"\b(semiconductor|chip|wafer|foundry|fab|TSMC|Samsung\s+foundry)\b",
        r"\b(supply\s+chain|shortage|inventory|backlog|lead\s+time|logistics)\b",
        r"\b(GPU|CPU|ASIC|FPGA|memory|DRAM|NAND|HBM|packaging)\b",
        r"\b(node|nanometer|nm\s+process|EUV|lithography|yield\s+rate)\b",
    ],
    "ガバナンス/経営": [
        r"\b(CEO|CTO|CFO|COO|board|director|executive|officer)\b",
        r"\b(resign|appoint|hire|fired|step\s+down|succession|leadership)\b",
        r"\b(governance|audit|whistleblow|scandal|fraud|misconduct)\b",
        r"\b(restructur|layoff|reorg|spinoff|merger|acquisition|takeover)\b",
    ],
    "社会/労働/教育": [
        r"\b(labor|worker|employee|union|strike|wage|hiring|workforce)\b",
        r"\b(education|university|training|skill|reskill|bootcamp)\b",
        r"\b(remote\s+work|hybrid|return.to.office|gig\s+economy)\b",
        r"\b(diversity|DEI|inclusion|equity|social\s+impact|ESG)\b",
    ],
}


def classify_narrative_category(
    event: dict[str, Any],
    articles: list[dict[str, Any]],
    posts: list[dict[str, Any]],
    gemini_client: Any | None = None,
) -> str:
    """Classify an event into one of eight narrative categories.

    Uses keyword pattern matching on related articles and posts.
    Falls back to Gemini LLM when top-2 categories are close (within 2 points).
    """
    texts: list[str] = []
    for a in articles:
        texts.append((a.get("title", "") or "") + " " + (a.get("summary", "") or ""))
    for p in posts:
        texts.append((p.get("title", "") or "") + " " + (p.get("body", "") or ""))

    # Include event summary/details in classification
    summary = event.get("summary", "") or ""
    details = event.get("details", {})
    if isinstance(details, dict):
        details_text = " ".join(str(v) for v in details.values())
    else:
        details_text = str(details)
    texts.append(summary + " " + details_text)

    combined_text = " ".join(texts)

    if not combined_text.strip():
        return "その他"

    scores: dict[str, int] = {}
    for category, patterns in _NARRATIVE_PATTERNS.items():
        score = 0
        for pattern in patterns:
            matches = re.findall(pattern, combined_text, re.IGNORECASE)
            score += len(matches)
        scores[category] = score

    if max(scores.values()) == 0:
        return "その他"

    sorted_cats = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top1_cat, top1_score = sorted_cats[0]
    top2_cat, top2_score = sorted_cats[1] if len(sorted_cats) > 1 else ("", 0)

    # Gemini fallback when top-2 are close
    if gemini_client and top2_score > 0 and (top1_score - top2_score) <= 2:
        try:
            prompt = (
                f"以下のテキストを最も適切なカテゴリに分類してください。"
                f"カテゴリ: {', '.join(NARRATIVE_CATEGORIES)}\n"
                f"テキスト: {combined_text[:500]}\n"
                f"カテゴリ名のみを回答してください。"
            )
            response = gemini_client.generate(prompt)
            if response:
                for cat in NARRATIVE_CATEGORIES:
                    if cat in response:
                        logger.debug(
                            "Narrative classification via Gemini: %s -> %s",
                            event.get("ticker"), cat,
                        )
                        return cat
        except Exception:
            logger.debug("Gemini fallback failed, using regex result")

    logger.debug(
        "Narrative classification for %s: %s (scores=%s)",
        event.get("ticker"), top1_cat, scores,
    )
    return top1_cat

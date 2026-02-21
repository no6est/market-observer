"""Shock type classification for detected anomaly events.

Classifies each event into one of five structural shock categories:
- Tech shock: New technology/product disrupting existing players
- Business model shock: Revenue structure or value chain changes
- Regulation shock: Policy/regulatory changes affecting industries
- Narrative shift: Market sentiment or investment theme rotation
- Execution signal: Company-specific performance events
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_SHOCK_PATTERNS: dict[str, list[str]] = {
    "Tech shock": [
        r"\b(launch|release|announc|new\s+product|disrupt|breakthrough|rollout|beta|preview|open.?source)\b",
        r"\b(AI\s+(?:agent|model|tool|platform)|GPT|LLM|code\s+review|automat|robot)\b",
    ],
    "Business model shock": [
        r"\b(pricing|subscription|revenue\s+model|pivot|monetiz|freemium|acqui[rs]|merger|spinoff|restructur|layoff|cost.?cut|partner)\b",
    ],
    "Regulation shock": [
        r"\b(regulat|SEC|FTC|antitrust|compliance|law|legislat|ban|sanction|tariff|tax\s+policy|executive\s+order|DOJ|probe)\b",
    ],
    "Narrative shift": [
        r"\b(bubble|overh[yi]pe|paradigm|shift|sentiment|bearish|bullish|crash|surge|panic|euphoria|rotation|mania|frenzy)\b",
        r"\b(crap|overvalu|undervalu|dump|pump|squeeze|meme|yolo|bet|gambl)\b",
    ],
    "Execution signal": [
        r"\b(earnings\s+(?:call|report|beat|miss)|guidance|outlook|forecast)\b",
        r"\b((?:CEO|CTO|CFO|COO|EVP|chief|president|head)\s+(?:resign|step|leav|depart|hire|named|appoint))\b",
        r"\b((?:resign|step\w*\s+down|leav\w+|depart)\s+(?:after|from|as))\b",
        r"\b(quarterly\s+results|annual\s+report|10-K|10-Q|SEC\s+filing|shakeup|shake.up)\b",
    ],
}

_SIGNAL_TYPE_DEFAULTS: dict[str, str] = {
    "price_change": "Execution signal",
    "volume_spike": "Narrative shift",
    "mention_surge": "Narrative shift",
}


def classify_shock_type(
    anomaly: dict[str, Any],
    related_articles: list[dict[str, Any]],
    related_posts: list[dict[str, Any]],
    gemini_client: Any | None = None,
) -> str:
    """Classify an anomaly event into a shock type category.

    Uses keyword pattern matching on related articles and posts.
    Falls back to signal-type-based defaults if no context is available.
    """
    # Gather all text for classification
    texts: list[str] = []
    for a in related_articles:
        texts.append((a.get("title", "") or "") + " " + (a.get("summary", "") or ""))
    for p in related_posts:
        texts.append((p.get("title", "") or "") + " " + (p.get("body", "") or ""))

    combined_text = " ".join(texts)

    if not combined_text.strip():
        signal = anomaly.get("signal_type", "unknown")
        return _SIGNAL_TYPE_DEFAULTS.get(signal, "Narrative shift")

    # Score each shock type by keyword matches
    scores: dict[str, int] = {}
    for shock_type, patterns in _SHOCK_PATTERNS.items():
        score = 0
        for pattern in patterns:
            matches = re.findall(pattern, combined_text, re.IGNORECASE)
            score += len(matches)
        scores[shock_type] = score

    if max(scores.values()) == 0:
        signal = anomaly.get("signal_type", "unknown")
        return _SIGNAL_TYPE_DEFAULTS.get(signal, "Narrative shift")

    result = max(scores, key=scores.get)
    logger.debug(
        "Shock classification for %s: %s (scores=%s)",
        anomaly.get("ticker"), result, scores,
    )
    return result


def classify_shock_type_ja(shock_type: str) -> str:
    """Return Japanese label for a shock type."""
    return {
        "Tech shock": "テクノロジーショック",
        "Business model shock": "ビジネスモデルショック",
        "Regulation shock": "規制ショック",
        "Narrative shift": "ナラティブシフト",
        "Execution signal": "エグゼキューションシグナル",
    }.get(shock_type, shock_type)

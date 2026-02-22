"""AI centricity score calculator.

Computes a 0.0-1.0 score indicating how AI-centric an event is.
Used to detect over-concentration on AI-related narratives.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_AI_KEYWORDS: list[str] = [
    r"\bAI\b",
    r"\bartificial\s+intelligence\b",
    r"\bmachine\s+learning\b",
    r"\bdeep\s+learning\b",
    r"\bGPT\b",
    r"\bLLM\b",
    r"\blarge\s+language\s+model\b",
    r"\bgenerative\b",
    r"\bchatbot\b",
    r"\bcopilot\b",
    r"\bco-pilot\b",
    r"\bneural\s+net\b",
    r"\btransformer\b",
    r"\bdiffusion\b",
    r"\bAGI\b",
    r"\bopenai\b",
    r"\banthropic\b",
    r"\bgemini\b",
    r"\btraining\s+data\b",
    r"\binference\b",
    r"\bfine.?tun\b",
    r"\bprompt\b",
    r"\btoken\b",
    r"\bembedding\b",
    r"\bRAG\b",
    r"\bautonomous\b",
    r"\bautomat\b",
]

# Categories that are strongly AI-related
_AI_CATEGORIES = {"AI/LLM/自動化"}
# Adjacent categories that get partial credit
_ADJACENT_CATEGORIES = {"半導体/供給網"}

_ADJACENT_WEIGHT = 0.3


def compute_ai_centricity(
    event: dict[str, Any],
    articles: list[dict[str, Any]],
    posts: list[dict[str, Any]],
) -> float:
    """Compute an AI centricity score for an event.

    Score components:
    - Keyword density (weight 0.4): ratio of AI keyword matches
    - Category signal (weight 0.3): based on narrative_category
    - Context ratio (weight 0.3): AI mentions / total word count

    Args:
        event: Enriched event dict (may include narrative_category).
        articles: Related articles for this event.
        posts: Related posts for this event.

    Returns:
        Float between 0.0 and 1.0.
    """
    texts: list[str] = []
    for a in articles:
        texts.append((a.get("title", "") or "") + " " + (a.get("summary", "") or ""))
    for p in posts:
        texts.append((p.get("title", "") or "") + " " + (p.get("body", "") or ""))

    summary = event.get("summary", "") or ""
    texts.append(summary)

    combined_text = " ".join(texts)

    # 1. Keyword density (0.4)
    if combined_text.strip():
        total_matches = 0
        for pattern in _AI_KEYWORDS:
            total_matches += len(re.findall(pattern, combined_text, re.IGNORECASE))
        word_count = max(len(combined_text.split()), 1)
        keyword_density = min(total_matches / (word_count * 0.1), 1.0)
    else:
        keyword_density = 0.0

    # 2. Category signal (0.3)
    category = event.get("narrative_category", "その他")
    if category in _AI_CATEGORIES:
        category_signal = 1.0
    elif category in _ADJACENT_CATEGORIES:
        category_signal = _ADJACENT_WEIGHT
    else:
        category_signal = 0.0

    # 3. Context ratio (0.3): AI keyword mentions as ratio of total tokens
    if combined_text.strip():
        words = combined_text.lower().split()
        total_words = max(len(words), 1)
        ai_word_hits = sum(
            1 for w in words
            if re.search(
                r"(ai|llm|gpt|ml|neural|transformer|generative|chatbot|openai|anthropic|agi|automat)",
                w,
            )
        )
        context_ratio = min(ai_word_hits / total_words * 5, 1.0)
    else:
        context_ratio = 0.0

    score = (
        keyword_density * 0.4
        + category_signal * 0.3
        + context_ratio * 0.3
    )
    score = round(max(0.0, min(1.0, score)), 3)

    logger.debug(
        "AI centricity for %s: %.3f (kw=%.2f, cat=%.2f, ctx=%.2f)",
        event.get("ticker"), score, keyword_density, category_signal, context_ratio,
    )
    return score

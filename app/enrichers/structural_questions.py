"""Generate forward-looking structural change questions.

Produces 3 questions per report to challenge assumptions and
encourage deeper analysis of potential structural changes.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_SIGNAL_JA = {
    "price_change": "価格変動",
    "volume_spike": "出来高急増",
    "mention_surge": "言及急増",
}

_SHOCK_JA = {
    "Tech shock": "テクノロジーショック",
    "Business model shock": "ビジネスモデルショック",
    "Regulation shock": "規制ショック",
    "Narrative shift": "ナラティブシフト",
    "Execution signal": "エグゼキューションシグナル",
}

_SECTOR_JA = {
    "AI_Infrastructure": "AI基盤",
    "Cloud_Security": "クラウドセキュリティ",
    "Data_Platform": "データプラットフォーム",
    "Enterprise_AI": "エンタープライズAI",
    "Cloud_Networking": "クラウドネットワーキング",
    "Energy": "エネルギー",
    "Financial": "金融",
    "Healthcare": "ヘルスケア",
    "Defense_Geopolitics": "防衛・地政学",
}


def generate_structural_questions(
    enriched_events: list[dict[str, Any]],
    top_n: int = 3,
) -> list[str]:
    """Generate forward-looking questions about potential structural change.

    Uses the highest-SIS event to generate 3 categories of questions:
    1. Forward impact: What happens in 6 months if this is real?
    2. Beneficiary/victim: Who wins and loses?
    3. Counter-evidence: What would disprove this?

    Args:
        enriched_events: Events enriched with shock_type, sector, etc.
        top_n: Number of questions to generate.

    Returns:
        List of question strings in Japanese.
    """
    if not enriched_events:
        return []

    # Use the highest-SIS event
    top = enriched_events[0]
    ticker = top.get("ticker", "?")
    shock_type = top.get("shock_type", "変化")
    shock_ja = _SHOCK_JA.get(shock_type, shock_type)
    signal = top.get("signal_type", "unknown")
    signal_ja = _SIGNAL_JA.get(signal, "異常シグナル")
    sector = top.get("sector", "")
    sector_ja = _SECTOR_JA.get(sector, sector)
    propagation = top.get("propagation_targets", [])
    prop_str = ", ".join(propagation[:3]) if propagation else "関連企業"

    questions: list[str] = []

    # Q1: Forward impact
    if sector_ja:
        questions.append(
            f"この{shock_ja}が構造的変化である場合、"
            f"6ヶ月後に{sector_ja}セクターはどう変わっているか？"
        )
    else:
        questions.append(
            f"この{shock_ja}が構造的変化である場合、"
            f"6ヶ月後に{ticker}とその競合はどう変わっているか？"
        )

    # Q2: Beneficiary/victim
    if propagation:
        questions.append(
            f"この構造変化の最大の受益者は誰か？"
            f"{prop_str}は恩恵を受けるか、それとも脅威を受けるか？"
        )
    else:
        questions.append(
            f"この{shock_ja}による業界再編が進む場合、"
            f"次の勝者と敗者は？"
        )

    # Q3: Counter-evidence
    questions.append(
        f"{ticker}の{signal_ja}が構造変化ではなく"
        f"一時的なノイズである反証は何か？"
    )

    logger.info("Generated %d structural questions for %s", len(questions), ticker)
    return questions[:top_n]

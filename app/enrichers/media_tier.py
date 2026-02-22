"""Media tier distribution calculator.

Computes media tier distribution for each event, classifying
information propagation patterns across Tier1 (major wire services),
Tier2 (specialized media), and SNS (community) sources.
"""

from __future__ import annotations

import logging
from typing import Any

from app.enrichers.evidence_scorer import _TIER1_DOMAINS, _TIER2_DOMAINS

logger = logging.getLogger(__name__)

# Community source identifiers
_SNS_SOURCES = frozenset({"reddit", "hackernews"})


def _is_tier1(article: dict[str, Any]) -> bool:
    """Check if article is from a Tier1 source."""
    source = (article.get("source") or "").lower()
    url = (article.get("url") or "").lower()
    return any(domain in source or domain in url for domain in _TIER1_DOMAINS)


def _is_tier2(article: dict[str, Any]) -> bool:
    """Check if article is from a Tier2 source."""
    source = (article.get("source") or "").lower()
    url = (article.get("url") or "").lower()
    return any(domain in source or domain in url for domain in _TIER2_DOMAINS)


def compute_media_tier_distribution(
    event: dict[str, Any],
    articles: list[dict[str, Any]],
    posts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute media tier distribution and diffusion pattern for an event.

    Classifies all related sources into Tier1, Tier2, or SNS tiers and
    determines the information propagation pattern.

    Args:
        event: Anomaly/enriched event dict.
        articles: Related articles (already filtered for this ticker).
        posts: Related community posts (already filtered for this ticker).

    Returns:
        Dict with keys:
        - tier1_count: int number of Tier1 source articles
        - tier2_count: int number of Tier2 source articles
        - sns_count: int number of community (SNS) posts
        - total_sources: int total across all tiers
        - diffusion_pattern: str one of "sns_only", "sns_to_tier2",
          "sns_to_tier1", "tier1_direct", "no_coverage"
    """
    tier1_count = 0
    tier2_count = 0
    for a in articles:
        if _is_tier1(a):
            tier1_count += 1
        elif _is_tier2(a):
            tier2_count += 1

    sns_count = len(posts)

    total_sources = tier1_count + tier2_count + sns_count

    # Determine diffusion pattern
    if tier1_count > 0 and sns_count == 0:
        diffusion_pattern = "tier1_direct"
    elif tier1_count > 0 and sns_count > 0:
        diffusion_pattern = "sns_to_tier1"
    elif tier2_count > 0 and sns_count > 0 and tier1_count == 0:
        diffusion_pattern = "sns_to_tier2"
    elif sns_count > 0 and tier1_count == 0 and tier2_count == 0:
        diffusion_pattern = "sns_only"
    else:
        diffusion_pattern = "no_coverage"

    result: dict[str, Any] = {
        "tier1_count": tier1_count,
        "tier2_count": tier2_count,
        "sns_count": sns_count,
        "total_sources": total_sources,
        "diffusion_pattern": diffusion_pattern,
    }

    logger.debug(
        "Media tier for %s: t1=%d, t2=%d, sns=%d, pattern=%s",
        event.get("ticker", "?"), tier1_count, tier2_count,
        sns_count, diffusion_pattern,
    )
    return result


def compute_sns_bias_ratio(tier_dist: dict[str, Any]) -> float:
    """Compute the SNS bias ratio from a tier distribution.

    Returns the proportion of sources that are community/SNS,
    indicating how much the signal relies on social media alone.

    Args:
        tier_dist: Dict returned by compute_media_tier_distribution.

    Returns:
        Float between 0.0 and 1.0 representing sns_count / total_sources.
        Returns 0.0 when there are no sources.
    """
    total = tier_dist.get("total_sources", 0)
    sns = tier_dist.get("sns_count", 0)
    ratio = sns / max(total, 1)
    return round(ratio, 3)

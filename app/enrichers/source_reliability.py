"""Source Reliability Score (SRS): weight events by media tier credibility."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TIER_WEIGHTS = {
    "tier1_direct": 1.0,
    "sns_to_tier1": 0.85,
    "sns_to_tier2": 0.60,
    "sns_only": 0.30,
    "no_coverage": 0.20,
}


def compute_srs(
    event: dict[str, Any],
    tier_weights: dict[str, float] | None = None,
    diversity_max_bonus: float = 0.20,
    diversity_source_cap: int = 5,
    echo_penalty_factor: float = 0.20,
) -> float:
    """Compute Source Reliability Score for an event.

    SRS = clamp(0.0, 1.0, base + diversity_bonus - echo_penalty)

    Args:
        event: Enriched event dict with diffusion_pattern,
               independent_source_count, echo_chamber_ratio.
        tier_weights: Mapping of diffusion_pattern to base weight.
        diversity_max_bonus: Maximum bonus from source diversity.
        diversity_source_cap: Number of independent sources for max bonus.
        echo_penalty_factor: Scaling factor for echo chamber penalty.

    Returns:
        SRS value clamped to [0.0, 1.0].
    """
    weights = tier_weights or _DEFAULT_TIER_WEIGHTS

    pattern = event.get("diffusion_pattern", "no_coverage")
    base = weights.get(pattern, weights.get("no_coverage", 0.20))

    independent_count = event.get("independent_source_count", 0) or 0
    diversity_bonus = min(independent_count / max(diversity_source_cap, 1), diversity_max_bonus)

    echo_ratio = event.get("echo_chamber_ratio", 0.0) or 0.0
    echo_penalty = echo_ratio * echo_penalty_factor

    srs = base + diversity_bonus - echo_penalty
    return max(0.0, min(1.0, srs))


def apply_srs_to_events(
    events: list[dict[str, Any]],
    tier_weights: dict[str, float] | None = None,
    diversity_max_bonus: float = 0.20,
    diversity_source_cap: int = 5,
    echo_penalty_factor: float = 0.20,
) -> None:
    """Apply SRS to each event in-place.

    Adds event["srs"] to each event dict.
    """
    for event in events:
        event["srs"] = compute_srs(
            event,
            tier_weights=tier_weights,
            diversity_max_bonus=diversity_max_bonus,
            diversity_source_cap=diversity_source_cap,
            echo_penalty_factor=echo_penalty_factor,
        )

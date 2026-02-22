"""Narrative Stats Baseline Layer.

Provides statistical baselines (moving average + standard deviation) for each
narrative category over configurable windows (7/30/90 days), enabling z-score
based anomaly detection instead of fixed thresholds.

Usage:
    baselines = compute_category_baselines(db, reference_date="2026-01-22")
    z_info = compute_category_zscore(current_pct=0.7, baseline=baselines)
    health = evaluate_narrative_health(category_distribution, baselines)
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

logger = logging.getLogger(__name__)


def compute_category_baselines(
    db: Any,
    reference_date: str | None = None,
    windows: list[int] | None = None,
) -> dict[str, Any]:
    """Compute statistical baselines per narrative category over multiple windows.

    For each window size, queries ``db.get_narrative_history(days=N)`` and
    computes mean, standard deviation, and sample count of ``event_pct``
    for every category found in the history.

    Args:
        db: Database instance with ``get_narrative_history`` method.
        reference_date: ISO date string (YYYY-MM-DD) to anchor the lookback.
            Defaults to today (UTC) when ``None``.
        windows: List of lookback window sizes in days.
            Defaults to ``[7, 30, 90]``.

    Returns:
        Dict with keys:
        - baselines: ``{window: {category: {mean, std, n}, ...}, ...}``
        - reference_date: the date string used
        - sample_sizes: ``{window: total_data_points, ...}``
    """
    if windows is None:
        windows = [7, 30, 90]

    baselines: dict[int, dict[str, dict[str, Any]]] = {}
    sample_sizes: dict[int, int] = {}

    for window in windows:
        try:
            history = db.get_narrative_history(
                days=window, reference_date=reference_date,
            )
        except Exception:
            logger.warning(
                "Failed to retrieve narrative history for %d-day window",
                window,
            )
            baselines[window] = {}
            sample_sizes[window] = 0
            continue

        if not history:
            baselines[window] = {}
            sample_sizes[window] = 0
            continue

        # Group event_pct values by category
        cat_pcts: dict[str, list[float]] = {}
        for row in history:
            cat = row["category"]
            pct = row["event_pct"]
            if cat not in cat_pcts:
                cat_pcts[cat] = []
            cat_pcts[cat].append(pct)

        window_baselines: dict[str, dict[str, Any]] = {}
        total_points = 0
        for cat, pcts in cat_pcts.items():
            n = len(pcts)
            total_points += n
            mean_val = statistics.mean(pcts)
            if n >= 3:
                std_val = statistics.stdev(pcts)
            else:
                std_val = statistics.pstdev(pcts)
            window_baselines[cat] = {
                "mean": round(mean_val, 4),
                "std": round(std_val, 4),
                "n": n,
            }

        baselines[window] = window_baselines
        sample_sizes[window] = total_points

    used_ref = reference_date or ""
    if not used_ref:
        from datetime import datetime

        used_ref = datetime.utcnow().strftime("%Y-%m-%d")

    result = {
        "baselines": baselines,
        "reference_date": used_ref,
        "sample_sizes": sample_sizes,
    }

    logger.info(
        "Category baselines computed: windows=%s, ref=%s, categories=%s",
        windows,
        used_ref,
        {w: len(b) for w, b in baselines.items()},
    )
    return result


def compute_category_zscore(
    current_pct: float,
    baseline: dict[str, Any],
    window: int = 30,
    category: str | None = None,
) -> dict[str, Any]:
    """Compute z-score for a category's current percentage against its baseline.

    Args:
        current_pct: The category's current proportion (0.0-1.0).
        baseline: The full baselines dict returned by
            :func:`compute_category_baselines`.
        window: Which window to use for the baseline lookup (default 30).
        category: Category name to look up in the window baselines.
            When ``None``, the caller must have already extracted
            ``mean`` / ``std`` / ``n`` into the baseline dict directly.

    Returns:
        Dict with keys:
        - z_score: float (or ``None`` if insufficient data)
        - mean: float
        - std: float
        - normal_range: ``(low, high)`` clamped to 0-1
        - is_anomalous: bool (``|z| > 2.0``)
        - window: int
        - status: ``"insufficient_data"`` when z-score cannot be computed
    """
    # Resolve the per-category stats
    if category is not None:
        window_data = baseline.get("baselines", {}).get(window, {})
        cat_stats = window_data.get(category)
    else:
        # Allow passing pre-extracted stats directly
        cat_stats = baseline

    if cat_stats is None:
        return {
            "z_score": None,
            "mean": None,
            "std": None,
            "normal_range": (0.0, 1.0),
            "is_anomalous": False,
            "window": window,
            "status": "insufficient_data",
        }

    mean_val: float = cat_stats["mean"]
    std_val: float = cat_stats["std"]
    n: int = cat_stats["n"]

    # Guard: insufficient data or zero variance
    if n < 3 or std_val == 0:
        low = max(0.0, round(mean_val - 2 * std_val, 4)) if std_val > 0 else 0.0
        high = min(1.0, round(mean_val + 2 * std_val, 4)) if std_val > 0 else 1.0
        return {
            "z_score": None,
            "mean": mean_val,
            "std": std_val,
            "normal_range": (low, high),
            "is_anomalous": False,
            "window": window,
            "status": "insufficient_data",
        }

    z_score = round((current_pct - mean_val) / std_val, 4)
    low = max(0.0, round(mean_val - 2 * std_val, 4))
    high = min(1.0, round(mean_val + 2 * std_val, 4))

    return {
        "z_score": z_score,
        "mean": mean_val,
        "std": std_val,
        "normal_range": (low, high),
        "is_anomalous": abs(z_score) > 2.0,
        "window": window,
        "status": "normal" if abs(z_score) < 1.0 else (
            "elevated" if abs(z_score) < 2.0 else "anomalous"
        ),
    }


def evaluate_narrative_health(
    category_distribution: dict[str, dict[str, Any]],
    baselines: dict[str, Any],
    window: int = 30,
) -> dict[str, Any]:
    """Evaluate narrative health by computing per-category z-scores.

    Compares today's category distribution (from
    :func:`~app.enrichers.narrative_concentration.compute_narrative_concentration`)
    against historical baselines and flags statistically anomalous categories.

    Args:
        category_distribution: Dict of ``{category: {"count": int, "pct": float}}``.
        baselines: Full baselines dict from :func:`compute_category_baselines`.
        window: Which lookback window to evaluate against (default 30).

    Returns:
        Dict with keys:
        - window: int
        - sample_size: total data points in that window
        - category_scores: per-category z-score details + status
        - anomalous_categories: list of categories with ``|z| >= 2``
        - health_summary: human-readable Japanese summary
    """
    sample_size = baselines.get("sample_sizes", {}).get(window, 0)
    window_data = baselines.get("baselines", {}).get(window, {})

    category_scores: dict[str, dict[str, Any]] = {}
    anomalous_categories: list[str] = []

    for cat, info in category_distribution.items():
        current_pct = info.get("pct", 0.0)

        z_result = compute_category_zscore(
            current_pct=current_pct,
            baseline=baselines,
            window=window,
            category=cat,
        )

        # Determine display status
        status = z_result["status"]

        category_scores[cat] = {
            "current_pct": current_pct,
            "z_score": z_result["z_score"],
            "mean": z_result["mean"],
            "std": z_result["std"],
            "normal_range": list(z_result["normal_range"]),
            "status": status,
        }

        if status == "anomalous":
            anomalous_categories.append(cat)

    # Also check categories present in the baseline but absent today
    for cat in window_data:
        if cat not in category_distribution:
            z_result = compute_category_zscore(
                current_pct=0.0,
                baseline=baselines,
                window=window,
                category=cat,
            )
            status = z_result["status"]
            category_scores[cat] = {
                "current_pct": 0.0,
                "z_score": z_result["z_score"],
                "mean": z_result["mean"],
                "std": z_result["std"],
                "normal_range": list(z_result["normal_range"]),
                "status": status,
            }
            if status == "anomalous":
                anomalous_categories.append(cat)

    # Build summary
    n_anomalous = len(anomalous_categories)
    if n_anomalous == 0:
        health_summary = "全カテゴリが統計的正常範囲"
    else:
        health_summary = f"{n_anomalous}カテゴリが統計的異常範囲"

    result = {
        "window": window,
        "sample_size": sample_size,
        "category_scores": category_scores,
        "anomalous_categories": anomalous_categories,
        "health_summary": health_summary,
    }

    logger.info(
        "Narrative health (window=%d): %d categories evaluated, %d anomalous - %s",
        window,
        len(category_scores),
        n_anomalous,
        health_summary,
    )
    return result

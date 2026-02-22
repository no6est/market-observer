"""Generate matplotlib charts for the weekly report.

Produces narrative trend line charts and media diffusion bar charts
as PNG files for embedding in weekly Markdown/HTML reports.
"""

import logging
from pathlib import Path
from typing import Any, Optional

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend — must be set before pyplot import

import matplotlib.pyplot as plt  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Label / colour mappings
# ---------------------------------------------------------------------------

_DIFFUSION_LABELS: dict[str, str] = {
    "sns_only": "SNS Only",
    "sns_to_tier2": "SNS -> Tier2",
    "sns_to_tier1": "SNS -> Tier1",
    "tier1_direct": "Tier1 Direct",
}

# Japanese category -> English label for chart legends
_CATEGORY_EN: dict[str, str] = {
    "AI/LLM/自動化": "AI/LLM/Automation",
    "エネルギー/資源": "Energy/Resources",
    "金融/金利/流動性": "Finance/Rates/Liquidity",
    "規制/政策/地政学": "Regulation/Policy/Geopolitics",
    "サプライチェーン": "Supply Chain",
    "半導体/ハードウェア": "Semiconductor/Hardware",
    "その他": "Other",
}

_DIFFUSION_COLORS: dict[str, str] = {
    "sns_only": "orange",
    "sns_to_tier2": "gold",
    "sns_to_tier1": "dodgerblue",
    "tier1_direct": "green",
}

# Muted palette for non-AI categories
_MUTED_COLORS: list[str] = [
    "#6baed6",  # steel blue
    "#74c476",  # muted green
    "#fd8d3c",  # muted orange
    "#9e9ac8",  # muted purple
    "#f768a1",  # muted pink
    "#bdbdbd",  # grey
    "#d6616b",  # dusty rose
    "#cedb9c",  # sage
    "#e7969c",  # salmon
    "#b5cf6b",  # lime
]

_AI_CATEGORY = "AI/LLM/自動化"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_narrative_trend_chart(
    narrative_trend: list[dict[str, Any]],
    output_path: str | Path,
) -> Optional[str]:
    """Generate a line chart showing narrative category trends over 7 days.

    Parameters
    ----------
    narrative_trend:
        List of dicts, each containing ``"date"`` (str, e.g. ``"2026-02-16"``)
        and ``"categories"`` (dict mapping category name to float 0-1).
    output_path:
        Filesystem path where the PNG will be written.

    Returns
    -------
    str or None
        The *output_path* as a string on success, ``None`` when *narrative_trend*
        is empty or otherwise unusable.
    """
    if not narrative_trend:
        logger.warning("narrative_trend is empty — skipping trend chart generation")
        return None

    output_path = Path(output_path)

    # Font settings — Japanese-safe fallback
    matplotlib.rcParams['font.family'] = ['DejaVu Sans', 'sans-serif']

    # Collect all category names (preserve insertion order)
    all_categories: list[str] = []
    for entry in narrative_trend:
        for cat in entry.get("categories", {}):
            if cat not in all_categories:
                all_categories.append(cat)

    if not all_categories:
        logger.warning("No categories found in narrative_trend data — skipping chart")
        return None

    dates = [entry["date"][5:].replace("-", "/") for entry in narrative_trend]  # MM/DD

    # Build series per category
    series: dict[str, list[float]] = {cat: [] for cat in all_categories}
    for entry in narrative_trend:
        cats = entry.get("categories", {})
        for cat in all_categories:
            series[cat].append(cats.get(cat, 0.0) * 100)  # convert to percentage

    # --- Plot ---
    fig, ax = plt.subplots(figsize=(12, 6))

    muted_idx = 0
    for cat in all_categories:
        label_en = _CATEGORY_EN.get(cat, cat)
        if cat == _AI_CATEGORY:
            ax.plot(dates, series[cat], label=label_en, color="red", linewidth=2.5)
        else:
            color = _MUTED_COLORS[muted_idx % len(_MUTED_COLORS)]
            muted_idx += 1
            ax.plot(dates, series[cat], label=label_en, color=color, linewidth=1.2)

    ax.set_title("Narrative Category Trend (7 days)")
    ax.set_ylabel("%")
    ax.set_ylim(0, 100)
    ax.yaxis.grid(True, linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)

    # Legend outside the plot on the right
    ax.legend(
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        borderaxespad=0,
        fontsize="small",
    )

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close("all")

    logger.info("Saved narrative trend chart to %s", output_path)
    return str(output_path)


def generate_media_diffusion_chart(
    propagation_data: dict[str, int],
    output_path: str | Path,
) -> Optional[str]:
    """Generate a horizontal bar chart showing media diffusion patterns.

    Parameters
    ----------
    propagation_data:
        Mapping of diffusion pattern keys (``"sns_only"``, ``"sns_to_tier2"``,
        ``"sns_to_tier1"``, ``"tier1_direct"``) to integer counts.
    output_path:
        Filesystem path where the PNG will be written.

    Returns
    -------
    str or None
        The *output_path* as a string on success, ``None`` when
        *propagation_data* is empty.
    """
    if not propagation_data:
        logger.warning("propagation_data is empty — skipping diffusion chart generation")
        return None

    output_path = Path(output_path)

    # Font settings — Japanese-safe fallback
    matplotlib.rcParams['font.family'] = ['DejaVu Sans', 'sans-serif']

    # Ordered keys for consistent display
    ordered_keys = ["sns_only", "sns_to_tier2", "sns_to_tier1", "tier1_direct"]
    keys = [k for k in ordered_keys if k in propagation_data]

    if not keys:
        logger.warning("No recognised diffusion keys in propagation_data — skipping chart")
        return None

    labels = [_DIFFUSION_LABELS.get(k, k) for k in keys]
    values = [propagation_data[k] for k in keys]
    colors = [_DIFFUSION_COLORS.get(k, "steelblue") for k in keys]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.barh(labels, values, color=colors)
    ax.set_xlabel("Count")
    ax.set_title("Narrative Diffusion Structure")

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close("all")

    logger.info("Saved media diffusion chart to %s", output_path)
    return str(output_path)


def generate_reaction_lag_histogram(
    histogram_data: list[tuple[str, int]],
    output_path: str | Path,
) -> Optional[str]:
    """Generate a horizontal bar chart showing reaction lag distribution.

    Parameters
    ----------
    histogram_data:
        List of ``(bucket_label, count)`` tuples.
        Expected buckets: 0日, 1日, ..., 5日, 6-10日, 11+日, 未反応.
    output_path:
        Filesystem path where the PNG will be written.

    Returns
    -------
    str or None
        The *output_path* as a string on success, ``None`` when data is empty.
    """
    if not histogram_data or all(count == 0 for _, count in histogram_data):
        logger.warning("histogram_data is empty — skipping reaction lag chart")
        return None

    output_path = Path(output_path)

    matplotlib.rcParams['font.family'] = ['DejaVu Sans', 'sans-serif']

    # Translate bucket labels to English
    _BUCKET_EN: dict[str, str] = {
        "0日": "0d", "1日": "1d", "2日": "2d", "3日": "3d",
        "4日": "4d", "5日": "5d", "6-10日": "6-10d", "11+日": "11+d",
        "未反応": "No Reaction",
    }
    raw_labels = [label for label, _ in histogram_data]
    labels = [_BUCKET_EN.get(l, l) for l in raw_labels]
    values = [count for _, count in histogram_data]

    # Color coding: immediate=green, delayed=orange, no reaction=grey
    colors: list[str] = []
    for label in raw_labels:
        if label in ("0日", "1日"):
            colors.append("#74c476")   # green — immediate
        elif label in ("2日", "3日", "4日", "5日"):
            colors.append("#fd8d3c")   # orange — moderate
        elif label in ("6-10日", "11+日"):
            colors.append("#d6616b")   # red — delayed
        else:
            colors.append("#bdbdbd")   # grey — no reaction

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(labels, values, color=colors)
    ax.set_xlabel("Count")
    ax.set_title("Narrative -> Price Reaction Lag Distribution")
    ax.invert_yaxis()

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close("all")

    logger.info("Saved reaction lag histogram to %s", output_path)
    return str(output_path)


def generate_charts(
    narrative_trend: list[dict[str, Any]],
    propagation_data: dict[str, int],
    output_dir: str | Path,
    date: str | None = None,
) -> dict[str, Optional[str]]:
    """Convenience wrapper that generates both charts into *output_dir*.

    Parameters
    ----------
    narrative_trend:
        Data for :func:`generate_narrative_trend_chart`.
    propagation_data:
        Data for :func:`generate_media_diffusion_chart`.
    output_dir:
        Directory where the PNG files will be created.
    date:
        Report date string (YYYY-MM-DD) used as filename prefix.
        If *None*, files are named without a date prefix.

    Returns
    -------
    dict
        ``{"trend_chart": <path|None>, "diffusion_chart": <path|None>}``
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    prefix = f"{date}_" if date else ""

    trend_path = generate_narrative_trend_chart(
        narrative_trend,
        output_dir / f"{prefix}narrative_trend.png",
    )
    diffusion_path = generate_media_diffusion_chart(
        propagation_data,
        output_dir / f"{prefix}media_diffusion.png",
    )

    return {
        "trend_chart": trend_path,
        "diffusion_chart": diffusion_path,
    }

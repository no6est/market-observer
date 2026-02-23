"""Market identification utilities for JP/US ticker handling."""

from __future__ import annotations

import re
from typing import Any

_JP_SUFFIX = re.compile(r"\.\d*T$")


def is_jp_ticker(ticker: str) -> bool:
    """Return True if *ticker* looks like a Tokyo Stock Exchange symbol (e.g. ``7203.T``)."""
    return bool(_JP_SUFFIX.search(ticker))


def get_market(ticker: str) -> str:
    """Return ``"JP"`` for TSE tickers, ``"US"`` otherwise."""
    return "JP" if is_jp_ticker(ticker) else "US"


_JP_TICKER_NAMES: dict[str, str] = {
    "7203.T": "トヨタ",
    "6758.T": "ソニー",
    "9984.T": "ソフトバンクG",
    "8035.T": "東京エレクトロン",
    "9432.T": "NTT",
    "6098.T": "リクルート",
    "6861.T": "キーエンス",
    "6501.T": "日立",
    "8306.T": "三菱UFJ",
    "2914.T": "JT",
}


def ticker_display_name(ticker: str) -> str:
    """Return display name for a ticker, e.g. ``7203.T（トヨタ）``.

    US tickers are returned as-is.
    """
    name = _JP_TICKER_NAMES.get(ticker)
    if name:
        return f"{ticker}（{name}）"
    return ticker


def split_by_market(
    items: list[dict[str, Any]],
    ticker_key: str = "ticker",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a list of dicts into (US items, JP items) based on ticker.

    Args:
        items: Sequence of dicts each containing a ticker field.
        ticker_key: Key name for the ticker value.

    Returns:
        Tuple of (us_items, jp_items).
    """
    us: list[dict[str, Any]] = []
    jp: list[dict[str, Any]] = []
    for item in items:
        ticker = item.get(ticker_key, "")
        if is_jp_ticker(ticker):
            jp.append(item)
        else:
            us.append(item)
    return us, jp

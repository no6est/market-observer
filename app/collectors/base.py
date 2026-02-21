"""Abstract base class for price collectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PriceCollector(ABC):
    """Interface for collecting OHLCV price data."""

    @abstractmethod
    def collect(self, tickers: list[str], period: str = "5d") -> list[dict[str, Any]]:
        """Collect OHLCV price data for the given tickers.

        Args:
            tickers: List of stock ticker symbols (e.g. ["NVDA", "MSFT"]).
            period: Period string for historical data (e.g. "1d", "5d", "1mo").

        Returns:
            List of dicts with keys: ticker, timestamp, open, high, low,
            close, volume.
        """
        ...

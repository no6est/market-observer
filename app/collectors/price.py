"""Stock price collector using yfinance."""

from __future__ import annotations

import logging
from typing import Any

import yfinance as yf

from app.collectors.base import PriceCollector

logger = logging.getLogger(__name__)


class YFinancePriceCollector(PriceCollector):
    """Collects OHLCV data via the yfinance library."""

    def collect(self, tickers: list[str], period: str = "5d") -> list[dict[str, Any]]:
        """Collect OHLCV price data for the given tickers.

        Args:
            tickers: List of stock ticker symbols (e.g. ["NVDA", "MSFT"]).
            period: yfinance period string (e.g. "1d", "5d", "1mo", "3mo").

        Returns:
            List of dicts with keys: ticker, timestamp, open, high, low,
            close, volume.  NaN values are converted to None.
        """
        rows: list[dict[str, Any]] = []

        for ticker in tickers:
            try:
                logger.info("Fetching price data for %s (period=%s)", ticker, period)
                tk = yf.Ticker(ticker)
                df = tk.history(period=period)

                if df.empty:
                    logger.warning("No price data returned for %s", ticker)
                    continue

                for ts, row in df.iterrows():
                    # NaN-safe: NaN != NaN, so x == x is False for NaN
                    rows.append({
                        "ticker": ticker,
                        "timestamp": ts.isoformat(),
                        "open": round(float(row["Open"]), 4) if row["Open"] == row["Open"] else None,
                        "high": round(float(row["High"]), 4) if row["High"] == row["High"] else None,
                        "low": round(float(row["Low"]), 4) if row["Low"] == row["Low"] else None,
                        "close": round(float(row["Close"]), 4) if row["Close"] == row["Close"] else None,
                        "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else None,
                    })

                logger.info("Collected %d price rows for %s", len(df), ticker)

            except Exception:
                logger.exception("Failed to collect price data for %s", ticker)

        logger.info("Total price rows collected: %d", len(rows))
        return rows


def create_price_collector() -> PriceCollector:
    """Factory that returns the default price collector implementation."""
    return YFinancePriceCollector()

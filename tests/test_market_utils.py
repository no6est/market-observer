"""Tests for market identification utilities."""

from __future__ import annotations

import pytest

from app.utils.market_utils import get_market, is_jp_ticker, split_by_market, ticker_display_name


class TestIsJpTicker:
    def test_standard_jp_ticker(self) -> None:
        assert is_jp_ticker("7203.T") is True

    def test_four_digit_jp_ticker(self) -> None:
        assert is_jp_ticker("9984.T") is True

    def test_us_ticker(self) -> None:
        assert is_jp_ticker("NVDA") is False

    def test_us_ticker_with_dot(self) -> None:
        assert is_jp_ticker("BRK.B") is False

    def test_empty_string(self) -> None:
        assert is_jp_ticker("") is False


class TestGetMarket:
    def test_us(self) -> None:
        assert get_market("NVDA") == "US"

    def test_jp(self) -> None:
        assert get_market("7203.T") == "JP"


class TestSplitByMarket:
    def test_split(self) -> None:
        items = [
            {"ticker": "NVDA", "score": 1},
            {"ticker": "7203.T", "score": 2},
            {"ticker": "MSFT", "score": 3},
            {"ticker": "6758.T", "score": 4},
        ]
        us, jp = split_by_market(items)
        assert [i["ticker"] for i in us] == ["NVDA", "MSFT"]
        assert [i["ticker"] for i in jp] == ["7203.T", "6758.T"]

    def test_empty_list(self) -> None:
        us, jp = split_by_market([])
        assert us == []
        assert jp == []

    def test_all_us(self) -> None:
        items = [{"ticker": "AAPL"}, {"ticker": "GOOGL"}]
        us, jp = split_by_market(items)
        assert len(us) == 2
        assert len(jp) == 0

    def test_all_jp(self) -> None:
        items = [{"ticker": "7203.T"}, {"ticker": "8306.T"}]
        us, jp = split_by_market(items)
        assert len(us) == 0
        assert len(jp) == 2

    def test_custom_key(self) -> None:
        items = [{"symbol": "NVDA"}, {"symbol": "7203.T"}]
        us, jp = split_by_market(items, ticker_key="symbol")
        assert len(us) == 1
        assert len(jp) == 1


class TestTickerDisplayName:
    def test_jp_ticker_with_name(self) -> None:
        assert ticker_display_name("7203.T") == "7203.T（トヨタ）"

    def test_jp_ticker_softbank(self) -> None:
        assert ticker_display_name("9984.T") == "9984.T（ソフトバンクG）"

    def test_us_ticker_unchanged(self) -> None:
        assert ticker_display_name("NVDA") == "NVDA"

    def test_unknown_jp_ticker(self) -> None:
        # Not in _JP_TICKER_NAMES, returned as-is
        assert ticker_display_name("9999.T") == "9999.T"

    def test_empty_string(self) -> None:
        assert ticker_display_name("") == ""

    def test_all_jp_tickers_have_names(self) -> None:
        jp_tickers = [
            "7203.T", "6758.T", "9984.T", "8035.T", "9432.T",
            "6098.T", "6861.T", "6501.T", "8306.T", "2914.T",
        ]
        for ticker in jp_tickers:
            name = ticker_display_name(ticker)
            assert "（" in name, f"{ticker} should have a display name"

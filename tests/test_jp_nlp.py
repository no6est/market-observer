"""Tests for Japanese NLP support: narrative classifier, shock classifier,
ticker aliases, and mention anomaly CJK handling."""

from __future__ import annotations

import pytest

from app.enrichers.narrative_classifier import classify_narrative_category
from app.enrichers.shock_classifier import classify_shock_type
from app.enrichers.ticker_aliases import (
    TICKER_ALIASES,
    _build_alias_pattern,
    _has_cjk,
    find_related_content,
)
from app.detectors.mention_anomaly import _count_mentions


# ---------------------------------------------------------------------------
# CJK helpers
# ---------------------------------------------------------------------------

class TestHasCjk:
    def test_ascii_only(self) -> None:
        assert _has_cjk("hello") is False

    def test_katakana(self) -> None:
        assert _has_cjk("トヨタ") is True

    def test_hiragana(self) -> None:
        assert _has_cjk("にほん") is True

    def test_kanji(self) -> None:
        assert _has_cjk("日本") is True

    def test_mixed(self) -> None:
        assert _has_cjk("Toyota トヨタ") is True


class TestBuildAliasPattern:
    def test_ascii_only(self) -> None:
        pat = _build_alias_pattern(["Nvidia", "NVDA"])
        assert pat.search("Nvidia launches GPU")
        assert not pat.search("nvidia_typo")  # boundary should work

    def test_cjk_only(self) -> None:
        pat = _build_alias_pattern(["トヨタ", "日立"])
        assert pat.search("トヨタの株価")
        assert pat.search("日立製作所")

    def test_mixed(self) -> None:
        pat = _build_alias_pattern(["Toyota", "トヨタ"])
        assert pat.search("Toyota announced")
        assert pat.search("トヨタが発表")


# ---------------------------------------------------------------------------
# Ticker aliases JP
# ---------------------------------------------------------------------------

class TestJpTickerAliases:
    def test_jp_tickers_present(self) -> None:
        jp_tickers = ["7203.T", "6758.T", "9984.T", "8035.T", "9432.T",
                       "6098.T", "6861.T", "6501.T", "8306.T", "2914.T"]
        for t in jp_tickers:
            assert t in TICKER_ALIASES, f"{t} missing from TICKER_ALIASES"

    def test_toyota_aliases(self) -> None:
        aliases = TICKER_ALIASES["7203.T"]
        assert "トヨタ" in aliases
        assert "Toyota" in aliases

    def test_sony_aliases(self) -> None:
        aliases = TICKER_ALIASES["6758.T"]
        assert "ソニー" in aliases
        assert "Sony" in aliases


class TestFindRelatedContentJp:
    def test_match_japanese_company_name(self) -> None:
        articles = [{"title": "トヨタが新型EVを発表", "summary": ""}]
        matched_articles, _ = find_related_content("7203.T", articles, [])
        assert len(matched_articles) == 1

    def test_match_english_name_for_jp_ticker(self) -> None:
        articles = [{"title": "Toyota reports strong quarterly results", "summary": ""}]
        matched_articles, _ = find_related_content("7203.T", articles, [])
        assert len(matched_articles) == 1

    def test_match_japanese_post(self) -> None:
        posts = [{"title": "ソニーの決算", "body": "PlayStation好調"}]
        _, matched_posts = find_related_content("6758.T", [], posts)
        assert len(matched_posts) == 1

    def test_no_match(self) -> None:
        articles = [{"title": "Apple launches new iPhone", "summary": ""}]
        matched_articles, _ = find_related_content("7203.T", articles, [])
        assert len(matched_articles) == 0


# ---------------------------------------------------------------------------
# Mention anomaly CJK
# ---------------------------------------------------------------------------

class TestCountMentionsCjk:
    def test_japanese_alias_match(self) -> None:
        texts = ["トヨタが新型車を発表した"]
        count = _count_mentions("7203.T", texts)
        assert count >= 1

    def test_english_alias_for_jp_ticker(self) -> None:
        texts = ["Toyota Motor Corporation announced results"]
        count = _count_mentions("7203.T", texts)
        assert count >= 1

    def test_no_match_different_company(self) -> None:
        texts = ["Apple launched a new product"]
        count = _count_mentions("7203.T", texts)
        assert count == 0

    def test_ambiguous_jt(self) -> None:
        """JT is ambiguous — case-sensitive matching."""
        texts = ["JT announced dividends"]
        count = _count_mentions("2914.T", texts)
        assert count >= 1

    def test_ambiguous_ntt(self) -> None:
        """NTT is ambiguous — case-sensitive matching."""
        texts = ["NTT expands fiber network"]
        count = _count_mentions("9432.T", texts)
        assert count >= 1


# ---------------------------------------------------------------------------
# Narrative classifier JP
# ---------------------------------------------------------------------------

class TestNarrativeClassifierJp:
    @pytest.fixture
    def base_event(self) -> dict:
        return {"ticker": "7203.T", "signal_type": "price_change",
                "score": 0.8, "summary": "", "details": {}}

    def test_ai_japanese(self, base_event) -> None:
        articles = [{"title": "生成AIの活用が加速", "summary": "大規模言語モデルの企業導入"}]
        result = classify_narrative_category(base_event, articles, [])
        assert result == "AI/LLM/自動化"

    def test_regulation_japanese(self, base_event) -> None:
        articles = [{"title": "独占禁止法に基づく制裁", "summary": "輸出規制の強化"}]
        result = classify_narrative_category(base_event, articles, [])
        assert result == "規制/政策/地政学"

    def test_financial_japanese(self, base_event) -> None:
        articles = [{"title": "日銀が利上げを決定", "summary": "金融政策の転換でインフレ懸念"}]
        result = classify_narrative_category(base_event, articles, [])
        assert result == "金融/金利/流動性"

    def test_semiconductor_japanese(self, base_event) -> None:
        articles = [{"title": "半導体製造装置の受注増", "summary": "GPU需要とHBMの供給逼迫"}]
        result = classify_narrative_category(base_event, articles, [])
        assert result == "半導体/供給網"

    def test_energy_japanese(self, base_event) -> None:
        articles = [{"title": "再生可能エネルギーへの転換加速", "summary": "太陽光発電と蓄電池"}]
        result = classify_narrative_category(base_event, articles, [])
        assert result == "エネルギー/資源"

    def test_governance_japanese(self, base_event) -> None:
        articles = [{"title": "社長辞任で経営再建へ", "summary": "取締役会がリストラを決定"}]
        result = classify_narrative_category(base_event, articles, [])
        assert result == "ガバナンス/経営"

    def test_mixed_en_ja(self, base_event) -> None:
        """Mixed English + Japanese should still classify correctly."""
        articles = [
            {"title": "AI regulation concerns", "summary": ""},
            {"title": "人工知能の規制議論", "summary": ""},
        ]
        result = classify_narrative_category(base_event, articles, [])
        # Should pick up both AI and regulation keywords
        assert result in ("AI/LLM/自動化", "規制/政策/地政学")


# ---------------------------------------------------------------------------
# Shock classifier JP
# ---------------------------------------------------------------------------

class TestShockClassifierJp:
    def test_tech_shock_japanese(self) -> None:
        anomaly = {"ticker": "6758.T", "signal_type": "price_change", "score": 0.8}
        articles = [{"title": "ソニーが新製品を発表", "summary": "技術革新による破壊的イノベーション"}]
        result = classify_shock_type(anomaly, articles, [])
        assert result == "Tech shock"

    def test_regulation_shock_japanese(self) -> None:
        anomaly = {"ticker": "9984.T", "signal_type": "price_change", "score": 0.8}
        articles = [{"title": "独占禁止法違反で課徴金", "summary": "規制当局がコンプライアンス強化"}]
        result = classify_shock_type(anomaly, articles, [])
        assert result == "Regulation shock"

    def test_execution_japanese(self) -> None:
        anomaly = {"ticker": "7203.T", "signal_type": "price_change", "score": 0.8}
        articles = [{"title": "トヨタ四半期決算で上方修正", "summary": "業績好調でガイダンス引き上げ"}]
        result = classify_shock_type(anomaly, articles, [])
        assert result == "Execution signal"

    def test_business_model_japanese(self) -> None:
        anomaly = {"ticker": "6098.T", "signal_type": "price_change", "score": 0.8}
        articles = [{"title": "リクルートが事業再編を発表", "summary": "買収と合併で収益モデル転換"}]
        result = classify_shock_type(anomaly, articles, [])
        assert result == "Business model shock"

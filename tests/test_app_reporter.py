"""Tests for the daily report generator."""

from __future__ import annotations

import pytest

from app.reporter.daily_report import generate_daily_report


@pytest.fixture
def sample_anomalies() -> list[dict]:
    return [
        {
            "ticker": "NVDA",
            "signal_type": "price_change",
            "score": 0.85,
            "summary": "NVDA dropped 8% on earnings miss",
        },
        {
            "ticker": "CRWD",
            "signal_type": "volume_spike",
            "score": 0.72,
            "summary": "CRWD volume 3x above average",
        },
    ]


@pytest.fixture
def sample_themes() -> list[dict]:
    return [
        {
            "name": "AI Infrastructure Spending",
            "momentum": 0.9,
            "mention_count": 42,
            "keywords": ["NVDA", "MSFT", "infrastructure"],
        },
    ]


@pytest.fixture
def sample_facts() -> list[dict]:
    return [
        {"text": "NVDA reported Q4 earnings below consensus.", "source": "https://example.com/nvda"},
        {"text": "Fed signaled rate hold through Q2.", "source": None},
    ]


@pytest.fixture
def sample_hypotheses() -> list[dict]:
    return [
        {
            "hypothesis": "NVDA price drop driven by margin guidance concerns",
            "confidence": 0.7,
            "evidence": ["https://example.com/nvda-earnings"],
            "counterpoints": ["Data center demand may offset margin pressure."],
        },
    ]


@pytest.fixture
def sample_propagation() -> list[dict]:
    return [
        {
            "source_ticker": "NVDA",
            "related_tickers": ["AMD", "SMCI"],
            "sector": "AI_Infrastructure",
            "reason": "Shared supply chain and customer base.",
        },
    ]


@pytest.fixture
def sample_queries() -> list[str]:
    return ["NVDA earnings guidance", "AI chip demand 2025"]


class TestReportSections:
    def test_all_sections_present(
        self,
        sample_anomalies,
        sample_themes,
        sample_facts,
        sample_hypotheses,
        sample_propagation,
        sample_queries,
    ) -> None:
        """Report should contain all required section headers."""
        report = generate_daily_report(
            anomalies=sample_anomalies,
            themes=sample_themes,
            facts=sample_facts,
            hypotheses=sample_hypotheses,
            propagation=sample_propagation,
            tracking_queries=sample_queries,
            date="2025-01-15",
        )

        assert "# 日次マーケット観測レポート - 2025-01-15" in report
        assert "## 異常検出サマリー" in report
        assert "## 新興テーマ" in report
        assert "## ファクト" in report
        assert "## 仮説" in report
        assert "## 波及候補" in report
        assert "## 追跡クエリ" in report
        assert "レポート生成日時" in report

    def test_anomalies_rendered(self, sample_anomalies) -> None:
        """Anomaly data should appear in the report table."""
        report = generate_daily_report(
            anomalies=sample_anomalies,
            themes=[],
            facts=[],
            hypotheses=[],
            propagation=[],
            tracking_queries=[],
        )

        assert "NVDA" in report
        assert "価格変動" in report
        assert "0.85" in report
        assert "CRWD" in report

    def test_themes_rendered(self, sample_themes) -> None:
        """Theme data should appear in the report."""
        report = generate_daily_report(
            anomalies=[],
            themes=sample_themes,
            facts=[],
            hypotheses=[],
            propagation=[],
            tracking_queries=[],
        )

        assert "AI Infrastructure Spending" in report
        assert "NVDA" in report
        assert "MSFT" in report

    def test_facts_rendered(self, sample_facts) -> None:
        """Facts should appear as bullet points with optional source links."""
        report = generate_daily_report(
            anomalies=[],
            themes=[],
            facts=sample_facts,
            hypotheses=[],
            propagation=[],
            tracking_queries=[],
        )

        assert "NVDA reported Q4 earnings below consensus" in report
        assert "https://example.com/nvda" in report
        assert "Fed signaled rate hold" in report

    def test_hypotheses_rendered(self, sample_hypotheses) -> None:
        """Hypotheses should include confidence and evidence."""
        report = generate_daily_report(
            anomalies=[],
            themes=[],
            facts=[],
            hypotheses=sample_hypotheses,
            propagation=[],
            tracking_queries=[],
        )

        assert "margin guidance concerns" in report
        assert "70%" in report
        assert "https://example.com/nvda-earnings" in report
        assert "反論" in report

    def test_facts_and_hypotheses_separate(
        self, sample_facts, sample_hypotheses
    ) -> None:
        """Facts section and Hypotheses section should be separate and distinct."""
        report = generate_daily_report(
            anomalies=[],
            themes=[],
            facts=sample_facts,
            hypotheses=sample_hypotheses,
            propagation=[],
            tracking_queries=[],
        )

        facts_pos = report.index("## ファクト")
        hyp_pos = report.index("## 仮説")

        # Facts section comes before Hypotheses
        assert facts_pos < hyp_pos

        # The fact text should appear between Facts and Hypotheses headers
        fact_text_pos = report.index("NVDA reported Q4 earnings below consensus")
        assert facts_pos < fact_text_pos < hyp_pos

        # The hypothesis text should appear after Hypotheses header
        hyp_text_pos = report.index("margin guidance concerns")
        assert hyp_text_pos > hyp_pos


class TestReportWithEmptyData:
    def test_empty_anomalies(self) -> None:
        """Report should render gracefully with no anomalies."""
        report = generate_daily_report(
            anomalies=[],
            themes=[],
            facts=[],
            hypotheses=[],
            propagation=[],
            tracking_queries=[],
        )

        assert "異常は検出されませんでした" in report

    def test_empty_themes(self) -> None:
        """Report should render gracefully with no themes."""
        report = generate_daily_report(
            anomalies=[],
            themes=[],
            facts=[],
            hypotheses=[],
            propagation=[],
            tracking_queries=[],
        )

        assert "新興テーマは検出されませんでした" in report

    def test_empty_facts(self) -> None:
        """Report should render gracefully with no facts."""
        report = generate_daily_report(
            anomalies=[],
            themes=[],
            facts=[],
            hypotheses=[],
            propagation=[],
            tracking_queries=[],
        )

        assert "特筆すべきファクトはありませんでした" in report

    def test_empty_hypotheses(self) -> None:
        """Report should render gracefully with no hypotheses."""
        report = generate_daily_report(
            anomalies=[],
            themes=[],
            facts=[],
            hypotheses=[],
            propagation=[],
            tracking_queries=[],
        )

        assert "仮説は生成されませんでした" in report

    def test_all_empty(self) -> None:
        """Completely empty report should still be valid Markdown."""
        report = generate_daily_report(
            anomalies=[],
            themes=[],
            facts=[],
            hypotheses=[],
            propagation=[],
            tracking_queries=[],
        )

        # Should still have all section headers
        assert "## 異常検出サマリー" in report
        assert "## 新興テーマ" in report
        assert "## ファクト" in report
        assert "## 仮説" in report
        assert "## 波及候補" in report
        assert "## 追跡クエリ" in report


class TestReportMarkdown:
    def test_markdown_table_format(self, sample_anomalies) -> None:
        """Anomaly table should use Markdown table syntax."""
        report = generate_daily_report(
            anomalies=sample_anomalies,
            themes=[],
            facts=[],
            hypotheses=[],
            propagation=[],
            tracking_queries=[],
        )

        # Should have table header row
        assert "| 順位 | 銘柄 | シグナル | スコア | サマリー |" in report
        # Should have separator row
        assert "|------|------|----------|--------|----------|" in report

    def test_tracking_queries_as_code(self, sample_queries) -> None:
        """Tracking queries should be rendered as code blocks."""
        report = generate_daily_report(
            anomalies=[],
            themes=[],
            facts=[],
            hypotheses=[],
            propagation=[],
            tracking_queries=sample_queries,
        )

        assert "`NVDA earnings guidance`" in report
        assert "`AI chip demand 2025`" in report

    def test_custom_date(self) -> None:
        """Report should use the provided date."""
        report = generate_daily_report(
            anomalies=[],
            themes=[],
            facts=[],
            hypotheses=[],
            propagation=[],
            tracking_queries=[],
            date="2025-06-15",
        )

        assert "2025-06-15" in report

    def test_propagation_rendered(self, sample_propagation) -> None:
        """Propagation candidates should be rendered."""
        report = generate_daily_report(
            anomalies=[],
            themes=[],
            facts=[],
            hypotheses=[],
            propagation=sample_propagation,
            tracking_queries=[],
        )

        assert "NVDA" in report
        assert "AMD" in report
        assert "SMCI" in report
        assert "AI_Infrastructure" in report

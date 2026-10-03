"""Tests for price data integrity: upsert, NULL handling, splits, stale bars."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.__main__ import _report_day_start_utc
from app.collectors.price import SPLIT_REFETCH_PERIOD, YFinancePriceCollector
from app.config import DetectionConfig
from app.database import Database
from app.detectors.price_anomaly import detect_price_anomalies
from app.detectors.volume_anomaly import detect_volume_anomalies
from app.enrichers.hypothesis import generate_hypotheses
from app.enrichers.narrative_archive import evaluate_pending_hypotheses, extract_ticker


@pytest.fixture
def db(tmp_path) -> Database:
    return Database(tmp_path / "test.db")


@pytest.fixture
def config() -> DetectionConfig:
    return DetectionConfig(lookback_days=30, z_threshold=2.0, cooldown_hours=24)


def _bar(ts: str, close: float | None, volume: int = 1_000_000) -> dict:
    return {"ticker": "TEST", "timestamp": ts, "open": close, "high": close,
            "low": close, "close": close, "volume": volume}


def _series(closes: list[float], volumes: list[int] | None = None) -> list[dict]:
    now = datetime.utcnow()
    return [
        _bar((now - timedelta(days=len(closes) - 1 - i)).strftime("%Y-%m-%d %H:%M:%S"),
             c, volumes[i] if volumes else 1_000_000)
        for i, c in enumerate(closes)
    ]


def _set_collected_at(db: Database, value: str) -> None:
    with db._connect() as conn:
        conn.execute("UPDATE price_data SET collected_at = ?", (value,))


class TestPriceUpsert:
    def test_existing_bar_is_overwritten(self, db: Database) -> None:
        """A re-fetched (e.g. split-adjusted) value replaces the stored one."""
        db.insert_price_data([_bar("2026-07-01 00:00:00", 772.74)])
        db.insert_price_data([_bar("2026-07-01 00:00:00", 193.18)])
        rows = db.get_price_history("TEST", days=10_000)
        assert len(rows) == 1
        assert rows[0]["close"] == 193.18

    def test_bar_without_close_is_not_stored(self, db: Database) -> None:
        assert db.insert_price_data([_bar("2026-09-29 00:00:00", None)]) == 0
        assert db.get_price_history("TEST", days=10_000) == []

    def test_null_does_not_overwrite_valid_close(self, db: Database) -> None:
        db.insert_price_data([_bar("2026-09-28 00:00:00", 334.68)])
        db.insert_price_data([_bar("2026-09-28 00:00:00", None)])
        assert db.get_price_history("TEST", days=10_000)[0]["close"] == 334.68

    def test_update_keeps_first_collected_at(self, db: Database) -> None:
        db.insert_price_data([_bar("2026-09-28 00:00:00", 100.0)])
        _set_collected_at(db, "2026-09-29 00:00:00")
        db.insert_price_data([_bar("2026-09-28 00:00:00", 101.0)])
        assert db.get_price_history("TEST", days=10_000)[0]["collected_at"] == "2026-09-29 00:00:00"

    def test_delete_null_price_rows(self, db: Database) -> None:
        with db._connect() as conn:
            conn.execute(
                "INSERT INTO price_data (ticker, timestamp, close, volume) VALUES ('TEST', '2026-09-29', NULL, 5)"
            )
        db.insert_price_data([_bar("2026-09-28 00:00:00", 100.0)])
        assert db.delete_null_price_rows() == 1
        assert len(db.get_price_history("TEST", days=10_000)) == 1


class TestSplitRefetch:
    def _frame(self, splits: list[float]) -> pd.DataFrame:
        idx = pd.date_range("2026-06-30", periods=len(splits), tz="America/New_York")
        return pd.DataFrame({
            "Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1,
            "Stock Splits": splits,
        }, index=idx)

    def test_refetches_long_history_when_split_in_window(self) -> None:
        tk = MagicMock()
        tk.history.side_effect = [self._frame([0, 4.0, 0]), self._frame([0] * 5)]
        with patch("app.collectors.price.yf.Ticker", return_value=tk):
            rows = YFinancePriceCollector().collect(["CRWD"], period="1mo")
        assert [c.kwargs["period"] for c in tk.history.call_args_list] == ["1mo", SPLIT_REFETCH_PERIOD]
        assert len(rows) == 5

    def test_no_refetch_without_split(self) -> None:
        tk = MagicMock()
        tk.history.return_value = self._frame([0, 0, 0])
        with patch("app.collectors.price.yf.Ticker", return_value=tk):
            rows = YFinancePriceCollector().collect(["NVDA"], period="1mo")
        assert tk.history.call_count == 1
        assert len(rows) == 3


class TestStaleBarSkipping:
    def test_report_day_start_is_jst_midnight_in_utc(self) -> None:
        assert _report_day_start_utc("2026-10-04") == "2026-10-03 15:00:00"

    def test_price_anomaly_skipped_when_bar_already_seen(self, db, config) -> None:
        db.insert_price_data(_series([100.0] * 15 + [80.0]))
        _set_collected_at(db, "2026-10-02 23:00:00")
        assert detect_price_anomalies(db, ["TEST"], config, fresh_since="2026-10-03 15:00:00") == []

    def test_price_anomaly_reported_for_new_bar(self, db, config) -> None:
        db.insert_price_data(_series([100.0, 101.0, 99.0, 100.5, 99.5] * 3 + [80.0]))
        _set_collected_at(db, "2026-10-03 23:00:00")
        anomalies = detect_price_anomalies(db, ["TEST"], config, fresh_since="2026-10-03 15:00:00")
        assert len(anomalies) == 1

    def test_volume_anomaly_skipped_when_bar_already_seen(self, db, config) -> None:
        db.insert_price_data(_series([100.0] * 16, [1_000_000, 1_010_000, 990_000] * 5 + [5_000_000]))
        _set_collected_at(db, "2026-10-02 23:00:00")
        assert detect_volume_anomalies(db, ["TEST"], config, fresh_since="2026-10-03 15:00:00") == []


class TestAbsoluteReturnThreshold:
    # Volatile series: +-6% swings make the std large, so a +9% day has z < 2.
    VOLATILE = [100.0, 106.0, 100.0, 106.0, 100.0, 106.0, 100.0, 106.0,
                100.0, 106.0, 100.0, 106.0, 100.0, 106.0, 100.0]

    def test_large_move_below_z_threshold_is_detected(self, db, config) -> None:
        db.insert_price_data(_series(self.VOLATILE + [109.0]))
        anomalies = detect_price_anomalies(db, ["TEST"], config)
        assert len(anomalies) == 1
        assert abs(anomalies[0]["z_score"]) < config.z_threshold
        assert anomalies[0]["details"]["trigger"] == "abs_return"
        # Scored at least as high as a z_threshold hit
        assert anomalies[0]["score"] >= config.z_threshold / 5.0

    def test_threshold_zero_disables(self, db) -> None:
        cfg = DetectionConfig(lookback_days=30, z_threshold=2.0, cooldown_hours=24,
                              min_abs_return_pct=0)
        db.insert_price_data(_series(self.VOLATILE + [109.0]))
        assert detect_price_anomalies(db, ["TEST"], cfg) == []

    def test_small_move_not_detected(self, db, config) -> None:
        db.insert_price_data(_series(self.VOLATILE + [103.0]))
        assert detect_price_anomalies(db, ["TEST"], config) == []


class TestHypothesisTicker:
    def test_generated_hypothesis_carries_ticker(self) -> None:
        anomaly = {"ticker": "MSFT", "signal_type": "price_change", "score": 0.5,
                   "z_score": 2.1, "summary": "前日比+2.25%の価格変動", "details": {}}
        hyps = generate_hypotheses([anomaly], [], [])
        assert hyps[0]["ticker"] == "MSFT"
        assert hyps[0]["signal_type"] == "price_change"

    @pytest.mark.parametrize("text,expected", [
        ("マイクロソフト（MSFT）の株価は2.25%上昇", "MSFT"),
        ("NVIDIA (NVDA) に関する言及が増加", "NVDA"),
        ("AI基盤セクターの動向", None),
        ("ネクステラ・エナジー（", None),
    ])
    def test_extract_ticker(self, text: str, expected: str | None) -> None:
        assert extract_ticker(text) == expected

    def test_legacy_row_without_ticker_is_evaluated(self) -> None:
        db = MagicMock()
        db.get_pending_hypotheses.return_value = [
            {"id": 7, "date": "2026-08-28", "ticker": None,
             "hypothesis": "クラウドストライク（CRWD）が過去最高益"},
        ]
        db.get_enriched_events_history.return_value = [{"ticker": "CRWD"}]
        results = evaluate_pending_hypotheses(db, "2026-10-01")
        assert results[0]["evaluation"] == "confirmed"
        assert results[0]["ticker"] == "CRWD"

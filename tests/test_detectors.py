"""Tests for anomaly detection modules."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.detectors.price_anomaly import detect_price_anomalies
from src.detectors.volume_anomaly import detect_volume_anomalies
from src.storage.database import Database
from src.utils.config import DetectionConfig


@pytest.fixture
def db(tmp_path) -> Database:
    """Create a fresh database in a temp directory for each test."""
    return Database(tmp_path / "test.db")


@pytest.fixture
def config() -> DetectionConfig:
    """Default detection config with a low threshold for testing."""
    return DetectionConfig(
        lookback_days=30,
        z_threshold=2.0,
        cooldown_hours=24,
    )


def _insert_price_series(
    db: Database,
    ticker: str,
    closes: list[float],
    volumes: list[int] | None = None,
) -> None:
    """Helper to insert a series of price data points for a ticker.

    Generates timestamps going backwards from now, one per day.
    """
    now = datetime.utcnow()
    rows = []
    for i, close in enumerate(closes):
        ts = (now - timedelta(days=len(closes) - 1 - i)).strftime("%Y-%m-%d %H:%M:%S")
        volume = volumes[i] if volumes else 1000000
        rows.append({
            "ticker": ticker,
            "timestamp": ts,
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "volume": volume,
        })
    db.insert_price_data(rows)


# ---- Price Anomaly Detection ----


class TestPriceAnomalyDetection:
    def test_detects_large_price_spike(self, db: Database, config: DetectionConfig) -> None:
        """A sudden large price move should trigger an anomaly."""
        # Stable prices around 100, then a spike to 120 (+20%)
        closes = [100.0] * 15 + [120.0]
        _insert_price_series(db, "TEST", closes)

        anomalies = detect_price_anomalies(db, ["TEST"], config)
        assert len(anomalies) == 1
        assert anomalies[0]["ticker"] == "TEST"
        assert anomalies[0]["signal_type"] == "price_change"
        assert anomalies[0]["z_score"] > 0

    def test_no_anomaly_for_stable_prices(self, db: Database, config: DetectionConfig) -> None:
        """Stable prices with small fluctuations should not trigger."""
        closes = [100.0, 101.0, 99.5, 100.5, 101.0, 100.0, 100.2, 99.8, 100.1, 100.3]
        _insert_price_series(db, "TEST", closes)

        anomalies = detect_price_anomalies(db, ["TEST"], config)
        assert len(anomalies) == 0

    def test_score_normalized_0_to_1(self, db: Database, config: DetectionConfig) -> None:
        """Score should always be in [0, 1] range."""
        # Extreme spike to force a high z-score
        closes = [100.0] * 15 + [200.0]
        _insert_price_series(db, "TEST", closes)

        anomalies = detect_price_anomalies(db, ["TEST"], config)
        assert len(anomalies) == 1
        assert 0.0 <= anomalies[0]["score"] <= 1.0

    def test_cooldown_prevents_duplicate_anomaly(
        self, db: Database, config: DetectionConfig
    ) -> None:
        """If a recent anomaly exists for the same ticker+signal, skip it."""
        closes = [100.0] * 15 + [130.0]
        _insert_price_series(db, "TEST", closes)

        # Insert an existing anomaly to trigger cooldown
        db.insert_anomaly({
            "ticker": "TEST",
            "signal_type": "price_change",
            "score": 0.5,
        })

        anomalies = detect_price_anomalies(db, ["TEST"], config)
        assert len(anomalies) == 0

    def test_insufficient_data_skipped(self, db: Database, config: DetectionConfig) -> None:
        """Tickers with fewer than 3 data points should be skipped."""
        _insert_price_series(db, "TEST", [100.0, 101.0])

        anomalies = detect_price_anomalies(db, ["TEST"], config)
        assert len(anomalies) == 0

    def test_zero_std_skipped(self, db: Database, config: DetectionConfig) -> None:
        """All identical prices yield zero std, which should be skipped (no division by zero)."""
        closes = [100.0] * 10
        _insert_price_series(db, "TEST", closes)

        anomalies = detect_price_anomalies(db, ["TEST"], config)
        assert len(anomalies) == 0

    def test_multiple_tickers(self, db: Database, config: DetectionConfig) -> None:
        """Detection should process multiple tickers independently."""
        # SPIKE should trigger, STABLE should not
        _insert_price_series(db, "SPIKE", [100.0] * 15 + [130.0])
        _insert_price_series(db, "STABLE", [100.0, 100.5, 99.5, 100.2, 100.1, 99.9, 100.3])

        anomalies = detect_price_anomalies(db, ["SPIKE", "STABLE"], config)
        tickers = [a["ticker"] for a in anomalies]
        assert "SPIKE" in tickers
        assert "STABLE" not in tickers


# ---- Volume Anomaly Detection ----


class TestVolumeAnomalyDetection:
    def test_detects_volume_spike(self, db: Database, config: DetectionConfig) -> None:
        """A sudden volume spike should trigger an anomaly."""
        volumes = [1000000, 1010000, 990000, 1005000, 995000, 1002000, 998000,
                   1003000, 997000, 1001000, 999000, 1004000, 996000, 1000000, 1000000] + [5000000]
        closes = [100.0] * 16
        _insert_price_series(db, "TEST", closes, volumes)

        anomalies = detect_volume_anomalies(db, ["TEST"], config)
        assert len(anomalies) == 1
        assert anomalies[0]["signal_type"] == "volume_spike"
        assert anomalies[0]["z_score"] > 0

    def test_no_anomaly_for_stable_volume(self, db: Database, config: DetectionConfig) -> None:
        """Stable volume should not trigger."""
        volumes = [1000000, 1050000, 980000, 1020000, 1010000, 990000, 1000000]
        closes = [100.0] * 7
        _insert_price_series(db, "TEST", closes, volumes)

        anomalies = detect_volume_anomalies(db, ["TEST"], config)
        assert len(anomalies) == 0

    def test_volume_score_normalized(self, db: Database, config: DetectionConfig) -> None:
        """Volume anomaly score should be in [0, 1]."""
        volumes = [1000000, 1010000, 990000, 1005000, 995000, 1002000, 998000,
                   1003000, 997000, 1001000, 999000, 1004000, 996000, 1000000, 1000000] + [50000000]
        closes = [100.0] * 16
        _insert_price_series(db, "TEST", closes, volumes)

        anomalies = detect_volume_anomalies(db, ["TEST"], config)
        assert len(anomalies) == 1
        assert 0.0 <= anomalies[0]["score"] <= 1.0

    def test_volume_cooldown(self, db: Database, config: DetectionConfig) -> None:
        """Cooldown should prevent duplicate volume anomalies."""
        volumes = [1000000] * 15 + [5000000]
        closes = [100.0] * 16
        _insert_price_series(db, "TEST", closes, volumes)

        db.insert_anomaly({
            "ticker": "TEST",
            "signal_type": "volume_spike",
            "score": 0.5,
        })

        anomalies = detect_volume_anomalies(db, ["TEST"], config)
        assert len(anomalies) == 0

    def test_volume_insufficient_data(self, db: Database, config: DetectionConfig) -> None:
        """Should skip tickers with insufficient volume data."""
        _insert_price_series(db, "TEST", [100.0, 101.0], [1000000, 1000000])

        anomalies = detect_volume_anomalies(db, ["TEST"], config)
        assert len(anomalies) == 0

    def test_volume_zero_std_skipped(self, db: Database, config: DetectionConfig) -> None:
        """Identical volumes yield zero std, should be skipped."""
        volumes = [1000000] * 10
        closes = [100.0] * 10
        _insert_price_series(db, "TEST", closes, volumes)

        anomalies = detect_volume_anomalies(db, ["TEST"], config)
        assert len(anomalies) == 0


# ---- Z-Score Calculation Verification ----


class TestZScoreCalculation:
    def test_z_score_value_is_correct(self, db: Database) -> None:
        """Verify z-score calculation with known data."""
        # Series: 10 days of return=0 (close stays at 100), then +10%
        # Returns: [0, 0, 0, ..., 0.1]
        # Mean of returns (all 10): close to 0.01 (average including the spike)
        # We'll use a very specific case for calculation
        closes = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 110.0]
        _insert_price_series(db, "CALC", closes)

        config = DetectionConfig(lookback_days=30, z_threshold=0.0, cooldown_hours=0)
        anomalies = detect_price_anomalies(db, ["CALC"], config)

        assert len(anomalies) == 1
        a = anomalies[0]

        # 10 returns: 9 zeros + 1 at 0.1
        # mean = 0.1 / 10 = 0.01
        # variance = (9 * (0 - 0.01)^2 + 1 * (0.1 - 0.01)^2) / 10
        #          = (9 * 0.0001 + 1 * 0.0081) / 10
        #          = (0.0009 + 0.0081) / 10
        #          = 0.009 / 10 = 0.0009
        # std = sqrt(0.0009) = 0.03
        # z = (0.1 - 0.01) / 0.03 = 3.0

        assert abs(a["z_score"] - 3.0) < 0.01
        assert a["value"] is not None
        assert a["mean"] is not None
        assert a["std"] is not None

    def test_negative_z_score_for_drop(self, db: Database) -> None:
        """A large price drop should produce a negative z-score."""
        closes = [100.0] * 15 + [80.0]  # -20% drop
        _insert_price_series(db, "DROP", closes)

        config = DetectionConfig(lookback_days=30, z_threshold=0.0, cooldown_hours=0)
        anomalies = detect_price_anomalies(db, ["DROP"], config)

        assert len(anomalies) == 1
        assert anomalies[0]["z_score"] < 0

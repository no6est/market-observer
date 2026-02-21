"""Tests for configuration loading."""

import tempfile
from pathlib import Path

import pytest
import yaml

from src.utils.config import (
    AppConfig,
    DetectionConfig,
    HackerNewsConfig,
    RedditConfig,
    ReportConfig,
    RSSFeed,
    load_config,
)


@pytest.fixture
def sample_config_path(tmp_path: Path) -> Path:
    """Write a minimal config YAML to a temp directory and return its path."""
    data = {
        "tickers": ["AAPL", "GOOG"],
        "rss_feeds": [
            {"name": "TestFeed", "url": "https://example.com/rss"},
        ],
        "reddit": {
            "subreddits": ["python"],
            "limit_per_sub": 25,
        },
        "hackernews": {
            "enabled": False,
            "min_score": 50,
            "limit": 20,
        },
        "detection": {
            "lookback_days": 10,
            "z_threshold": 3.0,
            "cooldown_hours": 12,
            "max_anomalies_per_report": 5,
        },
        "report": {
            "output_dir": "out",
            "top_n_anomalies": 3,
            "top_n_themes": 2,
        },
        "sector_map": {
            "Tech": ["AAPL", "GOOG"],
        },
        "database": {
            "path": "test.db",
        },
    }
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(data), encoding="utf-8")
    return config_file


def test_load_config_parses_all_fields(sample_config_path: Path) -> None:
    """Verify all config fields are loaded from YAML correctly."""
    cfg = load_config(sample_config_path)

    assert cfg.tickers == ["AAPL", "GOOG"]
    assert len(cfg.rss_feeds) == 1
    assert cfg.rss_feeds[0].name == "TestFeed"
    assert cfg.rss_feeds[0].url == "https://example.com/rss"

    assert cfg.reddit.subreddits == ["python"]
    assert cfg.reddit.limit_per_sub == 25

    assert cfg.hackernews.enabled is False
    assert cfg.hackernews.min_score == 50
    assert cfg.hackernews.limit == 20

    assert cfg.detection.lookback_days == 10
    assert cfg.detection.z_threshold == 3.0
    assert cfg.detection.cooldown_hours == 12
    assert cfg.detection.max_anomalies_per_report == 5

    assert cfg.report.output_dir == "out"
    assert cfg.report.top_n_anomalies == 3
    assert cfg.report.top_n_themes == 2

    assert cfg.sector_map == {"Tech": ["AAPL", "GOOG"]}
    assert cfg.database_path == "test.db"


def test_load_config_defaults(tmp_path: Path) -> None:
    """Verify defaults when YAML has minimal content."""
    config_file = tmp_path / "minimal.yaml"
    config_file.write_text(yaml.dump({}), encoding="utf-8")

    cfg = load_config(config_file)

    assert cfg.tickers == []
    assert cfg.rss_feeds == []
    assert cfg.reddit.subreddits == ["stocks", "technology"]
    assert cfg.reddit.limit_per_sub == 50
    assert cfg.hackernews.enabled is True
    assert cfg.hackernews.min_score == 10
    assert cfg.hackernews.limit == 100
    assert cfg.detection.lookback_days == 20
    assert cfg.detection.z_threshold == 2.0
    assert cfg.detection.cooldown_hours == 24
    assert cfg.report.output_dir == "reports"
    assert cfg.database_path == "data/market_obs.db"


def test_load_config_missing_file() -> None:
    """Verify FileNotFoundError when config file doesn't exist."""
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_config("/nonexistent/path/config.yaml")


def test_load_config_accepts_string_path(sample_config_path: Path) -> None:
    """Verify load_config accepts a string path."""
    cfg = load_config(str(sample_config_path))
    assert cfg.tickers == ["AAPL", "GOOG"]


def test_dataclass_defaults() -> None:
    """Verify dataclass defaults match expected values."""
    detection = DetectionConfig()
    assert detection.lookback_days == 20
    assert detection.z_threshold == 2.0
    assert detection.cooldown_hours == 24
    assert detection.max_anomalies_per_report == 10

    report = ReportConfig()
    assert report.output_dir == "reports"

    reddit = RedditConfig()
    assert reddit.subreddits == ["stocks", "technology"]

    hn = HackerNewsConfig()
    assert hn.enabled is True

    app = AppConfig()
    assert app.tickers == []
    assert app.database_path == "data/market_obs.db"

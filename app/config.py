"""Pydantic-based YAML configuration loader."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class DetectionConfig(BaseModel):
    lookback_days: int = 20
    z_threshold: float = 2.0
    cooldown_hours: int = 24
    max_anomalies_per_report: int = 10


class ReportConfig(BaseModel):
    output_dir: str = "reports"
    top_n_anomalies: int = 5
    top_n_themes: int = 5


class RedditConfig(BaseModel):
    subreddits: list[str] = Field(default_factory=lambda: ["stocks", "technology"])
    limit_per_sub: int = 50


class HackerNewsConfig(BaseModel):
    enabled: bool = True
    min_score: int = 10
    limit: int = 100


class RSSFeed(BaseModel):
    name: str
    url: str


class GeminiConfig(BaseModel):
    enabled: bool = False
    model: str = "gemini-2.0-flash"
    api_key: str | None = None


class DatabaseConfig(BaseModel):
    path: str = "data/market_obs.db"


class AppConfig(BaseModel):
    """Root application configuration."""

    tickers: list[str] = Field(default_factory=list)
    rss_feeds: list[RSSFeed] = Field(default_factory=list)
    reddit: RedditConfig = Field(default_factory=RedditConfig)
    hackernews: HackerNewsConfig = Field(default_factory=HackerNewsConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    sector_map: dict[str, list[str]] = Field(default_factory=dict)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)

    @property
    def database_path(self) -> str:
        return self.database.path

    @classmethod
    def from_yaml(cls, path: str | Path) -> AppConfig:
        """Load configuration from a YAML file.

        Gemini API key is resolved from:
        1. config.yaml gemini.api_key
        2. Environment variable GEMINI_API_KEY
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        config = cls(**data)

        # Resolve Gemini API key from env if not set in config
        if config.gemini.enabled and not config.gemini.api_key:
            env_key = os.environ.get("GEMINI_API_KEY")
            if env_key:
                config.gemini.api_key = env_key

        return config


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load configuration from YAML file.

    Args:
        config_path: Path to config YAML. Defaults to configs/config.yaml.
    """
    if config_path is None:
        config_path = Path("configs/config.yaml")
    return AppConfig.from_yaml(config_path)

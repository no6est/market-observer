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


class NarrativeConfig(BaseModel):
    ai_threshold: float = 0.3
    overheat_ai_pct: float = 0.5
    overheat_streak_days: int = 3
    concentration_warning_pct: float = 0.6
    top_n_non_ai: int = 3
    narrative_basis: str = "all_events"
    overheat_delta_threshold: float = 0.15
    overheat_evidence_threshold: float = 0.3


class DatabaseConfig(BaseModel):
    path: str = "data/market_obs.db"


class BaselineConfig(BaseModel):
    windows: list[int] = Field(default_factory=lambda: [7, 30, 90])
    z_threshold: float = 2.0
    min_samples: int = 3


class RegimeConfig(BaseModel):
    vol_threshold: float = 0.25
    declining_threshold: float = 0.50
    weights_normal: dict[str, float] = Field(default_factory=lambda: {
        "consecutive_days": 0.25, "evidence_trend": 0.25,
        "price_trend": 0.15, "media_diffusion": 0.20, "sector_propagation": 0.15,
    })
    weights_high_vol: dict[str, float] = Field(default_factory=lambda: {
        "consecutive_days": 0.15, "evidence_trend": 0.15,
        "price_trend": 0.35, "media_diffusion": 0.15, "sector_propagation": 0.20,
    })
    weights_tightening: dict[str, float] = Field(default_factory=lambda: {
        "consecutive_days": 0.20, "evidence_trend": 0.20,
        "price_trend": 0.25, "media_diffusion": 0.20, "sector_propagation": 0.15,
    })


class NarrativeTrackConfig(BaseModel):
    keyword_overlap_threshold: float = 0.5
    ticker_overlap_threshold: float = 0.3
    cooling_inactive_days: int = 3
    weak_drift_z_threshold: float = 1.2
    weak_drift_category_ratio: float = 0.30
    use_embeddings: bool = False


class EchoChamberConfig(BaseModel):
    similarity_threshold: float = 0.7
    min_correction: float = 0.5


class SourceReliabilityConfig(BaseModel):
    tier_weights: dict[str, float] = Field(default_factory=lambda: {
        "tier1_direct": 1.0, "sns_to_tier1": 0.85,
        "sns_to_tier2": 0.60, "sns_only": 0.30, "no_coverage": 0.20,
    })
    diversity_max_bonus: float = 0.20
    diversity_source_cap: int = 5
    echo_penalty_factor: float = 0.20


class NarrativeTransitionConfig(BaseModel):
    declining_threshold: float = -0.3
    rising_threshold: float = 0.3
    history_days: int = 90
    top_n_outlook: int = 5


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
    narrative: NarrativeConfig = Field(default_factory=NarrativeConfig)
    baseline: BaselineConfig = Field(default_factory=BaselineConfig)
    regime: RegimeConfig = Field(default_factory=RegimeConfig)
    echo_chamber: EchoChamberConfig = Field(default_factory=EchoChamberConfig)
    narrative_track: NarrativeTrackConfig = Field(default_factory=NarrativeTrackConfig)
    source_reliability: SourceReliabilityConfig = Field(default_factory=SourceReliabilityConfig)
    narrative_transition: NarrativeTransitionConfig = Field(default_factory=NarrativeTransitionConfig)

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


def _load_dotenv(dotenv_path: Path | None = None) -> None:
    """Load .env file into os.environ (simple parser, no dependency)."""
    if dotenv_path is None:
        dotenv_path = Path(".env")
    if not dotenv_path.exists():
        return
    with open(dotenv_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load configuration from YAML file.

    Also loads .env file into environment if present.

    Args:
        config_path: Path to config YAML. Defaults to configs/config.yaml.
    """
    _load_dotenv()
    if config_path is None:
        config_path = Path("configs/config.yaml")
    return AppConfig.from_yaml(config_path)

"""Pydantic models for market observability data."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PriceData(BaseModel):
    """OHLCV price data for a single ticker and timestamp."""

    ticker: str
    timestamp: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None


class Article(BaseModel):
    """News article from an RSS feed."""

    source: str
    url: str
    title: str
    summary: str | None = None
    published_at: str | None = None


class CommunityPost(BaseModel):
    """Community post from Reddit, HN, etc."""

    source: str
    url: str
    title: str
    body: str | None = None
    score: int = 0
    num_comments: int = 0
    author: str | None = None
    created_at: str | None = None


class Anomaly(BaseModel):
    """Detected anomaly for a ticker."""

    ticker: str
    signal_type: str
    score: float = Field(ge=0.0, le=1.0)
    z_score: float | None = None
    value: float | None = None
    mean: float | None = None
    std: float | None = None
    summary: str | None = None
    details: dict | None = None


class Theme(BaseModel):
    """Emerging theme extracted from recent content."""

    name: str
    keywords: list[str] = Field(default_factory=list)
    mention_count: int = 0
    momentum: float = 0.0
    first_seen: str | None = None


class Hypothesis(BaseModel):
    """Explanatory hypothesis for an anomaly."""

    hypothesis: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    counterpoints: list[str] = Field(default_factory=list)


class Propagation(BaseModel):
    """Sector-based propagation candidate."""

    source_ticker: str
    related_tickers: list[str] = Field(default_factory=list)
    sector: str = ""
    reason: str = ""


class Fact(BaseModel):
    """Observed fact (no interpretation)."""

    text: str
    source: str | None = None

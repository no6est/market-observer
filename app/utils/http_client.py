"""HTTP client with rate limiting and exponential backoff."""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

_last_request_time: dict[str, float] = {}
_MIN_INTERVAL_SECONDS = 1.0
_USER_AGENT = "MarketObservability/0.2 (internal research tool)"


def _rate_limit(url: str) -> None:
    """Enforce minimum interval between requests to the same domain."""
    domain = urlparse(url).netloc
    now = time.time()
    last = _last_request_time.get(domain, 0.0)
    wait = _MIN_INTERVAL_SECONDS - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_request_time[domain] = time.time()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
)
def fetch_url(url: str, timeout: int = 30, **kwargs: Any) -> requests.Response:
    """Fetch a URL with rate limiting and retry logic."""
    _rate_limit(url)
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", _USER_AGENT)

    logger.debug("Fetching: %s", url)
    resp = requests.get(url, timeout=timeout, headers=headers, **kwargs)
    resp.raise_for_status()
    return resp


def fetch_json(url: str, timeout: int = 30, **kwargs: Any) -> Any:
    """Fetch a URL and parse JSON response."""
    resp = fetch_url(url, timeout=timeout, **kwargs)
    return resp.json()

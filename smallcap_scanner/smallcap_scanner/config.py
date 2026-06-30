"""Configuration loaded from environment variables.

All tunables live here so the screening thresholds can be changed without
touching logic. Values are read from the environment (a local ``.env`` file is
loaded automatically if ``python-dotenv`` is installed).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

try:  # optional convenience: load a local .env if present
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


# The subreddits tracked by default, plus room to extend via env.
DEFAULT_SUBREDDITS = [
    "wallstreetbets",
    "TheRaceTo10Million",
    "raceto10000",
    "smallstreetbets",
    "pennystocks",
]


@dataclass
class ScreenThresholds:
    """Fundamental / price filters that define the candidate universe."""

    price_min: float = field(default_factory=lambda: _get_float("PRICE_MIN", 0.50))
    price_max: float = field(default_factory=lambda: _get_float("PRICE_MAX", 8.0))
    market_cap_min: float = field(
        default_factory=lambda: _get_float("MARKET_CAP_MIN", 30_000_000)
    )
    market_cap_max: float = field(
        default_factory=lambda: _get_float("MARKET_CAP_MAX", 2_000_000_000)
    )
    # Minimum average daily volume — proxy for "can I actually get filled / are
    # there options". Truly illiquid micro-caps rarely have listed LEAPS.
    avg_volume_min: float = field(
        default_factory=lambda: _get_float("AVG_VOLUME_MIN", 500_000)
    )
    # Only exchanges that list options. OTC names are excluded by design.
    exchanges: List[str] = field(
        default_factory=lambda: os.getenv(
            "EXCHANGES", "nasdaq,nyse,amex"
        ).split(",")
    )


@dataclass
class Config:
    fmp_api_key: str = field(default_factory=lambda: os.getenv("FMP_API_KEY", ""))
    fmp_base_url: str = field(
        default_factory=lambda: os.getenv(
            "FMP_BASE_URL", "https://financialmodelingprep.com/api/v3"
        )
    )

    reddit_client_id: str = field(
        default_factory=lambda: os.getenv("REDDIT_CLIENT_ID", "")
    )
    reddit_client_secret: str = field(
        default_factory=lambda: os.getenv("REDDIT_CLIENT_SECRET", "")
    )
    reddit_user_agent: str = field(
        default_factory=lambda: os.getenv(
            "REDDIT_USER_AGENT", "smallcap-scanner/0.1 (by u/your_username)"
        )
    )

    subreddits: List[str] = field(
        default_factory=lambda: [
            s.strip()
            for s in os.getenv("SUBREDDITS", ",".join(DEFAULT_SUBREDDITS)).split(",")
            if s.strip()
        ]
    )
    # How many posts per subreddit listing to pull, and how far back to count
    # mentions for the "momentum" window.
    reddit_post_limit: int = field(
        default_factory=lambda: _get_int("REDDIT_POST_LIMIT", 200)
    )
    reddit_lookback_hours: int = field(
        default_factory=lambda: _get_int("REDDIT_LOOKBACK_HOURS", 72)
    )

    thresholds: ScreenThresholds = field(default_factory=ScreenThresholds)

    # Weights for the composite score (need not sum to 1; normalised at use).
    weight_fundamental: float = field(
        default_factory=lambda: _get_float("WEIGHT_FUNDAMENTAL", 0.30)
    )
    weight_momentum: float = field(
        default_factory=lambda: _get_float("WEIGHT_MOMENTUM", 0.30)
    )
    weight_social: float = field(
        default_factory=lambda: _get_float("WEIGHT_SOCIAL", 0.40)
    )

    @property
    def has_fmp(self) -> bool:
        return bool(self.fmp_api_key)

    @property
    def has_reddit(self) -> bool:
        return bool(self.reddit_client_id and self.reddit_client_secret)

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


# Subreddits ApeWisdom (https://apewisdom.io) already tracks — free, no-auth,
# licensed third-party aggregation. Preferred wherever it has coverage.
DEFAULT_APEWISDOM_SUBREDDITS = [
    "wallstreetbets",
    "pennystocks",
]

# Subreddits ApeWisdom does NOT cover, scraped directly via RSS as a fallback.
# See reddit_rss_client.py for the compliance tradeoff this involves.
DEFAULT_RSS_SUBREDDITS = [
    "TheRaceTo10Million",
    "raceto10000",
    "smallstreetbets",
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
            "FMP_BASE_URL", "https://financialmodelingprep.com/stable"
        )
    )
    # FMP's legacy /api/v3 endpoints (incl. batch quote) were retired; current
    # plans only expose single-symbol /stable/quote. This bounds how many
    # screener hits get the extra per-symbol enrichment call (50/200d avg,
    # 52w range) so a broad screen doesn't turn into thousands of requests.
    fmp_enrich_limit: int = field(
        default_factory=lambda: _get_int("FMP_ENRICH_LIMIT", 300)
    )

    # "auto" (default): ApeWisdom for the subs it covers + RSS scraping for
    # the rest, no credentials needed. "praw": official Reddit OAuth via
    # PRAW, covering every subreddit in `subreddits` — requires
    # REDDIT_CLIENT_ID/SECRET and is the only fully ToS-compliant option for
    # the subs ApeWisdom doesn't track.
    reddit_mode: str = field(default_factory=lambda: os.getenv("REDDIT_MODE", "auto"))

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

    # Used only in REDDIT_MODE=praw, where OAuth can reach any public subreddit.
    subreddits: List[str] = field(
        default_factory=lambda: [
            s.strip()
            for s in os.getenv(
                "SUBREDDITS",
                ",".join(DEFAULT_APEWISDOM_SUBREDDITS + DEFAULT_RSS_SUBREDDITS),
            ).split(",")
            if s.strip()
        ]
    )
    apewisdom_subreddits: List[str] = field(
        default_factory=lambda: [
            s.strip()
            for s in os.getenv(
                "APEWISDOM_SUBREDDITS", ",".join(DEFAULT_APEWISDOM_SUBREDDITS)
            ).split(",")
            if s.strip()
        ]
    )
    reddit_rss_subreddits: List[str] = field(
        default_factory=lambda: [
            s.strip()
            for s in os.getenv(
                "REDDIT_RSS_SUBREDDITS", ",".join(DEFAULT_RSS_SUBREDDITS)
            ).split(",")
            if s.strip()
        ]
    )
    # Delay between sequential RSS requests — keep this polite since the feeds
    # are being used outside Reddit's stated crawl policy (see
    # reddit_rss_client.py).
    reddit_rss_delay_seconds: float = field(
        default_factory=lambda: _get_float("REDDIT_RSS_DELAY_SECONDS", 2.0)
    )
    # How many posts per subreddit listing to pull (praw mode), and how far
    # back to count mentions for the "momentum" window (all modes).
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
        """Whether *some* social data source is usable.

        In "auto" mode this is always True — ApeWisdom and RSS both need no
        credentials. In "praw" mode it requires real OAuth credentials.
        """
        if self.reddit_mode == "praw":
            return bool(self.reddit_client_id and self.reddit_client_secret)
        return True

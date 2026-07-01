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


# Subreddits scanned via ApeWisdom (https://apewisdom.io) — free, no-auth,
# licensed third-party aggregation, no scraping or ToS conflict.
#
# wallstreetbets/pennystocks were the original ask. Shortsqueeze, SqueezePlays,
# SPACs and Daytrading were added after checking ApeWisdom's full tracked list
# (https://apewisdom.io/methodology/): short-squeeze and SPAC communities skew
# toward exactly the small/micro-cap, high-volatility profile this scanner
# targets, and Daytrading's top mentions overlapped with names already
# surfacing from wallstreetbets/pennystocks in testing. Deliberately excluded:
# stocks, investing, options, StockMarket, WallStreetbetsELITE,
# Wallstreetbetsnew — verified live and all are dominated by mega-cap mentions
# (MSFT/AAPL/AMZN/SPY), which would just dilute the small-cap signal.
DEFAULT_APEWISDOM_SUBREDDITS = [
    "wallstreetbets",
    "pennystocks",
    "Shortsqueeze",
    "SqueezePlays",
    "SPACs",
    "Daytrading",
]

# Subreddits ApeWisdom does NOT cover. Only reachable via REDDIT_MODE=praw
# (official Reddit OAuth) — direct RSS scraping was removed since it
# conflicted with Reddit's robots.txt.
DEFAULT_PRAW_ONLY_SUBREDDITS = [
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

    # "auto" (default): ApeWisdom only, no credentials needed. "praw":
    # official Reddit OAuth, covering every subreddit in `subreddits`
    # (including the ones ApeWisdom doesn't track) — requires
    # REDDIT_CLIENT_ID/SECRET and is the only fully ToS-compliant way to
    # reach those.
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
                ",".join(DEFAULT_APEWISDOM_SUBREDDITS + DEFAULT_PRAW_ONLY_SUBREDDITS),
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
    # How many posts per subreddit listing to pull (praw mode), and how far
    # back to count mentions for the "momentum" window (all modes).
    reddit_post_limit: int = field(
        default_factory=lambda: _get_int("REDDIT_POST_LIMIT", 200)
    )
    reddit_lookback_hours: int = field(
        default_factory=lambda: _get_int("REDDIT_LOOKBACK_HOURS", 72)
    )
    # Stage 3 (social -> FMP cross-reference): how many top social tickers,
    # ranked by mention growth, get an FMP quote lookup. Bounds API calls
    # since a 6-subreddit ApeWisdom scan can surface hundreds of tickers.
    social_fmp_limit: int = field(
        default_factory=lambda: _get_int("SOCIAL_FMP_LIMIT", 50)
    )
    # Skip known large/mega-caps (known_largecaps.py) before spending the
    # social_fmp_limit budget on names that would just get flagged
    # out-of-range anyway. Disable to see the raw social ranking unfiltered.
    filter_large_caps: bool = field(
        default_factory=lambda: os.getenv("FILTER_LARGE_CAPS", "true").lower()
        not in ("false", "0", "no")
    )
    extra_large_cap_exclusions: List[str] = field(
        default_factory=lambda: [
            s.strip().upper()
            for s in os.getenv("EXTRA_LARGE_CAP_EXCLUSIONS", "").split(",")
            if s.strip()
        ]
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
    def large_cap_blocklist(self):
        from .known_largecaps import KNOWN_LARGE_CAP_TICKERS

        return KNOWN_LARGE_CAP_TICKERS | set(self.extra_large_cap_exclusions)

    @property
    def has_reddit(self) -> bool:
        """Whether *some* social data source is usable.

        In "auto" mode this is always True — ApeWisdom needs no credentials.
        In "praw" mode it requires real OAuth credentials.
        """
        if self.reddit_mode == "praw":
            return bool(self.reddit_client_id and self.reddit_client_secret)
        return True

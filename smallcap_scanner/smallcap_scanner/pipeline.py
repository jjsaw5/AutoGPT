"""Orchestrate a full scan: universe -> enrich -> social -> rank."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set

from .config import Config
from .models import RedditSignal, ScoredCandidate, StockCandidate
from . import scoring

log = logging.getLogger(__name__)


def run_scan(
    cfg: Config,
    mock: bool = False,
    require_social: bool = False,
    top_n: Optional[int] = 25,
) -> List[ScoredCandidate]:
    """Return ranked candidates. ``mock=True`` uses bundled offline data."""
    if mock:
        from .mock_data import mock_stocks, MOCK_POSTS
        from .reddit_aggregate import aggregate_from_posts

        stocks = mock_stocks()
        known = set(stocks)
        reddit = aggregate_from_posts(
            MOCK_POSTS, known, cfg.reddit_lookback_hours, provider="mock"
        )
    else:
        stocks = _load_universe(cfg)
        known = set(stocks)
        reddit = _load_social(cfg, known)

    ranked = scoring.rank(stocks, reddit, cfg, require_social=require_social)
    return ranked[:top_n] if top_n else ranked


def _load_universe(cfg: Config) -> Dict[str, StockCandidate]:
    from .fmp_client import FMPClient

    client = FMPClient(cfg)
    candidates = client.screen()
    stocks = {c.symbol: c for c in candidates}
    if stocks:
        try:
            client.enrich_quotes(list(stocks.values()))
        except Exception as exc:  # enrichment is best-effort
            log.warning("quote enrichment failed: %s", exc)
    return stocks


def _load_social(
    cfg: Config, known: Set[str]
) -> Dict[str, RedditSignal]:
    if cfg.reddit_mode == "praw":
        if not cfg.has_reddit:
            log.warning(
                "REDDIT_MODE=praw but credentials are missing — running "
                "fundamentals/momentum only. Set REDDIT_CLIENT_ID/SECRET, or "
                "drop REDDIT_MODE to use the no-credential 'auto' mode."
            )
            return {}
        from .reddit_client import RedditScanner

        return RedditScanner(cfg).scan(known)

    # "auto" mode: ApeWisdom (clean, no-auth, limited coverage) + RSS
    # scraping (broader coverage, but outside Reddit's stated crawl policy —
    # see reddit_rss_client.py for the tradeoff this involves).
    from .apewisdom_client import ApeWisdomClient
    from .reddit_rss_client import RedditRSSClient
    from .reddit_aggregate import merge_signals

    signal_maps = []
    if cfg.apewisdom_subreddits:
        try:
            signal_maps.append(ApeWisdomClient(cfg).scan(known))
        except Exception as exc:
            log.warning("ApeWisdom scan failed: %s", exc)
    if cfg.reddit_rss_subreddits:
        try:
            signal_maps.append(RedditRSSClient(cfg).scan(known))
        except Exception as exc:
            log.warning("Reddit RSS scan failed: %s", exc)
    return merge_signals(*signal_maps) if signal_maps else {}


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

_COLUMNS = [
    ("symbol", "TICKER", 7),
    ("price", "PRICE", 8),
    ("composite", "SCORE", 7),
    ("fund_score", "FUND", 6),
    ("mom_score", "MOM", 6),
    ("social_score", "SOCIAL", 7),
    ("reddit_recent", "RDT", 5),
    ("vol_surge", "VOLx", 6),
    ("flags", "FLAGS", 40),
]


def format_table(ranked: List[ScoredCandidate]) -> str:
    header = "  ".join(f"{title:<{w}}" for _, title, w in _COLUMNS)
    lines = [header, "-" * len(header)]
    for c in ranked:
        row = c.to_row()
        cells = []
        for key, _, w in _COLUMNS:
            val = row.get(key)
            val = "" if val is None else str(val)
            cells.append(f"{val:<{w}}")
        lines.append("  ".join(cells))
    return "\n".join(lines)

"""Three independent, chainable scan stages.

1. scan_fundamentals — FMP screener + quotes only. "What does the market
   data say is a small-cap, optionable, grinding-up prospect?" No social
   input at all.
2. scan_social       — ApeWisdom (or PRAW) only. "What tickers are actually
   heating up on the tracked subreddits right now?" No FMP filtering — this
   can surface tickers stage 1 never saw (wrong price/cap band, or simply
   not in the screener's universe).
3. scan_combined     — takes a stage-2 result, looks up exactly those
   tickers via FMP, and re-scores them with the full fundamental + momentum
   + social blend. This is the "now that we know what's trending, what does
   the market data say about it" pass.

Each stage returns plain data (List[ScoredCandidate] or List[RedditSignal])
that the CLI can print, save to JSON, and/or feed into the next stage.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Dict, List, Optional

from .config import Config
from .models import RedditSignal, ScoredCandidate, StockCandidate
from . import scoring

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stage 1: FMP-only fundamentals/momentum scan
# ---------------------------------------------------------------------------

def scan_fundamentals(
    cfg: Config, mock: bool = False, top_n: Optional[int] = 25
) -> List[ScoredCandidate]:
    if mock:
        from .mock_data import mock_stocks

        stocks = mock_stocks()
    else:
        stocks = _load_universe(cfg)

    ranked = scoring.rank_fmp_only(stocks, cfg)
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


# ---------------------------------------------------------------------------
# Stage 2: raw social discovery (no FMP filtering)
# ---------------------------------------------------------------------------

def scan_social(
    cfg: Config, mock: bool = False, top_n: Optional[int] = None
) -> List[RedditSignal]:
    """Return tickers trending on the tracked subreddits, regardless of
    whether they'd pass the fundamental screen.

    Sorted by net-new mentions (the "heating up right now" signal) with total
    mentions as a tiebreaker.
    """
    if mock:
        from .mock_data import MOCK_POSTS
        from .reddit_aggregate import aggregate_from_posts

        signals = aggregate_from_posts(
            MOCK_POSTS, None, cfg.reddit_lookback_hours, provider="mock"
        )
    else:
        signals = _load_social_raw(cfg)

    ranked = sorted(
        signals.values(),
        key=lambda s: (s.mentions_recent, s.mentions_total),
        reverse=True,
    )
    return ranked[:top_n] if top_n else ranked


def _load_social_raw(cfg: Config) -> Dict[str, RedditSignal]:
    if cfg.reddit_mode == "praw":
        if not cfg.has_reddit:
            log.warning(
                "REDDIT_MODE=praw but credentials are missing — no social "
                "data available. Set REDDIT_CLIENT_ID/SECRET, or drop "
                "REDDIT_MODE to use the no-credential 'auto' mode."
            )
            return {}
        from .reddit_client import RedditScanner

        return RedditScanner(cfg).scan(known_symbols=None)

    from .apewisdom_client import ApeWisdomClient

    try:
        return ApeWisdomClient(cfg).scan(known_symbols=None)
    except Exception as exc:
        log.warning("ApeWisdom scan failed: %s", exc)
        return {}


def dump_social(signals: List[RedditSignal]) -> List[dict]:
    """Full-fidelity serialization for re-use as ``scan_combined``'s input
    (e.g. via a saved JSON file) — preserves every field, unlike the display
    row from ``format_social_table``."""
    return [dataclasses.asdict(s) for s in signals]


def load_social(rows: List[dict]) -> List[RedditSignal]:
    return [RedditSignal(**row) for row in rows]


# ---------------------------------------------------------------------------
# Stage 3: cross-reference a social list against FMP, full 3-way scoring
# ---------------------------------------------------------------------------

_OUT_OF_RANGE_FLAGS = {"OUTSIDE_PRICE_RANGE", "OUTSIDE_MARKET_CAP_RANGE"}


def filter_known_large_caps(
    signals: List[RedditSignal], cfg: Config
) -> List[RedditSignal]:
    """Drop tickers on the maintained large-cap blocklist before they consume
    the FMP lookup budget (see known_largecaps.py). ApeWisdom's raw rankings
    are dominated by the same handful of mega-caps every scan — without this,
    SOCIAL_FMP_LIMIT gets spent on names that would just get flagged
    out-of-range anyway, crowding out genuinely small-cap activity sitting
    further down the ranking.
    """
    if not cfg.filter_large_caps:
        return signals
    blocklist = cfg.large_cap_blocklist
    kept = [s for s in signals if s.symbol not in blocklist]
    skipped = len(signals) - len(kept)
    if skipped:
        log.info(
            "Skipped %d known large-cap ticker(s) before the FMP lookup "
            "(set FILTER_LARGE_CAPS=false to disable).",
            skipped,
        )
    return kept


def hide_out_of_range(ranked: List[ScoredCandidate]) -> List[ScoredCandidate]:
    """Drop candidates flagged outside the configured price/market-cap band.

    This is a display-time filter, not a data-loss one — it only runs in
    scan_combined and only when the caller hasn't asked to see everything
    (the social/fundamentals stages and any caller passing
    show_out_of_range=True still see the full picture).
    """
    return [c for c in ranked if not (_OUT_OF_RANGE_FLAGS & set(c.flags))]


def scan_combined(
    cfg: Config,
    social: Optional[List[RedditSignal]] = None,
    mock: bool = False,
    social_limit: Optional[int] = None,
    top_n: Optional[int] = 25,
    show_out_of_range: bool = False,
) -> List[ScoredCandidate]:
    """Look up the top social tickers via FMP and score with the full blend.

    If ``social`` isn't provided, runs a fresh ``scan_social`` first. Known
    large-caps are skipped before the FMP lookup (see
    ``filter_known_large_caps``), and by default the returned list excludes
    anything still flagged outside the configured price/cap band — pass
    ``show_out_of_range=True`` to see those too.
    """
    if social is None:
        social = scan_social(cfg, mock=mock)

    social = filter_known_large_caps(social, cfg)

    limit = social_limit if social_limit is not None else cfg.social_fmp_limit
    top_social = social[:limit]
    if len(social) > limit:
        log.info(
            "SOCIAL_FMP_LIMIT=%d — cross-referencing the top %d of %d trending "
            "tickers by mention growth.",
            limit, limit, len(social),
        )
    symbols = [s.symbol for s in top_social]

    if mock:
        from .mock_data import mock_quote_lookup

        stocks = mock_quote_lookup(symbols)
    else:
        stocks = _quote_symbols(cfg, symbols)

    reddit_map = {s.symbol: s for s in top_social}
    ranked = scoring.rank(stocks, reddit_map, cfg)

    if not show_out_of_range:
        before = len(ranked)
        ranked = hide_out_of_range(ranked)
        hidden = before - len(ranked)
        if hidden:
            log.info(
                "Hid %d ticker(s) outside the configured price/market-cap "
                "range from the combined output (use --show-out-of-range to "
                "see them).",
                hidden,
            )

    return ranked[:top_n] if top_n else ranked


def _quote_symbols(cfg: Config, symbols: List[str]) -> Dict[str, StockCandidate]:
    from .fmp_client import FMPClient

    if not symbols:
        return {}
    try:
        return FMPClient(cfg).quote_symbols(symbols)
    except Exception as exc:
        log.warning("FMP quote lookup failed: %s", exc)
        return {}


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


_SOCIAL_COLUMNS = [
    ("symbol", "TICKER", 7),
    ("mentions_total", "MENT", 6),
    ("mentions_recent", "NEW", 5),
    ("social_score", "SCORE", 6),
    ("unique_authors", "AUTH", 5),
    ("upvotes_sum", "UPVOTES", 8),
    ("subreddits", "SUBREDDITS", 30),
]


def format_social_table(signals: List[RedditSignal]) -> str:
    header = "  ".join(f"{title:<{w}}" for _, title, w in _SOCIAL_COLUMNS)
    lines = [header, "-" * len(header)]
    for sig in signals:
        row = sig.to_row()
        row["social_score"] = round(scoring.score_social(sig)[0], 1)
        cells = []
        for key, _, w in _SOCIAL_COLUMNS:
            val = row.get(key)
            val = "" if val is None else str(val)
            cells.append(f"{val:<{w}}")
        lines.append("  ".join(cells))
    return "\n".join(lines)

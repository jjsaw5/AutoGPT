"""Offline sample data so the pipeline runs end-to-end without API keys.

Lets you try the tool (`--mock`) and lets the test-suite exercise the full
ranking path deterministically. The SLS-like name here is illustrative only.
"""

from __future__ import annotations

from typing import Dict, List

from .models import StockCandidate

MOCK_STOCKS: List[StockCandidate] = [
    StockCandidate(
        symbol="SLS", name="SmallCo Labs", price=1.85, market_cap=120_000_000,
        volume=33_000_000, avg_volume=9_000_000, exchange="NASDAQ",
        sector="Healthcare", year_high=2.10, year_low=0.65,
        price_avg_50=1.40, price_avg_200=1.05, change_pct=8.2,
    ),
    StockCandidate(
        symbol="GRND", name="Grind Resources", price=2.40, market_cap=340_000_000,
        volume=4_500_000, avg_volume=2_100_000, exchange="NASDAQ",
        sector="Basic Materials", year_high=3.0, year_low=1.10,
        price_avg_50=2.05, price_avg_200=1.70, change_pct=3.1,
    ),
    StockCandidate(
        symbol="QTUM", name="Quantum Micro", price=4.10, market_cap=900_000_000,
        volume=1_200_000, avg_volume=1_300_000, exchange="NASDAQ",
        sector="Technology", year_high=6.5, year_low=3.8,
        price_avg_50=4.30, price_avg_200=4.90, change_pct=-1.4,
    ),
    StockCandidate(
        symbol="PMPD", name="Pumped Inc", price=0.78, market_cap=45_000_000,
        volume=22_000_000, avg_volume=800_000, exchange="NASDAQ",
        sector="Technology", year_high=0.95, year_low=0.20,
        price_avg_50=0.40, price_avg_200=0.35, change_pct=41.0,
    ),
    StockCandidate(
        symbol="STBL", name="Stable Boring Co", price=6.20, market_cap=1_500_000_000,
        volume=900_000, avg_volume=1_000_000, exchange="NYSE",
        sector="Utilities", year_high=7.0, year_low=5.8,
        price_avg_50=6.30, price_avg_200=6.25, change_pct=0.3,
    ),
]

# Reddit posts (title/selftext/author/score/created_utc/subreddit).
# created_utc is set very high so they always count as "recent".
_FUTURE = 9_999_999_999
MOCK_POSTS: List[dict] = [
    {"title": "$SLS is the play, 1.5 LEAPS calls printing",
     "selftext": "SLS grinding up for 6 months, volume exploding",
     "author": "diamondhands1", "score": 540, "created_utc": _FUTURE,
     "subreddit": "pennystocks"},
    {"title": "SLS DD - why this runs to $15",
     "selftext": "small float, catalyst soon", "author": "valueguy",
     "score": 210, "created_utc": _FUTURE, "subreddit": "smallstreetbets"},
    {"title": "Anyone else in SLS?", "selftext": "loading calls",
     "author": "newbie22", "score": 95, "created_utc": _FUTURE,
     "subreddit": "TheRaceTo10Million"},
    {"title": "GRND looking strong", "selftext": "$GRND breakout above 50d",
     "author": "charttrader", "score": 120, "created_utc": _FUTURE,
     "subreddit": "pennystocks"},
    # PMPD: one author spamming -> should trip the manipulation flag.
    {"title": "$PMPD TO THE MOON BUY NOW", "selftext": "PMPD 10x easy",
     "author": "spammer", "score": 5, "created_utc": _FUTURE,
     "subreddit": "pennystocks"},
    {"title": "PMPD next 1000% runner", "selftext": "$PMPD load up",
     "author": "spammer", "score": 3, "created_utc": _FUTURE,
     "subreddit": "pennystocks"},
    {"title": "PMPD is going parabolic", "selftext": "$PMPD dont miss",
     "author": "spammer", "score": 2, "created_utc": _FUTURE,
     "subreddit": "pennystocks"},
    {"title": "PMPD squeeze incoming", "selftext": "$PMPD",
     "author": "spammer", "score": 1, "created_utc": _FUTURE,
     "subreddit": "pennystocks"},
    # MOONX: mentioned a lot on social but never passed the FMP screen
    # (price/cap outside the configured band) — exercises the stage-3
    # "discovered via social, looked up directly via FMP quote" path.
    {"title": "$MOONX breaking out, huge runner today",
     "selftext": "everyone's talking about MOONX", "author": "trader1",
     "score": 300, "created_utc": _FUTURE, "subreddit": "wallstreetbets"},
    {"title": "MOONX DD - the next big short squeeze",
     "selftext": "$MOONX short interest is massive", "author": "trader2",
     "score": 180, "created_utc": _FUTURE, "subreddit": "Shortsqueeze"},
]

# Quote-lookup data for stage 3 (social -> FMP cross-reference) in mock mode,
# standing in for FMPClient.quote_symbols(). Covers every ticker mentioned in
# MOCK_POSTS, including MOONX which is deliberately absent from MOCK_STOCKS.
MOCK_QUOTES: Dict[str, StockCandidate] = {
    s.symbol: s for s in MOCK_STOCKS
}
MOCK_QUOTES["MOONX"] = StockCandidate(
    symbol="MOONX", name="Moonshot Co", price=42.50, market_cap=8_500_000_000,
    volume=15_000_000, avg_volume=15_000_000, exchange="NASDAQ",
    year_high=45.0, year_low=12.0, price_avg_50=30.0, price_avg_200=20.0,
    change_pct=12.0,
)


def mock_stocks() -> Dict[str, StockCandidate]:
    return {s.symbol: s for s in MOCK_STOCKS}


def mock_quote_lookup(symbols: List[str]) -> Dict[str, StockCandidate]:
    """Stand-in for FMPClient.quote_symbols() in --mock runs."""
    return {s: MOCK_QUOTES[s] for s in symbols if s in MOCK_QUOTES}

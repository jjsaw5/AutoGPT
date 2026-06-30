"""Plain data structures passed between pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class StockCandidate:
    """A stock that passed the fundamental/price screen, enriched with the
    momentum fields used downstream for scoring."""

    symbol: str
    name: str = ""
    price: float = 0.0
    market_cap: float = 0.0
    volume: float = 0.0
    avg_volume: float = 0.0
    exchange: str = ""
    sector: str = ""

    # Enrichment from the quote endpoint (optional — populated when available).
    year_high: Optional[float] = None
    year_low: Optional[float] = None
    price_avg_50: Optional[float] = None
    price_avg_200: Optional[float] = None
    change_pct: Optional[float] = None  # today's % change

    @property
    def pct_above_year_low(self) -> Optional[float]:
        if self.year_low and self.year_low > 0:
            return (self.price - self.year_low) / self.year_low * 100.0
        return None

    @property
    def pct_below_year_high(self) -> Optional[float]:
        if self.year_high and self.year_high > 0:
            return (self.year_high - self.price) / self.year_high * 100.0
        return None

    @property
    def volume_surge(self) -> Optional[float]:
        """Today's volume as a multiple of average daily volume."""
        if self.avg_volume and self.avg_volume > 0:
            return self.volume / self.avg_volume
        return None


@dataclass
class RedditSignal:
    """Aggregated mentions of a single ticker across the tracked subreddits."""

    symbol: str
    mentions_total: int = 0
    mentions_recent: int = 0  # within the lookback window
    unique_authors: int = 0
    upvotes_sum: int = 0
    subreddits: List[str] = field(default_factory=list)
    sample_titles: List[str] = field(default_factory=list)

    @property
    def author_diversity(self) -> float:
        """Unique authors / total mentions. Low values (one person posting a
        ticker many times) are a coordinated-pump red flag, not a green light."""
        if self.mentions_total <= 0:
            return 0.0
        return self.unique_authors / self.mentions_total


@dataclass
class ScoredCandidate:
    symbol: str
    stock: StockCandidate
    reddit: Optional[RedditSignal] = None

    fundamental_score: float = 0.0
    momentum_score: float = 0.0
    social_score: float = 0.0
    composite_score: float = 0.0

    # Human-readable reasons + warnings that explain the score.
    reasons: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)

    def to_row(self) -> Dict[str, object]:
        s = self.stock
        r = self.reddit
        return {
            "symbol": self.symbol,
            "name": s.name,
            "price": round(s.price, 2),
            "market_cap_m": round(s.market_cap / 1e6, 1) if s.market_cap else None,
            "vol_surge": round(s.volume_surge, 2) if s.volume_surge else None,
            "pct_above_low": round(s.pct_above_year_low, 1)
            if s.pct_above_year_low is not None
            else None,
            "reddit_mentions": r.mentions_total if r else 0,
            "reddit_recent": r.mentions_recent if r else 0,
            "reddit_authors": r.unique_authors if r else 0,
            "fund_score": round(self.fundamental_score, 1),
            "mom_score": round(self.momentum_score, 1),
            "social_score": round(self.social_score, 1),
            "composite": round(self.composite_score, 1),
            "flags": ";".join(self.flags),
        }

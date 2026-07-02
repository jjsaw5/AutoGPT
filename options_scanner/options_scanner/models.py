"""Domain models for the Options Opportunity Scanner.

These are plain dataclasses / enums shared across the pipeline stages so each
stage speaks the same language: a raw :class:`Candidate` flows through thesis
construction, gates, scoring, structure selection and ranking, accumulating a
:class:`Thesis`, :class:`GateReport`, :class:`Score`, and :class:`Structure`
until it becomes a fully-evaluated :class:`EvaluatedCandidate`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CapTier(str, Enum):
    MEGA = "MEGA"    # > $200B
    LARGE = "LARGE"  # $10-200B
    MID = "MID"      # $2-10B
    SMALL = "SMALL"  # $300M-2B
    MICRO = "MICRO"  # < $300M (manual override only)

    @classmethod
    def from_market_cap(cls, market_cap: float | None) -> "CapTier | None":
        if market_cap is None:
            return None
        if market_cap > 200e9:
            return cls.MEGA
        if market_cap >= 10e9:
            return cls.LARGE
        if market_cap >= 2e9:
            return cls.MID
        if market_cap >= 300e6:
            return cls.SMALL
        return cls.MICRO


class Tier(str, Enum):
    A = "A"  # core watch, scanned every cycle
    B = "B"  # opportunistic feed-driven pull-in


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class VolRegime(str, Enum):
    CHEAP = "cheap"
    FAIR = "fair"
    RICH = "rich"


class Horizon(str, Enum):
    INTRADAY = "intraday"   # 0DTE
    SWING = "swing"         # 1-10d
    POSITION = "position"   # 2-8wk
    LEAPS = "leaps"         # > 6mo


class Catalyst(str, Enum):
    EARNINGS = "earnings"
    NEWS = "news"
    FDA = "fda"
    MACRO = "macro"
    TECHNICAL = "technical"
    FLOW_ONLY = "flow_only"


class Decision(str, Enum):
    GO = "GO"
    WATCH = "WATCH"
    PASS = "PASS"


class StructureType(str, Enum):
    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    LEAPS = "leaps"
    DEBIT_VERTICAL = "debit_vertical"
    CREDIT_VERTICAL = "credit_vertical"
    IRON_CONDOR = "iron_condor"
    ZERO_DTE_SPREAD = "0dte_defined_risk_spread"
    NONE = "none"


@dataclass
class Candidate:
    """A ticker pulled into the scan, plus the raw signal snapshot for it."""

    ticker: str
    tier: Tier
    cap_tier: CapTier | None = None
    market_cap: float | None = None
    sector: str | None = None
    price: float | None = None
    source_feeds: list[str] = field(default_factory=list)
    # Raw signal snapshot keyed by signal name (populated by data clients).
    signals: dict[str, Any] = field(default_factory=dict)


@dataclass
class Thesis:
    """Structured thesis assembled per candidate before scoring (§4)."""

    direction: Direction
    conviction: float               # 0-1
    vol_regime: VolRegime           # decides buy vs sell premium
    horizon: Horizon
    catalyst: Catalyst
    days_to_catalyst: int | None = None
    # Distance to the next scheduled earnings date, independent of the chosen
    # catalyst tag. A long-premium trade can hold *through* earnings even when
    # earnings isn't its thesis (drives gate G4).
    days_to_earnings: int | None = None
    implied_move: float | None = None   # ATM straddle-implied, fraction of spot
    expected_move: float | None = None  # thesis expected move, fraction of spot
    iv_rank: float | None = None        # 0-100
    iv: float | None = None             # current implied vol
    rv: float | None = None             # realized vol
    supporting_signals: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def is_earnings_play(self) -> bool:
        return self.catalyst == Catalyst.EARNINGS

    def regime_iv_vs_rv(self) -> float | None:
        """0-100 where higher = IV cheap vs RV (favors buying premium).

        50 = IV≈RV; >50 = IV below RV (buyer's edge); <50 = IV rich vs RV.
        Returns ``None`` when either leg of the comparison is missing.
        """
        if not self.iv or not self.rv:
            return None
        ratio = (self.rv - self.iv) / self.rv
        return max(0.0, min(100.0, 50.0 + ratio * 100.0))


@dataclass
class GateResult:
    gate_id: str
    passed: bool
    detail: str = ""


@dataclass
class GateReport:
    results: list[GateResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failures(self) -> list[GateResult]:
        return [r for r in self.results if not r.passed]

    def flags(self) -> str:
        """Compact gate flag string for the readout, e.g. "G1 G2 ✓" / "G4✗"."""
        return " ".join(
            f"{r.gate_id}{'✓' if r.passed else '✗'}" for r in self.results
        )


@dataclass
class Score:
    p1: float = 0.0  # Volatility Edge
    p2: float = 0.0  # Directional Signal
    p3: float = 0.0  # Expected Value
    p4: float = 0.0  # Catalyst Quality
    p5: float = 0.0  # Liquidity/Execution
    p6: float = 0.0  # Corroboration
    composite: float = 0.0
    pop: float = 0.0            # probability of profit (predicted)
    expected_value: float = 0.0

    def pillars(self) -> dict[str, float]:
        return {
            "P1": self.p1, "P2": self.p2, "P3": self.p3,
            "P4": self.p4, "P5": self.p5, "P6": self.p6,
        }


@dataclass
class Leg:
    action: str          # "buy" | "sell"
    option_type: str     # "call" | "put"
    strike: float
    expiry: str          # ISO date

    def __str__(self) -> str:
        sign = "+" if self.action == "buy" else "-"
        return f"{sign}{self.option_type[0].upper()}{self.strike:g}@{self.expiry}"


@dataclass
class Structure:
    structure_type: StructureType
    legs: list[Leg] = field(default_factory=list)
    max_profit: float | None = None
    max_loss: float | None = None       # defined risk (positive $)
    breakevens: list[float] = field(default_factory=list)
    rationale: str = ""
    is_defined_risk: bool = True
    is_speculative: bool = False

    def legs_str(self) -> str:
        return " ".join(str(leg) for leg in self.legs) if self.legs else "—"


@dataclass
class EvaluatedCandidate:
    candidate: Candidate
    thesis: Thesis
    structure: Structure
    score: Score
    gates: GateReport
    decision: Decision = Decision.PASS
    suggested_size: float = 0.0      # $ risk allocated
    size_tier: str = "none"          # "standard" | "high_conviction" | "none"
    why: str = ""                    # one-line "why this trade"
    biggest_risk: str = ""

    @property
    def ticker(self) -> str:
        return self.candidate.ticker

    @property
    def rank_key(self) -> float:
        return self.score.composite

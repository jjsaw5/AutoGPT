"""Shared data structures.

Both data sources (FMP for regular-hours history, Robinhood for premarket
and live quotes) normalise into these types so the signal engine never has
to know which provider a bar came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Session(str, Enum):
    PRE = "pre"
    REGULAR = "reg"
    POST = "post"


@dataclass(frozen=True)
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    session: Session = Session.REGULAR


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float
    prev_close: float
    change_pct: float
    volume: float = 0.0
    day_high: float | None = None
    day_low: float | None = None


class Regime(str, Enum):
    STRONG_BULL = "STRONG_BULL"
    BULL = "BULL"
    NEUTRAL = "NEUTRAL"
    BEAR = "BEAR"
    STRONG_BEAR = "STRONG_BEAR"

    @property
    def direction(self) -> int:
        if self in (Regime.STRONG_BULL, Regime.BULL):
            return 1
        if self in (Regime.STRONG_BEAR, Regime.BEAR):
            return -1
        return 0


class Decision(str, Enum):
    LONG_CALL = "LONG_CALL"
    LONG_PUT = "LONG_PUT"
    NO_TRADE = "NO_TRADE"


@dataclass(frozen=True)
class Gate:
    """One pass/fail check with the reasoning kept attached.

    The engine is deliberately verbose about *why* it stood aside; a
    no-trade with no explanation is impossible to review after the close.
    """

    name: str
    passed: bool
    detail: str
    direction: int = 0


@dataclass
class RegimeScore:
    regime: Regime
    score: float
    sector_rs: float
    breadth: float
    qqq_rs: float
    detail: str = ""


@dataclass
class Levels:
    premarket_high: float | None = None
    premarket_low: float | None = None
    opening_range_high: float | None = None
    opening_range_low: float | None = None
    ema_fast: float | None = None
    ema_slow: float | None = None
    sma_daily: float | None = None
    vwap: float | None = None
    atr: float | None = None
    price: float | None = None


@dataclass
class TradePlan:
    """The mechanical part of the trade, fixed before entry."""

    direction: int
    entry_reference: float
    invalidation: float
    profit_target_pct: float
    stop_loss_pct: float
    time_stop_minutes: int
    flat_by: str
    risk_dollars: float
    notes: list[str] = field(default_factory=list)


@dataclass
class Signal:
    symbol: str
    asof: datetime
    decision: Decision
    conviction: int
    regime: RegimeScore
    levels: Levels
    gates: list[Gate] = field(default_factory=list)
    plan: TradePlan | None = None
    uw_detail: str | None = None
    uw_bias: float = 0.0

    @property
    def blocking_gates(self) -> list[Gate]:
        return [g for g in self.gates if not g.passed]

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "asof": self.asof.isoformat(),
            "decision": self.decision.value,
            "conviction": self.conviction,
            "regime": {
                "regime": self.regime.regime.value,
                "score": round(self.regime.score, 3),
                "sector_rs": round(self.regime.sector_rs, 3),
                "breadth": round(self.regime.breadth, 3),
                "qqq_rs": round(self.regime.qqq_rs, 3),
                "detail": self.regime.detail,
            },
            "levels": {
                k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in vars(self.levels).items()
            },
            "gates": [
                {"name": g.name, "passed": g.passed, "detail": g.detail}
                for g in self.gates
            ],
            "unusual_whales": {
                "bias": round(self.uw_bias, 3),
                "detail": self.uw_detail,
            },
            "plan": (
                {
                    "direction": self.plan.direction,
                    "entry_reference": round(self.plan.entry_reference, 4),
                    "invalidation": round(self.plan.invalidation, 4),
                    "profit_target_pct": self.plan.profit_target_pct,
                    "stop_loss_pct": self.plan.stop_loss_pct,
                    "time_stop_minutes": self.plan.time_stop_minutes,
                    "flat_by": self.plan.flat_by,
                    "risk_dollars": self.plan.risk_dollars,
                    "notes": self.plan.notes,
                }
                if self.plan
                else None
            ),
        }


@dataclass(frozen=True)
class OptionContract:
    symbol: str
    expiration: str
    strike: float
    option_type: str
    bid: float
    ask: float
    delta: float | None = None
    open_interest: int = 0
    volume: int = 0
    instrument_id: str | None = None

    @property
    def mid(self) -> float:
        if self.bid <= 0 or self.ask <= 0:
            return max(self.bid, self.ask)
        return (self.bid + self.ask) / 2

    @property
    def spread_pct(self) -> float:
        mid = self.mid
        if mid <= 0:
            return 1.0
        return (self.ask - self.bid) / mid

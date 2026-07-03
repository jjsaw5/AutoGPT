"""Domain models shared by strategists, data providers, and API routes.

All monetary figures are in the underlying's quote currency (assumed USD).
Options contracts follow the US equity convention of 100 shares per contract.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

CONTRACT_MULTIPLIER: int = 100


class OptionRight(str, Enum):
    CALL = "C"
    PUT = "P"


class OptionContract(BaseModel):
    """A single listed option contract snapshot."""

    symbol: str
    underlying: str
    expiry: date
    strike: float = Field(gt=0)
    right: OptionRight
    bid: float = Field(ge=0)
    ask: float = Field(ge=0)
    last: float | None = None
    volume: int = Field(default=0, ge=0)
    open_interest: int = Field(default=0, ge=0)
    implied_vol: float | None = Field(default=None, ge=0)
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    as_of: datetime

    @property
    def mid(self) -> float:
        if self.bid <= 0 and self.ask <= 0:
            return self.last or 0.0
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return max(self.ask - self.bid, 0.0)


class OptionChain(BaseModel):
    """An option chain for one underlying at one point in time."""

    underlying: str
    spot: float = Field(gt=0)
    as_of: datetime
    risk_free_rate: float = Field(default=0.045, ge=0)
    contracts: list[OptionContract]

    def by_expiry(self, expiry: date) -> list[OptionContract]:
        return [c for c in self.contracts if c.expiry == expiry]

    def expiries(self) -> list[date]:
        return sorted({c.expiry for c in self.contracts})


class TradeLeg(BaseModel):
    """One leg of a multi-leg structure. Quantity is signed (+ long / - short)."""

    contract: OptionContract
    quantity: int

    @field_validator("quantity")
    @classmethod
    def _nonzero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("leg quantity must be non-zero")
        return v

    @property
    def is_long(self) -> bool:
        return self.quantity > 0


class StopLoss(BaseModel):
    """An explicit hard stop. Required for Phase-3 0DTE entries."""

    price_trigger: float | None = Field(default=None, gt=0, description="Underlying level that triggers the stop.")
    dollar_loss: float = Field(gt=0, description="Dollar loss at which the trade must be closed.")
    kind: Literal["underlying_level", "dollar_loss"] = "dollar_loss"


class TradeSetup(BaseModel):
    """A fully-specified multi-leg idea ready for sizing and review."""

    ticker: str
    strategy: str
    thesis: str
    legs: list[TradeLeg]
    net_credit: float
    max_profit: float
    max_loss: float
    max_theoretical_loss: float | None = Field(
        default=None,
        description=(
            "Ceiling on catastrophic loss for undefined-risk structures. "
            "The high-volume module requires this to be surfaced on entry."
        ),
    )
    breakevens: list[float]
    pop: float | None = Field(default=None, ge=0, le=1)
    expected_value: float | None = None
    iv_rank: float | None = Field(default=None, ge=0, le=100)
    iv_percentile: float | None = Field(default=None, ge=0, le=100)
    dte: int = Field(ge=0)
    stop_loss: StopLoss | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def reward_risk(self) -> float:
        if self.max_loss <= 0:
            return float("inf")
        return self.max_profit / self.max_loss


class Account(BaseModel):
    """A paper-trading account used for sizing decisions."""

    cash: float = Field(gt=0)
    kelly_fraction: float = Field(default=0.25, ge=0, le=1)
    max_pct_per_trade: float = Field(default=0.05, ge=0, le=1)
    max_total_deployed_pct: float = Field(default=0.5, ge=0, le=1)


class PositionSize(BaseModel):
    """Sizing recommendation for a TradeSetup."""

    contracts: int = Field(ge=0)
    capital_at_risk: float = Field(ge=0)
    pct_of_account: float = Field(ge=0)
    rationale: str


class MarketSnapshot(BaseModel):
    """Minimal market state used for position management decisions."""

    ticker: str
    spot: float
    as_of: datetime
    chain: OptionChain | None = None


class Position(BaseModel):
    """A live (paper) position built from a TradeSetup."""

    setup: TradeSetup
    size: PositionSize
    opened_at: datetime
    current_pnl: float = 0.0


class ManagementVerdict(str, Enum):
    HOLD = "hold"
    CLOSE_WINNER = "close_winner"
    CLOSE_TIME = "close_time"
    ROLL = "roll"
    ADJUST = "adjust"


class ManagementAction(BaseModel):
    verdict: ManagementVerdict
    reason: str
    suggested_action: str | None = None


class Candidate(BaseModel):
    """A ticker that passed a strategist's screen."""

    ticker: str
    reason: str
    score: float = 0.0


class JournalOutcome(str, Enum):
    OPEN = "open"
    WIN = "win"
    LOSS = "loss"
    SCRATCH = "scratch"


class JournalEntry(BaseModel):
    """One paper-trade record. Source of truth for Phase-3 analytics."""

    id: int | None = None
    ticker: str
    strategy: str
    strategist: str
    thesis: str
    opened_at: datetime
    closed_at: datetime | None = None
    contracts: int = Field(ge=0)
    entry_credit: float = Field(description="Net credit (+) or debit (−) per spread at entry.")
    exit_credit: float | None = Field(
        default=None,
        description="Net credit/debit per spread at exit. None while open.",
    )
    max_loss: float = Field(ge=0, description="Defined-risk max loss per spread at entry.")
    outcome: JournalOutcome = JournalOutcome.OPEN
    realized_pnl: float = 0.0
    planned_size_contracts: int | None = Field(
        default=None,
        description="Kelly-implied size at entry — analytics compares this against actual.",
    )
    notes: str = ""
    setup_snapshot: TradeSetup | None = Field(
        default=None,
        description=(
            "Frozen TradeSetup at entry. Persisted as JSON by TradeJournal so the "
            "Phase-5 risk dashboard can recompute Greeks and exposures on open positions."
        ),
    )

    @property
    def r_multiple(self) -> float | None:
        """Realised P/L expressed as a multiple of initial risk per spread.

        Risk = max_loss × contracts × 100. Returns None while the trade is open.
        """
        if self.outcome is JournalOutcome.OPEN:
            return None
        risk_dollars = self.max_loss * self.contracts * CONTRACT_MULTIPLIER
        if risk_dollars <= 0:
            return None
        return self.realized_pnl / risk_dollars


TradeSide = Literal["long", "short", "neutral", "directional_bullish", "directional_bearish"]

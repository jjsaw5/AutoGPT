"""Dataclasses and enums shared across the Vol Desk rule engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional, Union


class SetupClassification(str, Enum):
    """Outcome of running the five entry filters against a gamma screen row."""

    CONFIRMED = "CONFIRMED"
    PENDING = "PENDING"
    BLOCKED = "BLOCKED"


class PositionStatus(str, Enum):
    """Lifecycle state of a tracked position in the ledger."""

    CONFIRMED = "CONFIRMED"
    WATCH = "WATCH"
    CLOSED = "CLOSED"


class ExitUrgency(str, Enum):
    """How quickly an exit should be acted on."""

    NEXT_OPEN = "next_open"
    IMMEDIATE = "immediate"
    REVISIT = "revisit"


@dataclass
class GammaScreenRow:
    """One row of the vendor's nightly gamma screen export."""

    symbol: str
    spot: float
    dealer_delta_balance: float  # "db", typically 0-1
    db_change: float  # change in db from the prior session
    grade: int  # 0-11
    p_trans: float  # pTrans
    n_trans: float  # nTrans
    plus_gex: float  # +GEX / T1 target
    cotmp: float  # Center Of Put Mass
    grade_11_deep: bool = False
    db_prior_2_sessions: Optional[float] = None  # db value two sessions ago
    minervini_score: Optional[float] = None
    oi_depth: Optional[float] = None
    zero_gex: Optional[float] = None
    plus_gex_next: Optional[float] = None  # T2 candidate
    cotmc: Optional[float] = None  # Center Of Call Mass, T2 candidate
    spike_crash_pattern: bool = False


@dataclass
class FilterResult:
    """Result of a single entry filter, with a human-readable reason."""

    name: str
    passed: bool
    reason: str


@dataclass
class SetupEvaluation:
    """Aggregate result of running all entry filters against one symbol."""

    symbol: str
    classification: SetupClassification
    filters: list[FilterResult] = field(default_factory=list)
    risk_reward: Optional[float] = None
    cotmp_cushion_pct: Optional[float] = None


@dataclass
class RegimeGateResult:
    """Result of evaluating the macro/regime gates for the trading day."""

    basket_gate: bool
    bull_bear_gate: bool
    vix_delta_gate: bool
    gates_passed: int  # 0-3
    track1_mechanical_allowed: bool  # gates_passed >= 2
    b_continuation_allowed: bool  # gates_passed == 3
    hyg_divergence_warning: bool
    # Suggested, not enforced, sizing haircut -- caller decides whether to apply it.
    sizing_multiplier: float = 1.0


@dataclass
class Position:
    """A tracked, live swing position managed by the ledger."""

    symbol: str
    entry_price: float
    entry_date: date
    p_trans: float
    n_trans: float
    t1_target: float  # plus_gex
    t2_target: Optional[float] = None
    t1_hit: bool = False
    stop_locked_to_entry: bool = False
    status: PositionStatus = PositionStatus.CONFIRMED
    daily_closes: list[tuple[date, float]] = field(default_factory=list)
    close_reason: Optional[str] = None


@dataclass
class ExitDecision:
    """Recommendation returned by evaluate_exits."""

    should_exit: bool
    reason: Optional[str] = None
    exit_urgency: Optional[Union[ExitUrgency, str]] = None
    new_status: Optional[PositionStatus] = None

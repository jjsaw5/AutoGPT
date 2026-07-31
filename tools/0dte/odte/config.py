"""Strategy tunables for the 0DTE SPY/QQQ process.

Every number that encodes a trading opinion lives here so the rules can be
audited and changed in one place, rather than being scattered as literals
through the signal engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("America/New_York")

# The tech complex used to score the regime. XLK is the sector proxy; the
# mega caps carry enough index weight that their agreement (or lack of it)
# is what actually moves SPY and QQQ intraday.
TECH_SECTOR_PROXY = "XLK"
TECH_MEGACAPS: tuple[str, ...] = (
    "NVDA",
    "MSFT",
    "AAPL",
    "AVGO",
    "META",
    "GOOGL",
    "AMZN",
    "TSLA",
)


@dataclass(frozen=True)
class RegimeConfig:
    """Thresholds for turning tech strength into a tradeable regime."""

    sector_rs_weight: float = 0.35
    breadth_weight: float = 0.40
    qqq_rs_weight: float = 0.25

    # Relative strength is measured in percentage points of day change versus
    # SPY. Half a point of intraday divergence is a meaningful tech tilt.
    rs_saturation_pct: float = 0.50

    strong_threshold: float = 0.50
    directional_threshold: float = 0.20


@dataclass(frozen=True)
class TrendConfig:
    """Moving-average structure required before a direction is considered."""

    fast_ema: int = 9
    slow_ema: int = 21
    daily_sma: int = 200
    intraday_interval: str = "5min"

    # Price must clear the fast EMA by this fraction of the day's ATR before
    # the stack counts as trending. Keeps the engine out of EMA-hugging chop.
    ema_clearance_atr_frac: float = 0.10
    atr_period: int = 14


@dataclass(frozen=True)
class LevelConfig:
    """Premarket and opening-range level handling."""

    premarket_start: time = time(4, 0)
    premarket_end: time = time(9, 30)
    opening_range_minutes: int = 15

    # A break only counts once price closes this far beyond the level, in
    # fractions of ATR. Stops one-tick pokes from arming a trade.
    break_buffer_atr_frac: float = 0.05


@dataclass(frozen=True)
class TimingConfig:
    """When the process is allowed to open a position.

    0DTE gamma makes the first few minutes and the final half hour behave
    very differently from the rest of the session, and the midday window is
    where trend strategies bleed. Entries are confined to the two windows
    where intraday trend actually persists.
    """

    no_entry_before: time = time(9, 40)
    morning_window_end: time = time(11, 30)
    afternoon_window_start: time = time(13, 30)
    no_entry_after: time = time(15, 0)
    hard_flat_by: time = time(15, 30)

    # Robinhood force-liquidates 0DTE contracts 30 minutes before expiry
    # (chain field `sellout_time_to_expiration`). Never be discovering that
    # at 15:45 -- hard_flat_by sits comfortably ahead of it.
    skip_midday_chop: bool = True


@dataclass(frozen=True)
class RiskConfig:
    """Position sizing and the stop-trading rules.

    These exist to answer the exact problem in the thread that prompted
    this: sizing up is what turns a working process into a drawdown. Size
    is derived from a fixed dollar risk, never from conviction.
    """

    account_size: float = 25_000.0
    risk_per_trade_pct: float = 0.01
    max_contracts: int = 10
    max_trades_per_day: int = 3
    max_losses_per_day: int = 2
    daily_loss_limit_pct: float = 0.02

    # Premium-based exits. 0DTE decays too fast for wide stops to be useful.
    profit_target_pct: float = 0.30
    stop_loss_pct: float = 0.25
    trail_after_pct: float = 0.20
    time_stop_minutes: int = 25


@dataclass(frozen=True)
class ContractConfig:
    """Filters for picking the actual 0DTE contract."""

    target_delta: float = 0.40
    min_delta: float = 0.30
    max_delta: float = 0.50
    max_spread_pct: float = 0.06
    min_open_interest: int = 250
    min_volume: int = 100
    max_premium: float = 5.00


@dataclass(frozen=True)
class StrategyConfig:
    symbols: tuple[str, ...] = ("SPY", "QQQ")
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    trend: TrendConfig = field(default_factory=TrendConfig)
    levels: LevelConfig = field(default_factory=LevelConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    contract: ContractConfig = field(default_factory=ContractConfig)

    def risk_dollars(self) -> float:
        return self.risk.account_size * self.risk.risk_per_trade_pct


DEFAULT_CONFIG = StrategyConfig()

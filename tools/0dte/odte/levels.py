"""Session level construction.

Premarket high/low is the reference the thread's process leans on, and it
is the one level FMP cannot supply -- its intraday feed starts at 09:30.
These helpers therefore expect premarket bars from the broker adapter and
regular-hours bars from either source.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from .config import LevelConfig, TrendConfig
from .indicators import atr, closes, ema, sma, vwap
from .models import Bar, Levels, Session


def _same_day(bars: Sequence[Bar], day: date) -> list[Bar]:
    return [b for b in bars if b.ts.date() == day]


def premarket_levels(
    bars: Sequence[Bar],
    day: date,
    config: LevelConfig | None = None,
) -> tuple[float | None, float | None]:
    """High and low of the premarket session for `day`.

    Uses the broker's session tag when present and falls back to a clock
    window, so a feed that omits the tag still produces usable levels.
    """
    config = config or LevelConfig()
    candidates = [
        b
        for b in _same_day(bars, day)
        if b.session == Session.PRE
        or (config.premarket_start <= b.ts.time() < config.premarket_end)
    ]
    if not candidates:
        return None, None
    return max(b.high for b in candidates), min(b.low for b in candidates)


def opening_range(
    bars: Sequence[Bar],
    day: date,
    config: LevelConfig | None = None,
) -> tuple[float | None, float | None]:
    config = config or LevelConfig()
    regular = [
        b
        for b in _same_day(bars, day)
        if b.session == Session.REGULAR and b.ts.time() >= config.premarket_end
    ]
    if not regular:
        return None, None
    open_ts = regular[0].ts
    cutoff = open_ts + timedelta(minutes=config.opening_range_minutes)
    window = [b for b in regular if b.ts < cutoff]
    if not window:
        return None, None
    return max(b.high for b in window), min(b.low for b in window)


def build_levels(
    intraday_bars: Sequence[Bar],
    daily_bars: Sequence[Bar],
    day: date,
    price: float,
    premarket_bars: Sequence[Bar] | None = None,
    trend_config: TrendConfig | None = None,
    level_config: LevelConfig | None = None,
) -> Levels:
    """Assemble every level the gates need.

    `intraday_bars` should be the regular-hours series for `day`.
    `premarket_bars` may be the same list when the broker feed already
    carries pre-session bars; duplicates are harmless because premarket and
    regular bars are separated by session tag and clock time.
    """
    trend_config = trend_config or TrendConfig()
    level_config = level_config or LevelConfig()

    pm_source = (
        list(premarket_bars) if premarket_bars is not None else list(intraday_bars)
    )
    pmh, pml = premarket_levels(pm_source, day, level_config)
    orh, orl = opening_range(intraday_bars, day, level_config)

    regular = [b for b in _same_day(intraday_bars, day) if b.session == Session.REGULAR]
    intraday_closes = closes(regular)

    return Levels(
        premarket_high=pmh,
        premarket_low=pml,
        opening_range_high=orh,
        opening_range_low=orl,
        ema_fast=ema(intraday_closes, trend_config.fast_ema),
        ema_slow=ema(intraday_closes, trend_config.slow_ema),
        sma_daily=sma(closes(daily_bars), trend_config.daily_sma),
        vwap=vwap(regular),
        atr=atr(regular, trend_config.atr_period),
        price=price,
    )

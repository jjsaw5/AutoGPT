"""The decision engine.

Every gate must pass in the same direction before a trade exists. The gates
are evaluated in full even after one fails, so the output always explains
the whole picture rather than short-circuiting on the first objection --
that is what makes an end-of-day review possible.

Order of reasoning:

  1. timing       is this a window where intraday trend actually persists?
  2. risk_budget  is there still room in today's trade and loss allowance?
  3. data         do we have the levels the rules depend on?
  4. regime       is tech giving a direction, or is it the neutral chop day?
  5. trend        does the 9/21 EMA stack agree with that direction?
  6. level        has price actually cleared the premarket level, with a buffer?

Only then is a plan produced, and the plan's size comes from fixed dollar
risk -- never from how good the setup feels.
"""

from __future__ import annotations

from datetime import datetime

from .config import DEFAULT_CONFIG, StrategyConfig
from .models import (
    Decision,
    Gate,
    Levels,
    Regime,
    RegimeScore,
    Signal,
    TradePlan,
)
from .uw import UWContext


def evaluate(
    symbol: str,
    now: datetime,
    levels: Levels,
    regime: RegimeScore,
    config: StrategyConfig | None = None,
    uw: UWContext | None = None,
    trades_taken_today: int = 0,
    losses_today: int = 0,
) -> Signal:
    config = config or DEFAULT_CONFIG
    gates: list[Gate] = [
        _timing_gate(now, config),
        _risk_budget_gate(trades_taken_today, losses_today, config),
        _data_gate(levels),
        _regime_gate(regime, config),
    ]

    direction = regime.regime.direction
    gates.append(_trend_gate(levels, direction, config))
    gates.append(_level_gate(levels, direction, config))

    passed = all(g.passed for g in gates)
    decision = Decision.NO_TRADE
    if passed and direction != 0:
        decision = Decision.LONG_CALL if direction > 0 else Decision.LONG_PUT

    conviction = _conviction(levels, regime, gates, uw, config)
    plan = (
        _build_plan(levels, direction, config)
        if decision is not Decision.NO_TRADE
        else None
    )

    return Signal(
        symbol=symbol,
        asof=now,
        decision=decision,
        conviction=conviction if decision is not Decision.NO_TRADE else 0,
        regime=regime,
        levels=levels,
        gates=gates,
        plan=plan,
        uw_detail=uw.detail if uw is not None else None,
        uw_bias=uw.bias if uw is not None else 0.0,
    )


def _timing_gate(now: datetime, config: StrategyConfig) -> Gate:
    timing = config.timing
    clock = now.time()

    if clock < timing.no_entry_before:
        return Gate(
            "timing",
            False,
            f"{clock:%H:%M} is before {timing.no_entry_before:%H:%M}; "
            "the opening rotation has not resolved",
        )
    if clock >= timing.no_entry_after:
        return Gate(
            "timing",
            False,
            f"{clock:%H:%M} is past {timing.no_entry_after:%H:%M}; "
            f"no new 0DTE risk, be flat by {timing.hard_flat_by:%H:%M}",
        )
    if (
        timing.skip_midday_chop
        and timing.morning_window_end <= clock < timing.afternoon_window_start
    ):
        return Gate(
            "timing",
            False,
            f"{clock:%H:%M} is in the midday window "
            f"({timing.morning_window_end:%H:%M}-"
            f"{timing.afternoon_window_start:%H:%M}); trend persistence is worst here",
        )
    return Gate("timing", True, f"{clock:%H:%M} is inside an entry window")


def _risk_budget_gate(trades_taken: int, losses: int, config: StrategyConfig) -> Gate:
    risk = config.risk
    if trades_taken >= risk.max_trades_per_day:
        return Gate(
            "risk_budget",
            False,
            f"{trades_taken} trades already taken (max {risk.max_trades_per_day})",
        )
    if losses >= risk.max_losses_per_day:
        return Gate(
            "risk_budget",
            False,
            f"{losses} losses today (max {risk.max_losses_per_day}); done for the day",
        )
    return Gate(
        "risk_budget",
        True,
        f"{trades_taken}/{risk.max_trades_per_day} trades, "
        f"{losses}/{risk.max_losses_per_day} losses used",
    )


def _data_gate(levels: Levels) -> Gate:
    missing = [
        name
        for name in ("price", "ema_fast", "ema_slow", "atr")
        if getattr(levels, name) is None
    ]
    if levels.premarket_high is None or levels.premarket_low is None:
        missing.append("premarket_high/low")
    if missing:
        return Gate(
            "data",
            False,
            "missing inputs: " + ", ".join(missing),
        )
    return Gate("data", True, "all required levels present")


def _regime_gate(regime: RegimeScore, config: StrategyConfig) -> Gate:
    if regime.regime is Regime.NEUTRAL:
        return Gate(
            "regime",
            False,
            f"tech is neutral (score {regime.score:+.2f}, "
            f"needs |score| >= {config.regime.directional_threshold}); "
            "this is the day to stand aside",
        )
    return Gate("regime", True, regime.detail, direction=regime.regime.direction)


def _trend_gate(levels: Levels, direction: int, config: StrategyConfig) -> Gate:
    if direction == 0:
        return Gate("trend", False, "no directional bias to confirm")
    if None in (levels.price, levels.ema_fast, levels.ema_slow, levels.atr):
        return Gate("trend", False, "insufficient intraday history for the EMA stack")

    price = levels.price
    fast = levels.ema_fast
    slow = levels.ema_slow
    clearance = levels.atr * config.trend.ema_clearance_atr_frac

    if direction > 0:
        threshold = fast + clearance
        stacked = price > threshold and fast > slow
        label = f"price {price:.2f} > EMA9 {fast:.2f} > EMA21 {slow:.2f}"
        reason = (
            f"price {price:.2f} needs to be above {threshold:.2f} "
            f"(EMA9 {fast:.2f} + {clearance:.2f} clearance)"
            if price <= threshold
            else f"EMA9 {fast:.2f} is not above EMA21 {slow:.2f}"
        )
    else:
        threshold = fast - clearance
        stacked = price < threshold and fast < slow
        label = f"price {price:.2f} < EMA9 {fast:.2f} < EMA21 {slow:.2f}"
        reason = (
            f"price {price:.2f} needs to be below {threshold:.2f} "
            f"(EMA9 {fast:.2f} - {clearance:.2f} clearance)"
            if price >= threshold
            else f"EMA9 {fast:.2f} is not below EMA21 {slow:.2f}"
        )

    if not stacked:
        return Gate("trend", False, f"EMA stack does not confirm: {reason}")

    note = label
    if levels.sma_daily is not None:
        above = price > levels.sma_daily
        agrees = above if direction > 0 else not above
        note += (
            f"; {'with' if agrees else 'against'} the 200SMA "
            f"({levels.sma_daily:.2f})"
        )
    return Gate("trend", True, note, direction=direction)


def _level_gate(levels: Levels, direction: int, config: StrategyConfig) -> Gate:
    if direction == 0:
        return Gate("level", False, "no directional bias to confirm")
    if levels.price is None or levels.atr is None:
        return Gate("level", False, "missing price or ATR")

    buffer = levels.atr * config.levels.break_buffer_atr_frac
    price = levels.price

    if direction > 0:
        level = levels.premarket_high
        if level is None:
            return Gate("level", False, "no premarket high available")
        if price <= level + buffer:
            return Gate(
                "level",
                False,
                f"price {price:.2f} has not cleared premarket high "
                f"{level:.2f} (+{buffer:.2f} buffer)",
            )
        return Gate(
            "level",
            True,
            f"price {price:.2f} is above premarket high {level:.2f}",
            direction=1,
        )

    level = levels.premarket_low
    if level is None:
        return Gate("level", False, "no premarket low available")
    if price >= level - buffer:
        return Gate(
            "level",
            False,
            f"price {price:.2f} has not broken premarket low "
            f"{level:.2f} (-{buffer:.2f} buffer)",
        )
    return Gate(
        "level",
        True,
        f"price {price:.2f} is below premarket low {level:.2f}",
        direction=-1,
    )


def _conviction(
    levels: Levels,
    regime: RegimeScore,
    gates: list[Gate],
    uw: UWContext | None,
    config: StrategyConfig,
) -> int:
    if not all(g.passed for g in gates):
        return 0

    direction = regime.regime.direction
    score = 40 + min(35, abs(regime.score) * 60)

    if levels.vwap is not None and levels.price is not None:
        above_vwap = levels.price > levels.vwap
        if above_vwap == (direction > 0):
            score += 8

    if levels.sma_daily is not None and levels.price is not None:
        above_sma = levels.price > levels.sma_daily
        if above_sma == (direction > 0):
            score += 7

    if uw is not None and uw.available:
        score += uw.bias * direction * 10

    return int(max(0, min(100, round(score))))


def _build_plan(levels: Levels, direction: int, config: StrategyConfig) -> TradePlan:
    risk = config.risk
    price = levels.price or 0.0
    broken_level = (
        levels.premarket_high if direction > 0 else levels.premarket_low
    ) or price

    # Invalidation is a reclaim of the level that was broken, or the fast
    # EMA if that sits tighter -- whichever the underlying reaches first.
    if direction > 0:
        invalidation = max(broken_level, levels.ema_fast or broken_level)
    else:
        invalidation = min(broken_level, levels.ema_fast or broken_level)

    notes = [
        f"Underlying invalidation: a 5-minute close back through {invalidation:.2f}.",
        f"Premium stop {risk.stop_loss_pct:.0%}, target {risk.profit_target_pct:.0%}, "
        f"time stop {risk.time_stop_minutes} min.",
        f"Trail after +{risk.trail_after_pct:.0%} rather than holding for a runner.",
        f"Flat by {config.timing.hard_flat_by:%H:%M} regardless of P&L; the broker "
        "force-closes 0DTE 30 minutes before expiry.",
    ]

    return TradePlan(
        direction=direction,
        entry_reference=price,
        invalidation=invalidation,
        profit_target_pct=risk.profit_target_pct,
        stop_loss_pct=risk.stop_loss_pct,
        time_stop_minutes=risk.time_stop_minutes,
        flat_by=f"{config.timing.hard_flat_by:%H:%M}",
        risk_dollars=config.risk_dollars(),
        notes=notes,
    )

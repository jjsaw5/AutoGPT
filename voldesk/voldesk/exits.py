"""Position management: stop framework and take-profit recommendations."""

from __future__ import annotations

from datetime import date

from .models import ExitDecision, ExitUrgency, Position, PositionStatus

STOP2_DRAWDOWN_PCT = 0.90
TIME_STOP_DAYS = 7
TIME_STOP_PROGRESS_MIN = 0.5
STALL_LOOKBACK_SESSIONS = 3
STALL_PROGRESS_MAX = 0.10


def evaluate_exits(
    position: Position,
    current_price: float,
    current_date: date,
    closed_below_n_trans: bool,
) -> ExitDecision:
    """Apply the four stop rules in priority order; if none trigger, report the
    passive hold/watch status implied by price relative to pTrans/nTrans."""

    # Stop 1: close below nTrans -- exit at next open.
    if closed_below_n_trans:
        return ExitDecision(
            should_exit=True,
            reason="closed below nTrans",
            exit_urgency=ExitUrgency.NEXT_OPEN,
        )

    # Stop 2: hard drawdown stop, exit immediately.
    if current_price <= position.entry_price * STOP2_DRAWDOWN_PCT and current_price < position.p_trans:
        return ExitDecision(
            should_exit=True,
            reason="price <= 90% of entry and below pTrans",
            exit_urgency=ExitUrgency.IMMEDIATE,
        )

    # Stop 3: time stop -- insufficient progress toward T1 after 7 days.
    days_held = (current_date - position.entry_date).days
    if days_held >= TIME_STOP_DAYS:
        if position.t1_target > position.entry_price:
            progress = (current_price - position.entry_price) / (
                position.t1_target - position.entry_price
            )
        else:
            progress = 0.0
        if progress < TIME_STOP_PROGRESS_MIN:
            return ExitDecision(
                should_exit=True,
                reason=(
                    f"time stop: {days_held} days held, "
                    f"progress={progress:.2f} < {TIME_STOP_PROGRESS_MIN:.2f} toward T1"
                ),
                exit_urgency=ExitUrgency.REVISIT,
            )

    # Stop 4: stalling -- day-over-day progress toward T1 below 10% for 3 sessions.
    # INTERPRETATION: "progress" here is the day-over-day price move expressed as a
    # fraction of the total distance to T1 (close_i - close_{i-1}) / (T1 - entry),
    # not an absolute price-move threshold -- the spec text is ambiguous between
    # the two readings.
    closes = [c for c in position.daily_closes if c[0] <= current_date]
    closes.sort(key=lambda c: c[0])
    if len(closes) >= STALL_LOOKBACK_SESSIONS + 1 and position.t1_target > position.entry_price:
        recent = closes[-(STALL_LOOKBACK_SESSIONS + 1):]
        daily_progress = [
            (recent[i][1] - recent[i - 1][1]) / (position.t1_target - position.entry_price)
            for i in range(1, len(recent))
        ]
        if all(p < STALL_PROGRESS_MAX for p in daily_progress):
            return ExitDecision(
                should_exit=True,
                reason=(
                    f"stalling: day-over-day progress toward T1 below "
                    f"{STALL_PROGRESS_MAX:.0%} for {STALL_LOOKBACK_SESSIONS} consecutive sessions"
                ),
                exit_urgency=ExitUrgency.REVISIT,
            )

    # No stop triggered -- report passive hold/watch state.
    if current_price >= position.p_trans:
        return ExitDecision(should_exit=False, new_status=PositionStatus.CONFIRMED)
    elif current_price > position.n_trans:
        return ExitDecision(should_exit=False, new_status=PositionStatus.WATCH)

    return ExitDecision(should_exit=False)


def evaluate_take_profit(position: Position, current_price: float) -> dict:
    """Report whether T1 has been reached, without mutating the position. The
    caller decides whether to bank the gain or lock the stop and ride to T2."""
    t1_reached = current_price >= position.t1_target and not position.t1_hit

    result = {
        "t1_reached": t1_reached,
        "t1_target": position.t1_target,
        "t2_target": position.t2_target,
        "stop_locked_to_entry": position.stop_locked_to_entry,
    }

    if t1_reached:
        result["choices"] = [
            "exit and bank the gain at T1",
            "lock stop to entry (stop_locked_to_entry=True) before riding to T2",
        ]
        result["note"] = (
            "T2 must not be pursued unless stop_locked_to_entry is True"
        )

    return result

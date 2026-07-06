"""Exit engine — per-structure plans and completeness."""

from __future__ import annotations

from options_scanner.exits import build_exit_plan
from options_scanner.models import (
    Catalyst, Direction, Horizon, Leg, Structure, StructureType, Thesis, VolRegime,
)


def _thesis(**kw):
    base = dict(direction=Direction.BULLISH, conviction=0.6, vol_regime=VolRegime.CHEAP,
                horizon=Horizon.SWING, catalyst=Catalyst.FLOW_ONLY)
    base.update(kw)
    return Thesis(**base)


def _struct(st, max_profit=600.0, max_loss=300.0):
    return Structure(structure_type=st, legs=[Leg("buy", "call", 100, "x")],
                     max_profit=max_profit, max_loss=max_loss, breakevens=[103.0])


def test_long_plan_complete():
    p = build_exit_plan(_struct(StructureType.LONG_CALL), _thesis())
    assert p is not None and p.is_complete()
    assert p.profit_target_value == 300.0  # 50% of max profit
    assert p.stop_loss_value == 120.0      # 40% of risk
    assert p.time_stop_days is not None
    assert "breakeven" in p.invalidation


def test_credit_plan_has_delta_stop():
    p = build_exit_plan(_struct(StructureType.CREDIT_VERTICAL, 175.0, 325.0), _thesis())
    assert p.is_complete()
    assert p.short_delta_stop == 0.35
    assert p.profit_target_value == round(0.5 * 175.0, 2)


def test_pre_earnings_exit_flag():
    # earnings in the hold window, not an earnings play → exit before it
    t = _thesis(catalyst=Catalyst.FLOW_ONLY, days_to_earnings=4)
    p = build_exit_plan(_struct(StructureType.DEBIT_VERTICAL), t)
    assert p.pre_earnings_exit is True


def test_no_plan_for_no_trade():
    assert build_exit_plan(_struct(StructureType.NONE, None, None), _thesis()) is None


def test_zerodte_plan_hard_stops():
    p = build_exit_plan(_struct(StructureType.ZERO_DTE_SPREAD), _thesis(horizon=Horizon.INTRADAY))
    assert p.is_complete()
    assert p.time_stop_days == 0
    assert "no averaging" in p.invalidation

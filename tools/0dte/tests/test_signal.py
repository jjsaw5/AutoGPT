from datetime import datetime

import pytest

from odte.config import MARKET_TZ, DEFAULT_CONFIG
from odte.models import Decision, Levels, Regime, RegimeScore
from odte.signal import evaluate


def at(hour, minute):
    return datetime(2026, 7, 31, hour, minute, tzinfo=MARKET_TZ)


def bullish_levels(**overrides):
    base = dict(
        premarket_high=738.0,
        premarket_low=730.0,
        ema_fast=739.0,
        ema_slow=737.0,
        sma_daily=700.0,
        vwap=738.0,
        atr=2.0,
        price=741.0,
    )
    base.update(overrides)
    return Levels(**base)


def bearish_levels(**overrides):
    base = dict(
        premarket_high=738.0,
        premarket_low=730.0,
        ema_fast=731.0,
        ema_slow=733.0,
        sma_daily=760.0,
        vwap=732.0,
        atr=2.0,
        price=728.0,
    )
    base.update(overrides)
    return Levels(**base)


def regime(kind, score):
    return RegimeScore(
        regime=kind, score=score, sector_rs=0, breadth=0, qqq_rs=0, detail=kind.value
    )


BULL = regime(Regime.STRONG_BULL, 0.6)
BEAR = regime(Regime.STRONG_BEAR, -0.6)
NEUTRAL = regime(Regime.NEUTRAL, 0.05)


def gate(signal, name):
    return next(g for g in signal.gates if g.name == name)


def test_aligned_bull_setup_produces_a_call_with_a_plan():
    signal = evaluate("SPY", at(10, 0), bullish_levels(), BULL, DEFAULT_CONFIG)
    assert signal.decision is Decision.LONG_CALL
    assert signal.plan is not None
    assert signal.conviction > 0
    assert all(g.passed for g in signal.gates)


def test_aligned_bear_setup_produces_a_put():
    signal = evaluate("QQQ", at(10, 0), bearish_levels(), BEAR, DEFAULT_CONFIG)
    assert signal.decision is Decision.LONG_PUT
    assert signal.plan.direction == -1


def test_neutral_tech_stands_aside_even_with_perfect_price_structure():
    signal = evaluate("SPY", at(10, 0), bullish_levels(), NEUTRAL, DEFAULT_CONFIG)
    assert signal.decision is Decision.NO_TRADE
    assert not gate(signal, "regime").passed
    assert signal.plan is None
    assert signal.conviction == 0


def test_price_still_inside_the_premarket_range_is_rejected():
    signal = evaluate(
        "SPY",
        at(10, 0),
        bullish_levels(price=737.0, ema_fast=735.0, ema_slow=734.0),
        BULL,
        DEFAULT_CONFIG,
    )
    assert signal.decision is Decision.NO_TRADE
    assert not gate(signal, "level").passed


def test_marginal_poke_through_the_level_does_not_count():
    """Price 0.05 over the premarket high, inside the ATR buffer."""
    signal = evaluate(
        "SPY", at(10, 0), bullish_levels(price=738.05), BULL, DEFAULT_CONFIG
    )
    assert not gate(signal, "level").passed


def test_ema_stack_against_the_regime_is_rejected():
    signal = evaluate(
        "SPY",
        at(10, 0),
        bullish_levels(ema_fast=742.0, ema_slow=743.0),
        BULL,
        DEFAULT_CONFIG,
    )
    assert signal.decision is Decision.NO_TRADE
    assert not gate(signal, "trend").passed


@pytest.mark.parametrize("hour,minute", [(9, 35), (12, 0), (15, 15)])
def test_entries_are_confined_to_the_trend_windows(hour, minute):
    signal = evaluate("SPY", at(hour, minute), bullish_levels(), BULL, DEFAULT_CONFIG)
    assert signal.decision is Decision.NO_TRADE
    assert not gate(signal, "timing").passed


@pytest.mark.parametrize("hour,minute", [(9, 45), (11, 0), (14, 0), (14, 55)])
def test_valid_windows_are_accepted(hour, minute):
    signal = evaluate("SPY", at(hour, minute), bullish_levels(), BULL, DEFAULT_CONFIG)
    assert gate(signal, "timing").passed


def test_missing_premarket_levels_block_the_trade():
    signal = evaluate(
        "SPY",
        at(10, 0),
        bullish_levels(premarket_high=None, premarket_low=None),
        BULL,
        DEFAULT_CONFIG,
    )
    assert signal.decision is Decision.NO_TRADE
    assert not gate(signal, "data").passed
    assert "premarket" in gate(signal, "data").detail


def test_daily_trade_cap_stops_further_entries():
    signal = evaluate(
        "SPY", at(10, 0), bullish_levels(), BULL, DEFAULT_CONFIG, trades_taken_today=3
    )
    assert signal.decision is Decision.NO_TRADE
    assert not gate(signal, "risk_budget").passed


def test_two_losses_ends_the_day():
    signal = evaluate(
        "SPY", at(10, 0), bullish_levels(), BULL, DEFAULT_CONFIG, losses_today=2
    )
    assert signal.decision is Decision.NO_TRADE
    assert "done for the day" in gate(signal, "risk_budget").detail


def test_all_gates_are_reported_even_after_one_fails():
    signal = evaluate("SPY", at(12, 0), bullish_levels(), NEUTRAL, DEFAULT_CONFIG)
    assert {g.name for g in signal.gates} == {
        "timing",
        "risk_budget",
        "data",
        "regime",
        "trend",
        "level",
    }
    assert len(signal.blocking_gates) >= 2


def test_plan_invalidation_sits_below_price_for_a_long():
    signal = evaluate("SPY", at(10, 0), bullish_levels(), BULL, DEFAULT_CONFIG)
    assert signal.plan.invalidation < signal.plan.entry_reference
    assert signal.plan.risk_dollars == pytest.approx(250.0)


def test_plan_invalidation_sits_above_price_for_a_short():
    signal = evaluate("QQQ", at(10, 0), bearish_levels(), BEAR, DEFAULT_CONFIG)
    assert signal.plan.invalidation > signal.plan.entry_reference


def test_signal_serialises_to_json_safe_dict():
    signal = evaluate("SPY", at(10, 0), bullish_levels(), BULL, DEFAULT_CONFIG)
    payload = signal.to_dict()
    assert payload["decision"] == "LONG_CALL"
    assert payload["plan"]["flat_by"] == "15:30"
    import json

    json.dumps(payload)

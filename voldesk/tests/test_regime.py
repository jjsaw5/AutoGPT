"""Tests for the regime gate evaluation."""

from __future__ import annotations

from voldesk.regime import evaluate_regime


def test_all_gates_pass():
    result = evaluate_regime(
        spy_change_pct=1.0,
        qqq_change_pct=1.0,
        bull_count=10,
        bear_count=1,
        vix_dealer_delta=-5.0,
        hyg_bearish=False,
        basket_bullish_or_bull_bear_confirms=True,
    )
    assert result.basket_gate is True
    assert result.bull_bear_gate is True
    assert result.vix_delta_gate is True
    assert result.gates_passed == 3
    assert result.track1_mechanical_allowed is True
    assert result.b_continuation_allowed is True


def test_basket_gate_requires_spy_or_qqq_above_half_percent():
    result = evaluate_regime(
        spy_change_pct=0.4,
        qqq_change_pct=0.3,
        bull_count=10,
        bear_count=1,
        vix_dealer_delta=-1.0,
        hyg_bearish=False,
        basket_bullish_or_bull_bear_confirms=False,
    )
    assert result.basket_gate is False


def test_basket_gate_qqq_alone_can_pass():
    result = evaluate_regime(
        spy_change_pct=0.1,
        qqq_change_pct=0.6,
        bull_count=10,
        bear_count=1,
        vix_dealer_delta=-1.0,
        hyg_bearish=False,
        basket_bullish_or_bull_bear_confirms=False,
    )
    assert result.basket_gate is True


def test_bull_bear_gate_ratio_threshold():
    result_pass = evaluate_regime(
        spy_change_pct=0.0,
        qqq_change_pct=0.0,
        bull_count=31,
        bear_count=10,
        vix_dealer_delta=1.0,
        hyg_bearish=False,
        basket_bullish_or_bull_bear_confirms=False,
    )
    assert result_pass.bull_bear_gate is True  # 3.1 > 3.0

    result_fail = evaluate_regime(
        spy_change_pct=0.0,
        qqq_change_pct=0.0,
        bull_count=30,
        bear_count=10,
        vix_dealer_delta=1.0,
        hyg_bearish=False,
        basket_bullish_or_bull_bear_confirms=False,
    )
    assert result_fail.bull_bear_gate is False  # 3.0 is not > 3.0


def test_bull_bear_gate_defaults_true_when_no_bears():
    result = evaluate_regime(
        spy_change_pct=0.0,
        qqq_change_pct=0.0,
        bull_count=5,
        bear_count=0,
        vix_dealer_delta=1.0,
        hyg_bearish=False,
        basket_bullish_or_bull_bear_confirms=False,
    )
    assert result.bull_bear_gate is True


def test_vix_delta_gate_requires_negative():
    result = evaluate_regime(
        spy_change_pct=0.0,
        qqq_change_pct=0.0,
        bull_count=5,
        bear_count=1,
        vix_dealer_delta=0.0,
        hyg_bearish=False,
        basket_bullish_or_bull_bear_confirms=False,
    )
    assert result.vix_delta_gate is False


def test_two_gates_allows_track1_but_not_b_continuation():
    result = evaluate_regime(
        spy_change_pct=1.0,
        qqq_change_pct=1.0,
        bull_count=10,
        bear_count=1,
        vix_dealer_delta=1.0,  # fails vix gate
        hyg_bearish=False,
        basket_bullish_or_bull_bear_confirms=False,
    )
    assert result.gates_passed == 2
    assert result.track1_mechanical_allowed is True
    assert result.b_continuation_allowed is False


def test_fewer_than_two_gates_blocks_track1():
    result = evaluate_regime(
        spy_change_pct=0.0,
        qqq_change_pct=0.0,
        bull_count=1,
        bear_count=1,
        vix_dealer_delta=1.0,
        hyg_bearish=False,
        basket_bullish_or_bull_bear_confirms=False,
    )
    assert result.gates_passed == 0
    assert result.track1_mechanical_allowed is False
    assert result.b_continuation_allowed is False


def test_hyg_divergence_warning_and_sizing_haircut():
    result = evaluate_regime(
        spy_change_pct=1.0,
        qqq_change_pct=1.0,
        bull_count=10,
        bear_count=1,
        vix_dealer_delta=-1.0,
        hyg_bearish=True,
        basket_bullish_or_bull_bear_confirms=True,
    )
    assert result.hyg_divergence_warning is True
    assert result.sizing_multiplier == 0.5


def test_no_hyg_divergence_when_not_bearish():
    result = evaluate_regime(
        spy_change_pct=1.0,
        qqq_change_pct=1.0,
        bull_count=10,
        bear_count=1,
        vix_dealer_delta=-1.0,
        hyg_bearish=False,
        basket_bullish_or_bull_bear_confirms=True,
    )
    assert result.hyg_divergence_warning is False
    assert result.sizing_multiplier == 1.0


def test_no_hyg_divergence_when_basket_not_confirming():
    result = evaluate_regime(
        spy_change_pct=1.0,
        qqq_change_pct=1.0,
        bull_count=10,
        bear_count=1,
        vix_dealer_delta=-1.0,
        hyg_bearish=True,
        basket_bullish_or_bull_bear_confirms=False,
    )
    assert result.hyg_divergence_warning is False
    assert result.sizing_multiplier == 1.0

"""Macro/regime gate evaluation: basket, breadth, and VIX dealer positioning."""

from __future__ import annotations

from .models import RegimeGateResult

BASKET_CHANGE_THRESHOLD = 0.5  # percent
BULL_BEAR_RATIO_THRESHOLD = 3.0
HYG_DIVERGENCE_SIZING_MULTIPLIER = 0.5


def evaluate_regime(
    spy_change_pct: float,
    qqq_change_pct: float,
    bull_count: int,
    bear_count: int,
    vix_dealer_delta: float,
    hyg_bearish: bool,
    basket_bullish_or_bull_bear_confirms: bool,
) -> RegimeGateResult:
    """Evaluate the three regime gates and derive the resulting trade permissions."""
    basket_gate = spy_change_pct > BASKET_CHANGE_THRESHOLD or qqq_change_pct > BASKET_CHANGE_THRESHOLD
    bull_bear_gate = (
        (bull_count / bear_count) > BULL_BEAR_RATIO_THRESHOLD if bear_count > 0 else True
    )
    vix_delta_gate = vix_dealer_delta < 0

    gates_passed = sum([basket_gate, bull_bear_gate, vix_delta_gate])
    track1_mechanical_allowed = gates_passed >= 2
    b_continuation_allowed = gates_passed == 3

    hyg_divergence_warning = hyg_bearish and basket_bullish_or_bull_bear_confirms
    # Suggested, not enforced, sizing haircut -- the caller decides whether to apply it.
    sizing_multiplier = (
        HYG_DIVERGENCE_SIZING_MULTIPLIER if hyg_divergence_warning else 1.0
    )

    return RegimeGateResult(
        basket_gate=basket_gate,
        bull_bear_gate=bull_bear_gate,
        vix_delta_gate=vix_delta_gate,
        gates_passed=gates_passed,
        track1_mechanical_allowed=track1_mechanical_allowed,
        b_continuation_allowed=b_continuation_allowed,
        hyg_divergence_warning=hyg_divergence_warning,
        sizing_multiplier=sizing_multiplier,
    )

"""BSM sanity checks. Values cross-referenced with Hull Table 15.2."""
from __future__ import annotations

import math

import pytest

from app.core.bsm import delta, implied_vol, pop_between, price, prob_touch, vega
from app.core.models import OptionRight


def test_call_put_parity_at_atm() -> None:
    spot = 100.0
    strike = 100.0
    t = 0.5
    r = 0.05
    sigma = 0.2
    c = price(spot, strike, t, r, sigma, OptionRight.CALL)
    p = price(spot, strike, t, r, sigma, OptionRight.PUT)
    # C - P = S - K*e^(-rT)
    assert c - p == pytest.approx(spot - strike * math.exp(-r * t), abs=1e-6)


def test_atm_call_delta_is_near_half() -> None:
    d = delta(100.0, 100.0, 0.25, 0.05, 0.25, OptionRight.CALL)
    assert 0.45 < d < 0.6


def test_vega_positive() -> None:
    v = vega(100.0, 100.0, 0.25, 0.05, 0.25)
    assert v > 0


def test_implied_vol_round_trip() -> None:
    target = price(100.0, 100.0, 0.5, 0.05, 0.3, OptionRight.CALL)
    iv = implied_vol(target, 100.0, 100.0, 0.5, 0.05, OptionRight.CALL)
    assert iv is not None and iv == pytest.approx(0.3, abs=1e-3)


def test_implied_vol_returns_none_for_sub_intrinsic() -> None:
    # Market price well below intrinsic is impossible under BSM.
    iv = implied_vol(0.01, 100.0, 50.0, 0.5, 0.05, OptionRight.CALL)
    assert iv is None


def test_pop_between_bounds_are_zero_and_one() -> None:
    # Full real line -> 1.0 by construction.
    assert pop_between(1e-9, 1e9, 100.0, 0.5, 0.25) == pytest.approx(1.0, abs=1e-3)
    # Reversed bounds -> 0.
    assert pop_between(120.0, 80.0, 100.0, 0.5, 0.25) == 0.0


def test_prob_touch_bounded() -> None:
    # Touching a barrier 20% away in 45 DTE at 30% vol should be a real but <1 probability.
    pt_up = prob_touch(120.0, 100.0, 45 / 365.0, 0.30)
    pt_down = prob_touch(80.0, 100.0, 45 / 365.0, 0.30)
    assert 0.0 < pt_up < 1.0
    assert 0.0 < pt_down < 1.0

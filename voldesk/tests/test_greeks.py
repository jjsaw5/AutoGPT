"""Property-based tests for voldesk.greeks.black_scholes_greeks.

Deliberately does not assert against hand-computed reference numbers for
delta/gamma/vanna/charm (too easy to transcribe a formula error into both
the implementation and a "reference" value). Instead these assert the
mathematical properties any correct Black-Scholes implementation must
satisfy.
"""

from __future__ import annotations

import math

from voldesk.greeks import black_scholes_greeks


class TestGammaSymmetry:
    def test_gamma_identical_for_call_and_put(self):
        call = black_scholes_greeks(100, 100, 30, 0.30, "call")
        put = black_scholes_greeks(100, 100, 30, 0.30, "put")
        assert math.isclose(call.gamma, put.gamma, rel_tol=1e-9)

    def test_gamma_identical_across_moneyness(self):
        for strike in (80, 90, 100, 110, 120):
            call = black_scholes_greeks(100, strike, 45, 0.25, "call")
            put = black_scholes_greeks(100, strike, 45, 0.25, "put")
            assert math.isclose(call.gamma, put.gamma, rel_tol=1e-9)


class TestGammaShape:
    def test_gamma_positive(self):
        for strike in (50, 80, 100, 120, 150):
            g = black_scholes_greeks(100, strike, 30, 0.30, "call")
            assert g.gamma > 0

    def test_deep_otm_gamma_near_zero(self):
        near_atm = black_scholes_greeks(100, 100, 30, 0.20, "call")
        deep_otm_call = black_scholes_greeks(100, 300, 30, 0.20, "call")
        deep_otm_put = black_scholes_greeks(100, 20, 30, 0.20, "put")
        assert deep_otm_call.gamma < near_atm.gamma * 0.01
        assert deep_otm_put.gamma < near_atm.gamma * 0.01

    def test_atm_gamma_exceeds_far_otm_and_itm(self):
        atm = black_scholes_greeks(100, 100, 30, 0.25, "call")
        far_otm = black_scholes_greeks(100, 160, 30, 0.25, "call")
        far_itm = black_scholes_greeks(100, 40, 30, 0.25, "call")
        assert atm.gamma > far_otm.gamma
        assert atm.gamma > far_itm.gamma

    def test_gamma_peaks_near_atm(self):
        strikes = list(range(60, 141, 5))
        gammas = {
            k: black_scholes_greeks(100, k, 30, 0.25, "call").gamma for k in strikes
        }
        peak_strike = max(gammas, key=lambda k: gammas[k])
        # Peak should land close to spot (100), well inside the wings.
        assert abs(peak_strike - 100) <= 10


class TestDeltaBounds:
    def test_call_delta_in_zero_one(self):
        for strike in (50, 80, 100, 120, 200):
            g = black_scholes_greeks(100, strike, 30, 0.30, "call")
            assert 0.0 < g.delta < 1.0

    def test_put_delta_in_neg_one_zero(self):
        for strike in (50, 80, 100, 120, 200):
            g = black_scholes_greeks(100, strike, 30, 0.30, "put")
            assert -1.0 < g.delta < 0.0

    def test_deep_itm_call_delta_near_one(self):
        g = black_scholes_greeks(100, 20, 30, 0.20, "call")
        assert g.delta > 0.95

    def test_deep_itm_put_delta_near_neg_one(self):
        g = black_scholes_greeks(100, 300, 30, 0.20, "put")
        assert g.delta < -0.95


class TestPutCallParityOnDelta:
    def test_delta_parity_no_dividend(self):
        # delta_call - delta_put == e^(-qT); with q=0 that's exactly 1.0.
        for strike in (60, 80, 100, 120, 160):
            call = black_scholes_greeks(100, strike, 60, 0.35, "call", dividend_yield=0.0)
            put = black_scholes_greeks(100, strike, 60, 0.35, "put", dividend_yield=0.0)
            assert math.isclose(call.delta - put.delta, 1.0, abs_tol=1e-9)

    def test_delta_parity_with_dividend(self):
        q = 0.02
        t_years = 90 / 365.0
        expected = math.exp(-q * t_years)
        for strike in (70, 100, 130):
            call = black_scholes_greeks(100, strike, 90, 0.30, "call", dividend_yield=q)
            put = black_scholes_greeks(100, strike, 90, 0.30, "put", dividend_yield=q)
            assert math.isclose(call.delta - put.delta, expected, abs_tol=1e-9)


class TestVanna:
    def test_vanna_identical_for_call_and_put(self):
        call = black_scholes_greeks(100, 105, 45, 0.28, "call")
        put = black_scholes_greeks(100, 105, 45, 0.28, "put")
        assert math.isclose(call.vanna, put.vanna, rel_tol=1e-9)

    def test_vanna_near_zero_deep_itm_and_otm(self):
        atm = black_scholes_greeks(100, 100, 30, 0.25, "call")
        deep = black_scholes_greeks(100, 250, 30, 0.25, "call")
        assert abs(deep.vanna) < abs(atm.vanna)


class TestCharm:
    def test_charm_finite_and_differs_by_type(self):
        call = black_scholes_greeks(100, 100, 30, 0.25, "call", dividend_yield=0.02)
        put = black_scholes_greeks(100, 100, 30, 0.25, "put", dividend_yield=0.02)
        assert math.isfinite(call.charm)
        assert math.isfinite(put.charm)
        # With a nonzero dividend yield the call/put charm terms diverge.
        assert not math.isclose(call.charm, put.charm, rel_tol=1e-9)

    def test_charm_equal_when_no_dividend(self):
        # The only place call/put charm differ is the +/- q*N(+/-d1) term;
        # with q=0 that term vanishes and charm should match exactly.
        call = black_scholes_greeks(100, 100, 30, 0.25, "call", dividend_yield=0.0)
        put = black_scholes_greeks(100, 100, 30, 0.25, "put", dividend_yield=0.0)
        assert math.isclose(call.charm, put.charm, rel_tol=1e-9)


class TestExpiryEdgeCase:
    def test_zero_days_to_expiry_itm_call(self):
        g = black_scholes_greeks(110, 100, 0, 0.30, "call")
        assert g.delta == 1.0
        assert g.gamma == 0.0
        assert g.vanna == 0.0
        assert g.charm == 0.0

    def test_zero_days_to_expiry_otm_put(self):
        g = black_scholes_greeks(110, 100, 0, 0.30, "put")
        assert g.delta == 0.0
        assert g.gamma == 0.0

    def test_negative_days_to_expiry_does_not_raise(self):
        g = black_scholes_greeks(90, 100, -1, 0.30, "put")
        assert g.delta == -1.0

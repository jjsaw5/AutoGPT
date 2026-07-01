"""Tests for voldesk.gex: net GEX/vGEX/DEX/VEX/CEX, ratios, zero-gamma strike
interpolation, and OI walls, against hand-computed expected values.

Contracts here construct Greeks objects directly (bypassing
black_scholes_greeks) so each test's expected numbers can be computed by
hand from small, exact inputs.
"""

from __future__ import annotations

import math

from voldesk.gex import OptionContract, compute_gex_snapshot
from voldesk.greeks import Greeks


def _g(delta=0.0, gamma=0.0, vanna=0.0, charm=0.0) -> Greeks:
    return Greeks(delta=delta, gamma=gamma, vanna=vanna, charm=charm)


class TestNetGexAndRatio:
    def test_two_strike_net_gex_and_ratio(self):
        contracts = [
            OptionContract(
                strike=95, expiration="2026-08-01", option_type="put",
                open_interest=100, volume=0, implied_volatility=0.3,
                greeks=_g(gamma=0.02),
            ),
            OptionContract(
                strike=105, expiration="2026-08-01", option_type="call",
                open_interest=100, volume=0, implied_volatility=0.3,
                greeks=_g(gamma=0.03),
            ),
        ]
        snap = compute_gex_snapshot("TEST", spot=100, contracts=contracts, as_of="2026-07-01")

        assert snap.total_put_gex == 200.0  # 0.02 * 100 * 100
        assert snap.total_call_gex == 300.0  # 0.03 * 100 * 100
        assert snap.total_net_gex == 100.0
        assert math.isclose(snap.gex_ratio, 0.6)

        strike95 = next(sb for sb in snap.per_strike if sb.strike == 95)
        strike105 = next(sb for sb in snap.per_strike if sb.strike == 105)
        assert strike95.net_gex == -200.0
        assert strike105.net_gex == 300.0

    def test_empty_chain_ratio_is_none(self):
        snap = compute_gex_snapshot("TEST", spot=100, contracts=[], as_of="2026-07-01")
        assert snap.gex_ratio is None
        assert snap.vgex_ratio is None
        assert snap.oi_ratio is None
        assert snap.dex_ratio is None
        assert snap.vex_ratio is None
        assert snap.cex_ratio is None
        assert snap.total_net_gex == 0.0
        assert snap.zero_gamma_strike is None
        assert snap.max_oi_strike is None


class TestZeroGammaStrikeInterpolation:
    def test_clean_crossing_between_two_strikes(self):
        # Net GEX per strike: 95 -> -10, 100 -> -5, 105 -> +20
        # Cumulative walking ascending: -10, -15, +5
        # Sign change between strike 100 (cum=-15) and strike 105 (cum=+5).
        # frac = 15 / (5 - (-15)) = 15/20 = 0.75
        # crossing = 100 + 0.75 * (105 - 100) = 103.75
        contracts = [
            OptionContract(
                strike=95, expiration="2026-08-01", option_type="put",
                open_interest=1, volume=0, implied_volatility=0.3,
                greeks=_g(gamma=0.10),
            ),
            OptionContract(
                strike=100, expiration="2026-08-01", option_type="put",
                open_interest=1, volume=0, implied_volatility=0.3,
                greeks=_g(gamma=0.05),
            ),
            OptionContract(
                strike=105, expiration="2026-08-01", option_type="call",
                open_interest=1, volume=0, implied_volatility=0.3,
                greeks=_g(gamma=0.20),
            ),
        ]
        snap = compute_gex_snapshot("TEST", spot=100, contracts=contracts, as_of="2026-07-01")
        assert snap.zero_gamma_strike is not None
        assert math.isclose(snap.zero_gamma_strike, 103.75)

    def test_no_sign_change_returns_none(self):
        # Every strike contributes positive net GEX -- cumulative sum never
        # crosses zero, so there is no zero-gamma strike.
        contracts = [
            OptionContract(
                strike=strike, expiration="2026-08-01", option_type="call",
                open_interest=1, volume=0, implied_volatility=0.3,
                greeks=_g(gamma=0.05),
            )
            for strike in (90, 100, 110)
        ]
        snap = compute_gex_snapshot("TEST", spot=100, contracts=contracts, as_of="2026-07-01")
        assert snap.zero_gamma_strike is None

    def test_exact_zero_at_a_strike(self):
        contracts = [
            OptionContract(
                strike=95, expiration="2026-08-01", option_type="put",
                open_interest=1, volume=0, implied_volatility=0.3,
                greeks=_g(gamma=0.10),
            ),
            OptionContract(
                strike=100, expiration="2026-08-01", option_type="call",
                open_interest=1, volume=0, implied_volatility=0.3,
                greeks=_g(gamma=0.10),
            ),
        ]
        snap = compute_gex_snapshot("TEST", spot=100, contracts=contracts, as_of="2026-07-01")
        # cumulative: -10, then -10+10=0 exactly at strike 100.
        assert snap.zero_gamma_strike == 100


class TestOiWalls:
    def test_max_oi_strike_and_oi_ratio(self):
        contracts = [
            OptionContract(90, "2026-08-01", "call", 30, 0, 0.3),
            OptionContract(90, "2026-08-01", "put", 20, 0, 0.3),
            OptionContract(100, "2026-08-01", "call", 60, 0, 0.3),
            OptionContract(100, "2026-08-01", "put", 20, 0, 0.3),
            OptionContract(110, "2026-08-01", "call", 10, 0, 0.3),
            OptionContract(110, "2026-08-01", "put", 30, 0, 0.3),
        ]
        snap = compute_gex_snapshot("TEST", spot=100, contracts=contracts, as_of="2026-07-01")

        assert snap.max_oi_strike == 100  # total_oi 80 beats 50 and 40
        # total_call_oi = 30+60+10=100, total_put_oi=20+20+30=70
        assert math.isclose(snap.oi_ratio, 100 / 170)

        # Greeks-less contracts contribute zero to every greek-derived metric.
        assert snap.total_net_gex == 0.0
        assert snap.gex_ratio is None


class TestVgex:
    def test_volume_weighted_variant(self):
        contracts = [
            OptionContract(
                strike=100, expiration="2026-08-01", option_type="call",
                open_interest=5, volume=50, implied_volatility=0.3,
                greeks=_g(gamma=0.02),
            ),
            OptionContract(
                strike=100, expiration="2026-08-01", option_type="put",
                open_interest=5, volume=20, implied_volatility=0.3,
                greeks=_g(gamma=0.01),
            ),
        ]
        snap = compute_gex_snapshot("TEST", spot=100, contracts=contracts, as_of="2026-07-01")

        assert snap.total_call_gex == 10.0  # 0.02*5*100
        assert snap.total_put_gex == 5.0  # 0.01*5*100
        assert snap.total_call_vgex == 100.0  # 0.02*50*100
        assert snap.total_put_vgex == 20.0  # 0.01*20*100
        assert snap.net_vgex == 80.0
        assert math.isclose(snap.vgex_ratio, 100 / 120)


class TestDexVexCex:
    def test_net_and_ratios(self):
        contracts = [
            OptionContract(
                strike=100, expiration="2026-08-01", option_type="call",
                open_interest=10, volume=0, implied_volatility=0.3,
                greeks=_g(delta=0.6, vanna=0.05, charm=-0.01),
            ),
            OptionContract(
                strike=100, expiration="2026-08-01", option_type="put",
                open_interest=10, volume=0, implied_volatility=0.3,
                greeks=_g(delta=-0.4, vanna=0.03, charm=-0.02),
            ),
        ]
        snap = compute_gex_snapshot("TEST", spot=100, contracts=contracts, as_of="2026-07-01")

        # DEX: call=0.6*10*100=600, put=-0.4*10*100=-400, net=600-(-400)=1000
        assert snap.net_dex == 1000.0
        assert math.isclose(snap.dex_ratio, 600 / (600 + -400))

        # VEX: call=0.05*10*100=50, put=0.03*10*100=30, net=20
        assert snap.net_vex == 20.0
        assert math.isclose(snap.vex_ratio, 50 / 80)

        # CEX: call=-0.01*10*100=-10, put=-0.02*10*100=-20, net=-10-(-20)=10
        assert snap.net_cex == 10.0
        assert math.isclose(snap.cex_ratio, -10 / -30)


class TestUndefinedFieldsStayNone:
    def test_proprietary_fields_default_none(self):
        snap = compute_gex_snapshot("TEST", spot=100, contracts=[], as_of="2026-07-01")
        assert snap.p_trans is None
        assert snap.n_trans is None
        assert snap.cotmp is None
        assert snap.cotmc is None
        assert snap.grade is None
        assert snap.db_change is None


class TestOptionContractNormalization:
    def test_option_type_aliases_normalize(self):
        c1 = OptionContract(100, "2026-08-01", "C", 1, 0, 0.3)
        c2 = OptionContract(100, "2026-08-01", "PUT", 1, 0, 0.3)
        assert c1.option_type == "call"
        assert c2.option_type == "put"

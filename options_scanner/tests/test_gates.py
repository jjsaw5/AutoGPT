from options_scanner.models import (
    Catalyst, Direction, Horizon, Leg, Structure, StructureType, Thesis, VolRegime,
)
from options_scanner.pipeline.gates import evaluate_gates

from .conftest import make_candidate


def _thesis(**overrides):
    base = dict(
        direction=Direction.BULLISH, conviction=0.7, vol_regime=VolRegime.CHEAP,
        horizon=Horizon.SWING, catalyst=Catalyst.FLOW_ONLY, days_to_catalyst=None,
        iv_rank=20.0,
    )
    base.update(overrides)
    return Thesis(**base)


def _long_call(max_loss=300.0):
    return Structure(
        structure_type=StructureType.LONG_CALL,
        legs=[Leg("buy", "call", 300, "~7d")],
        max_profit=600.0, max_loss=max_loss, breakevens=[303.0],
    )


def test_g1_passes_on_volume_when_oi_is_zero(config):
    # SPY case: a real, liquid chain reports OI=0 (feed glitch) but healthy
    # volume. G1 must key off volume, not hard-fail on the bogus zero.
    from options_scanner.pipeline.gates import _g1_contract_liquidity
    s = _long_call()
    s.from_chain = True
    s.contract_oi = 0            # feed reported zero
    s.contract_volume = 1500     # but clearly being traded
    g = config.gates
    res = _g1_contract_liquidity(make_candidate("SPY"), s, g, {})
    assert res.passed
    # And a genuinely dead strike (OI 0, tiny volume) still fails.
    s.contract_volume = 1
    assert not _g1_contract_liquidity(make_candidate("SPY"), s, g, {}).passed


def test_clean_candidate_passes_gates(config):
    from options_scanner.exits import build_exit_plan
    c = make_candidate()
    t, s = _thesis(), _long_call()
    report = evaluate_gates(c, t, s, config, context={"exit_plan": build_exit_plan(s, t)})
    assert report.passed, report.flags()


def test_g11_blocks_without_exit_plan(config):
    c = make_candidate()
    report = evaluate_gates(c, _thesis(), _long_call(), config)  # no exit plan
    g11 = next(r for r in report.results if r.gate_id == "G11")
    assert not g11.passed


def test_g4_blocks_untagged_long_premium_through_earnings(config):
    c = make_candidate()
    # Long call, a flow-tagged thesis, but earnings lands in 2 days (inside the
    # swing holding window) and it is NOT an earnings play => block (IV crush).
    t = _thesis(catalyst=Catalyst.FLOW_ONLY, days_to_earnings=2)
    report = evaluate_gates(c, t, _long_call(), config)
    g4 = next(r for r in report.results if r.gate_id == "G4")
    assert not g4.passed


def test_g4_allows_tagged_earnings_play(config):
    c = make_candidate()
    # Same earnings-in-2-days, but the thesis IS an earnings play => allowed/flagged.
    t = _thesis(catalyst=Catalyst.EARNINGS, days_to_catalyst=2, days_to_earnings=2)
    report = evaluate_gates(c, t, _long_call(), config)
    g4 = next(r for r in report.results if r.gate_id == "G4")
    assert g4.passed


def test_g4_no_earnings_in_window_passes(config):
    c = make_candidate()
    t = _thesis(catalyst=Catalyst.FLOW_ONLY, days_to_earnings=45)  # beyond swing window
    report = evaluate_gates(c, t, _long_call(), config)
    g4 = next(r for r in report.results if r.gate_id == "G4")
    assert g4.passed


def test_g6_blocks_oversized_risk(config):
    c = make_candidate()
    report = evaluate_gates(c, _thesis(), _long_call(max_loss=900.0), config)
    g6 = next(r for r in report.results if r.gate_id == "G6")
    assert not g6.passed  # 900 > 500 ceiling


def test_g6_max_trade_risk_raises_ceiling(config):
    # Learning mode: max_trade_risk lifts the G6 cap so a $450 trade that fails
    # the %-based $400 ceiling passes once the override is set to $500.
    c = make_candidate()
    config.raw["account"]["max_trade_risk"] = 0      # disabled -> %-based $400 cap
    r1 = evaluate_gates(c, _thesis(), _long_call(max_loss=450.0), config)
    assert not next(r for r in r1.results if r.gate_id == "G6").passed
    config.raw["account"]["max_trade_risk"] = 500    # override raises cap to $500
    r2 = evaluate_gates(c, _thesis(), _long_call(max_loss=450.0), config)
    assert next(r for r in r2.results if r.gate_id == "G6").passed


def test_g7_blocks_at_position_cap(config):
    c = make_candidate()
    ctx = {"open_positions": 6}
    report = evaluate_gates(c, _thesis(), _long_call(), config, context=ctx)
    g7 = next(r for r in report.results if r.gate_id == "G7")
    assert not g7.passed


def test_g7_blocks_over_aggregate_risk(config):
    c = make_candidate()
    ctx = {"open_risk": 1900}
    report = evaluate_gates(c, _thesis(), _long_call(max_loss=300.0), config, context=ctx)
    g7 = next(r for r in report.results if r.gate_id == "G7")
    assert not g7.passed  # 1900 + 300 > 2000


def test_g3_micro_requires_override(config):
    from options_scanner.models import CapTier
    c = make_candidate(cap_tier=CapTier.MICRO, market_cap=100e6)
    report = evaluate_gates(c, _thesis(), _long_call(), config)
    g3 = next(r for r in report.results if r.gate_id == "G3")
    assert not g3.passed
    report2 = evaluate_gates(
        c, _thesis(), _long_call(), config, context={"manual_override": True}
    )
    g3b = next(r for r in report2.results if r.gate_id == "G3")
    # override clears the MICRO block (dollar-vol still evaluated / deferred)
    assert g3b.passed or "override" not in g3b.detail


def test_g12_blocks_over_correlated_direction(config):
    # account $5k, max_correlated 15% = $750. Existing $600 bullish + new $300 > cap.
    c = make_candidate(sector="Technology")
    t = _thesis(direction=Direction.BULLISH)
    ctx = {"open_exposure": [
        {"sector": "Energy", "direction": "bullish", "risk": 600},
    ]}
    report = evaluate_gates(c, t, _long_call(max_loss=300), config, context=ctx)
    g12 = next(r for r in report.results if r.gate_id == "G12")
    assert not g12.passed  # 600 same-direction + 300 new = 900 > 750


def test_g12_passes_under_cap(config):
    c = make_candidate(sector="Technology")
    t = _thesis(direction=Direction.BULLISH)
    ctx = {"open_exposure": [{"sector": "Energy", "direction": "bearish", "risk": 300}]}
    report = evaluate_gates(c, t, _long_call(max_loss=300), config, context=ctx)
    g12 = next(r for r in report.results if r.gate_id == "G12")
    assert g12.passed  # opposite direction, different sector => no cluster


def test_g12_defers_without_exposure(config):
    c = make_candidate()
    report = evaluate_gates(c, _thesis(), _long_call(), config)
    g12 = next(r for r in report.results if r.gate_id == "G12")
    assert g12.passed and "deferred" in g12.detail


def test_g8_stale_data_blocks(config):
    c = make_candidate()
    report = evaluate_gates(c, _thesis(), _long_call(), config, context={"data_stale": True})
    g8 = next(r for r in report.results if r.gate_id == "G8")
    assert not g8.passed

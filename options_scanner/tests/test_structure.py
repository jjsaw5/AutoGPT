from options_scanner.models import Direction, Horizon, StructureType, VolRegime
from options_scanner.pipeline.structure import select_structure
from options_scanner.pipeline.thesis import build_thesis

from .conftest import make_candidate


def _thesis(config, **overrides):
    c = make_candidate(signals=overrides.pop("signals", None) or {})
    t = build_thesis(c, config)
    for k, v in overrides.items():
        setattr(t, k, v)
    return c, t


def test_cheap_strong_swing_is_long_premium_when_it_fits(config):
    # Cheap underlying: naked long premium (~$300) fits the $500 ceiling.
    c = make_candidate("F", price=100.0, cap_tier=None)
    c.price = 100.0
    t = build_thesis(c, config)
    t.direction = Direction.BULLISH
    t.vol_regime = VolRegime.CHEAP
    t.horizon = Horizon.SWING
    t.conviction = 0.8
    t.iv_rank = 15.0
    s = select_structure(c, t, config)
    assert s.structure_type == StructureType.LONG_CALL
    assert s.is_defined_risk
    assert s.max_loss and s.max_loss <= config.account["risk_high_conviction_max"]


def test_long_premium_reward_not_inflated(config):
    # Long premium reward:risk must stay within the spread family range (~0.5-1.5)
    # so pool EV-normalization isn't skewed toward long options (artifact fix).
    c = make_candidate("F", price=100.0, cap_tier=None)
    c.price = 100.0
    t = build_thesis(c, config)
    t.direction = Direction.BULLISH
    t.vol_regime = VolRegime.CHEAP
    t.horizon = Horizon.SWING
    t.conviction = 0.8
    t.iv_rank = 15.0
    s = select_structure(c, t, config)
    assert s.structure_type == StructureType.LONG_CALL
    assert s.max_profit / s.max_loss <= 1.5


def test_expensive_long_premium_falls_back_to_spread(config):
    # Pricey underlying: a naked long (~$900) exceeds the $500 ceiling => spread.
    c, t = _thesis(config)  # price 300 => long call ~$900
    t.direction = Direction.BULLISH
    t.vol_regime = VolRegime.CHEAP
    t.horizon = Horizon.SWING
    t.conviction = 0.8
    t.iv_rank = 15.0
    s = select_structure(c, t, config)
    assert s.structure_type == StructureType.DEBIT_VERTICAL
    assert s.max_loss <= config.account["risk_high_conviction_max"]


def test_rich_moderate_is_credit_spread(config):
    c, t = _thesis(config)
    t.direction = Direction.BULLISH
    t.vol_regime = VolRegime.RICH
    t.horizon = Horizon.POSITION
    t.conviction = 0.5
    t.iv_rank = 75.0
    s = select_structure(c, t, config)
    assert s.structure_type == StructureType.CREDIT_VERTICAL


def test_rich_neutral_is_iron_condor(config):
    c, t = _thesis(config)
    t.direction = Direction.NEUTRAL
    t.vol_regime = VolRegime.RICH
    s = select_structure(c, t, config)
    assert s.structure_type == StructureType.IRON_CONDOR
    assert len(s.legs) == 4


def test_leaps_is_deep_itm(config):
    c, t = _thesis(config)
    t.direction = Direction.BULLISH
    t.vol_regime = VolRegime.CHEAP
    t.horizon = Horizon.LEAPS
    t.conviction = 0.8
    s = select_structure(c, t, config)
    assert s.structure_type == StructureType.LEAPS
    # Deep-ITM call strike well below spot (~0.75x).
    assert s.legs[0].strike < c.price


def test_0dte_is_defined_risk(config):
    c, t = _thesis(config)
    t.horizon = Horizon.INTRADAY
    s = select_structure(c, t, config)
    assert s.structure_type == StructureType.ZERO_DTE_SPREAD
    assert s.is_defined_risk


def test_elevated_ivr_prefers_spread_over_naked_long(config):
    c, t = _thesis(config)
    t.direction = Direction.BULLISH
    t.vol_regime = VolRegime.CHEAP
    t.horizon = Horizon.SWING
    t.conviction = 0.85
    t.iv_rank = 60.0  # elevated => spread, not naked long
    s = select_structure(c, t, config)
    assert s.structure_type == StructureType.DEBIT_VERTICAL

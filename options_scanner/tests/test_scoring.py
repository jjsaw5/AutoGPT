from options_scanner.models import (
    Catalyst, Direction, Horizon, Leg, Structure, StructureType, Thesis, VolRegime,
)
from options_scanner.pipeline.scoring import score_candidate

from .conftest import make_candidate


def _thesis(**overrides):
    base = dict(
        direction=Direction.BULLISH, conviction=0.75, vol_regime=VolRegime.CHEAP,
        horizon=Horizon.SWING, catalyst=Catalyst.FLOW_ONLY, iv_rank=15.0,
        iv=0.2, rv=0.35, implied_move=0.03, expected_move=0.05,
        supporting_signals=["net_premium", "technical", "darkpool"],
    )
    base.update(overrides)
    return Thesis(**base)


def _long_call():
    return Structure(
        structure_type=StructureType.LONG_CALL,
        legs=[Leg("buy", "call", 300, "~7d")],
        max_profit=600.0, max_loss=300.0, breakevens=[303.0],
    )


def _credit_spread():
    return Structure(
        structure_type=StructureType.CREDIT_VERTICAL,
        legs=[Leg("sell", "put", 290, "~14d"), Leg("buy", "put", 285, "~14d")],
        max_profit=175.0, max_loss=325.0, breakevens=[288.25],
    )


def test_pillars_bounded_0_100(config):
    s = score_candidate(make_candidate(), _thesis(), _long_call(), config)
    for name, val in s.pillars().items():
        assert 0.0 <= val <= 100.0, f"{name}={val}"
    assert 0.0 <= s.composite <= 100.0


def test_buying_cheap_vol_scores_p1_high(config):
    s = score_candidate(make_candidate(), _thesis(iv_rank=10.0), _long_call(), config)
    assert s.p1 > 60  # low IVR + IV<RV => strong long-premium edge


def test_buying_rich_vol_kills_p1(config):
    t = _thesis(vol_regime=VolRegime.RICH, iv_rank=85.0)
    s = score_candidate(make_candidate(), t, _long_call(), config)
    assert s.p1 < 30  # buying premium in rich regime => mismatch penalty


def test_selling_rich_vol_scores_p1_high(config):
    # Consistent rich regime: high IVR *and* IV > RV (positive variance premium).
    t = _thesis(
        vol_regime=VolRegime.RICH, iv_rank=80.0, iv=0.5, rv=0.3,
        direction=Direction.BULLISH,
    )
    s = score_candidate(make_candidate(), t, _credit_spread(), config)
    assert s.p1 > 55


def test_corroboration_scale(config):
    one = _thesis(supporting_signals=["net_premium"])
    three = _thesis(supporting_signals=["net_premium", "technical", "darkpool"])
    s1 = score_candidate(make_candidate(), one, _long_call(), config)
    s3 = score_candidate(make_candidate(), three, _long_call(), config)
    assert s1.p6 == 20.0
    assert s3.p6 == 75.0


def test_ev_and_pop_present(config):
    s = score_candidate(make_candidate(), _thesis(), _credit_spread(), config)
    assert 0.0 < s.pop < 1.0
    # credit spread EV sign follows POP*win - (1-POP)*loss - fees
    assert isinstance(s.expected_value, float)

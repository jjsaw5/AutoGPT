from options_scanner.models import Direction, VolRegime
from options_scanner.pipeline.thesis import build_thesis

from .conftest import make_candidate


def test_bullish_cheap_vol_thesis(config):
    c = make_candidate()  # bullish premium, price above MAs, IVR 20
    t = build_thesis(c, config)
    assert t.direction == Direction.BULLISH
    assert t.vol_regime == VolRegime.CHEAP
    assert 0.0 < t.conviction <= 1.0
    assert "net_premium" in t.supporting_signals


def test_bearish_from_negative_premium(config):
    c = make_candidate(
        price=100.0,
        signals={
            "price_avg_50": 110.0,
            "price_avg_200": 120.0,
            "net_prem": {
                "net_call_premium": -800_000.0,
                "net_put_premium": 900_000.0,
                "net_call_volume": -2000.0,
                "net_put_volume": 3000.0,
            },
        },
    )
    t = build_thesis(c, config)
    assert t.direction == Direction.BEARISH


def test_rich_vol_regime(config):
    c = make_candidate(signals={"iv_rank": 80.0, "iv": 0.5, "rv": 0.3})
    t = build_thesis(c, config)
    assert t.vol_regime == VolRegime.RICH


def test_agreement_measures_consensus_with_net_direction():
    from options_scanner.pipeline.thesis import _agreement
    # DKNG case: one big bearish vote vs two small bullish → net bearish, but
    # only 1 of 3 votes agrees → low agreement (not the old 2/3 majority).
    votes = (0.09, -0.75, 0.14)
    net = -0.14  # weighted net bearish
    assert _agreement(votes, net) == 1 / 3
    # unanimous → 1.0
    assert _agreement((0.5, 0.3, 0.2), 0.33) == 1.0


def test_iv_vs_rv_helper():
    from options_scanner.models import Thesis, Direction, Horizon, Catalyst
    t = Thesis(
        direction=Direction.BULLISH, conviction=0.5, vol_regime=VolRegime.CHEAP,
        horizon=Horizon.SWING, catalyst=Catalyst.FLOW_ONLY, iv=0.2, rv=0.4,
    )
    # IV well below RV => score above 50 (buyer's edge).
    assert t.regime_iv_vs_rv() > 50

from odte.config import TECH_MEGACAPS
from odte.models import Quote, Regime
from odte.regime import score_regime


def quotes(spy_pct, xlk_pct, qqq_pct, megacap_pcts):
    out = {
        "SPY": Quote("SPY", 700, 700, spy_pct),
        "XLK": Quote("XLK", 175, 175, xlk_pct),
        "QQQ": Quote("QQQ", 600, 600, qqq_pct),
    }
    for symbol, pct in zip(TECH_MEGACAPS, megacap_pcts):
        out[symbol] = Quote(symbol, 100, 100, pct)
    return out


def test_broad_tech_strength_is_strong_bull():
    score = score_regime(quotes(0.4, 1.4, 1.4, [1.0] * 8))
    assert score.regime is Regime.STRONG_BULL
    assert score.regime.direction == 1


def test_broad_tech_weakness_is_strong_bear():
    score = score_regime(quotes(-0.2, -1.2, -1.2, [-1.0] * 8))
    assert score.regime is Regime.STRONG_BEAR
    assert score.regime.direction == -1


def test_flat_tape_is_neutral_and_has_no_direction():
    score = score_regime(quotes(0.1, 0.1, 0.1, [0.1, -0.1] * 4))
    assert score.regime is Regime.NEUTRAL
    assert score.regime.direction == 0


def test_narrow_leadership_does_not_reach_strong_bull():
    """XLK carried by one name while the group is red is not a tech bid.

    This is the case breadth exists to catch -- without it the sector
    relative-strength term alone would read as bullish.
    """
    score = score_regime(
        quotes(0.0, 1.0, 0.8, [3.0, -0.4, -0.3, -0.5, -0.2, -0.6, -0.1, -0.3])
    )
    assert score.regime is not Regime.STRONG_BULL
    assert score.breadth < 0


def test_missing_spy_quote_is_neutral_rather_than_a_guess():
    score = score_regime({})
    assert score.regime is Regime.NEUTRAL
    assert "no SPY quote" in score.detail


def test_score_is_bounded_by_component_weights():
    score = score_regime(quotes(-5.0, 5.0, 5.0, [5.0] * 8))
    assert -1.0 <= score.score <= 1.0

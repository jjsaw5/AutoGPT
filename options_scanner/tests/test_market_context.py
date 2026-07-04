"""Cross-asset market regime + its effect on ranking."""

from __future__ import annotations

import math

from options_scanner.market_context import score_market, MarketRegime
from options_scanner.models import Decision, Direction
from options_scanner.pipeline.rank import rank_and_decide

from .conftest import make_candidate
from .test_journal import _ec  # reuse the EvaluatedCandidate builder


def _series(start, drift, seed, n=260):
    out, v = [], start
    for i in range(n):
        v *= (1 + drift + 0.004 * math.sin(i / 9 + seed))
        out.append(round(v, 2))
    return out


def _risk_on_series():
    # equal-weight, small caps and cyclicals leading => broadening / risk-on
    return {
        "SPY": _series(400, 0.0006, 1), "RSP": _series(150, 0.0011, 2),
        "IWM": _series(180, 0.0013, 3), "HYG": _series(75, 0.0006, 4),
        "LQD": _series(105, 0.0001, 5), "TLT": _series(95, -0.0004, 6),
        "XLY": _series(190, 0.0010, 7), "XLP": _series(78, 0.0002, 8),
    }


def _risk_off_series():
    # bonds and defensives leading, small caps lagging => risk-off
    return {
        "SPY": _series(400, -0.0004, 1), "RSP": _series(150, -0.0009, 2),
        "IWM": _series(180, -0.0013, 3), "HYG": _series(75, -0.0006, 4),
        "LQD": _series(105, 0.0002, 5), "TLT": _series(95, 0.0008, 6),
        "XLY": _series(190, -0.0010, 7), "XLP": _series(78, 0.0004, 8),
    }


def test_risk_on_regime():
    r = score_market(_risk_on_series(), yield_spread=0.3)
    assert r.composite > 0
    assert r.macro_score >= 1
    assert r.direction == 1


def test_risk_off_regime():
    r = score_market(_risk_off_series(), yield_spread=-0.2)
    assert r.composite < 0
    assert r.macro_score <= -1
    assert r.direction == -1


def test_missing_yield_redistributes():
    r = score_market(_risk_on_series(), yield_spread=None)
    yc = next(c for c in r.components if c["ratio"] == "10Y-2Y")
    assert yc["available"] is False
    assert any("redistribut" in n for n in r.notes)
    assert -1.0 <= r.composite <= 1.0


def test_bullish_penalized_in_risk_off(config):
    regime = score_market(_risk_off_series(), yield_spread=-0.4)
    assert regime.direction == -1
    ec = _ec(ticker="ABC", composite=74.0, ev=10.0, decision=Decision.GO)
    ec.thesis.direction = Direction.BULLISH
    rank_and_decide([ec], config, regime=regime)
    # composite nudged down; a fighting-the-regime bull loses points
    assert ec.regime_adj < 0
    assert ec.effective_composite < 74.0
    assert "regime" in ec.biggest_risk.lower()


def test_no_adjustment_when_disabled(config):
    regime = score_market(_risk_off_series(), yield_spread=-0.4)
    config.raw["market_context"]["max_composite_adjustment"] = 0
    ec = _ec(ticker="ABC", composite=74.0, ev=10.0, decision=Decision.GO)
    ec.thesis.direction = Direction.BULLISH
    rank_and_decide([ec], config, regime=regime)
    assert ec.regime_adj == 0.0

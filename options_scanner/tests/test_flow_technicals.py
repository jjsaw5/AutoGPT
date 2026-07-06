"""Flow-quality analysis and the technicals stack."""

from __future__ import annotations

from options_scanner.flow import analyze_flow
from options_scanner.technicals import (
    compute_technicals, late_entry_penalty, rsi_wilder, technical_vote,
)


def _alert(typ, ask, bid, opening=True, sweep=False, multileg=False, voo=1.5):
    return {"type": typ, "total_ask_side_prem": ask, "total_bid_side_prem": bid,
            "all_opening_trades": opening, "has_sweep": sweep,
            "has_multileg": multileg, "volume_oi_ratio": voo}


def test_flow_bullish_calls_bought_at_ask():
    r = analyze_flow([_alert("call", 3_000_000, 200_000)])
    assert r.vote > 0 and r.n == 1
    assert 0 <= r.quality <= 1


def test_flow_puts_bought_is_bearish():
    r = analyze_flow([_alert("put", 3_000_000, 100_000)])
    assert r.vote < 0


def test_flow_calls_sold_at_bid_is_bearish():
    r = analyze_flow([_alert("call", 100_000, 3_000_000)])  # net sold at bid
    assert r.vote < 0


def test_flow_quality_rewards_opening_singleleg():
    clean = analyze_flow([_alert("call", 2_000_000, 0, opening=True, multileg=False)])
    noisy = analyze_flow([_alert("call", 2_000_000, 0, opening=False, multileg=True)])
    assert clean.quality > noisy.quality


def test_empty_flow():
    r = analyze_flow([])
    assert r.vote == 0.0 and r.n == 0


def _uptrend(n=220, start=50.0, step=0.004):
    return [round(start * (1 + step) ** i, 4) for i in range(n)]


def test_rsi_bounds():
    assert 0 <= rsi_wilder(_uptrend()) <= 100


def test_technical_vote_bullish_uptrend():
    t = compute_technicals(_uptrend())
    assert t is not None
    assert technical_vote(t) > 0.5   # clean uptrend => strongly bullish


def test_technical_vote_bearish_downtrend():
    down = list(reversed(_uptrend()))
    t = compute_technicals(down)
    assert technical_vote(t) < 0


def test_late_entry_penalty_trims_stretched():
    # price far above EMA21 in a bullish trade => penalty < 1
    t = {"stretch": 0.12, "rsi14": 78}
    assert late_entry_penalty(t, direction=1) < 0.8
    # not stretched => no penalty
    assert late_entry_penalty({"stretch": 0.01, "rsi14": 55}, direction=1) == 1.0

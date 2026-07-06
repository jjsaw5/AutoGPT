"""Position review — grade + recommended action."""

from __future__ import annotations

from options_scanner.position_review import review_position


def _r(**kw):
    base = dict(ticker="X", direction=1, is_long_premium=True, pnl_pct=0.0,
                dte=45, days_to_earnings=None, thesis_dir=1,
                thesis_conviction=0.6, vol_regime="cheap")
    base.update(kw)
    return review_position(base.pop("ticker"), **base)


def test_aligned_bullish_long_cheap_holds():
    r = _r(direction=1, thesis_dir=1, vol_regime="cheap", pnl_pct=0.10)
    assert r.action == "HOLD"
    assert r.grade[0] in ("A", "B")


def test_flow_flipped_against_and_losing_closes():
    r = _r(direction=1, thesis_dir=-1, pnl_pct=-0.15)
    assert r.action == "CLOSE"
    assert "flipped" in r.reason


def test_earnings_through_long_premium_closes():
    r = _r(is_long_premium=True, days_to_earnings=3, dte=40)
    assert r.action == "CLOSE"
    assert "earnings" in r.reason.lower()


def test_winner_aligned_trims():
    r = _r(direction=1, thesis_dir=1, pnl_pct=0.6, vol_regime="cheap")
    assert r.action == "TRIM"


def test_long_premium_in_rich_vol_downgraded():
    cheap = _r(vol_regime="cheap")
    rich = _r(vol_regime="rich")
    assert rich.score < cheap.score


def test_flow_against_but_green_watch_to_exit():
    r = _r(direction=-1, thesis_dir=1, pnl_pct=0.08, is_long_premium=True, vol_regime="fair")
    # bearish position, bullish flow, but currently green => exit into strength
    assert r.action in ("WATCH", "CLOSE")

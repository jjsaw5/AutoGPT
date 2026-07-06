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


def test_conviction_reversal_closes():
    # strong opposing conviction => CLOSE, and the reason names the driver
    r = _r(direction=1, thesis_dir=-1, pnl_pct=-0.15, thesis_conviction=0.7, driver="technicals")
    assert r.action == "CLOSE"
    assert "technicals" in r.reason


def test_weak_reversal_watches_not_closes():
    # DKNG case: opposed but low conviction => WATCH (tighten), not a hard CLOSE
    r = _r(direction=1, thesis_dir=-1, pnl_pct=-0.08, thesis_conviction=0.37, driver="technicals")
    assert r.action == "WATCH"
    assert "tighten" in r.reason


def test_weak_grade_with_runway_watches_not_closes():
    # DKNG case: weak grade (D-), green, 46 DTE, no imminent earnings, no stop hit
    # => WATCH ("close if it slides"), NOT a hard close on grade alone.
    r = _r(direction=1, thesis_dir=-1, thesis_conviction=0.4, pnl_pct=0.02,
           vol_regime="rich", iv_rank=55, dte=46, days_to_earnings=30)
    assert r.action == "WATCH"
    assert "slides" in r.reason


def test_stop_loss_triggers_close():
    # Blew past the stop => CLOSE, even if the thesis still aligns.
    r = _r(direction=1, thesis_dir=1, pnl_pct=-0.45, dte=46)
    assert r.action == "CLOSE"
    assert "stop" in r.reason.lower()


def test_vol_penalty_ramps_with_iv_rank():
    # no cliff: IVR 47 is a mild penalty, IVR 75 a big one (long premium)
    mild = _r(iv_rank=47, vol_regime="fair")
    steep = _r(iv_rank=75, vol_regime="rich")
    assert steep.score < mild.score


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

"""Catalyst engine — earnings (from theses) + curated macro + computed OPEX."""

from __future__ import annotations

import datetime

from options_scanner.catalysts import (
    CatalystEvent,
    build_radar,
    opex_dates,
    render_radar,
    _third_friday,
)


class _Thesis:
    def __init__(self, d2e):
        self.days_to_earnings = d2e


class _EC:
    def __init__(self, ticker, d2e):
        self.ticker = ticker
        self.thesis = _Thesis(d2e)


_NOW = datetime.datetime(2026, 7, 6, 12, 0)


def test_third_friday_and_opex():
    assert _third_friday(2026, 7) == datetime.date(2026, 7, 17)   # 3rd Fri of Jul 2026
    got = opex_dates(datetime.date(2026, 7, 6), datetime.date(2026, 7, 31))
    assert got == [datetime.date(2026, 7, 17)]


def test_earnings_from_theses_within_horizon():
    evaluated = [_EC("AAPL", 3), _EC("MSFT", 30), _EC("SPY", None)]
    events = build_radar(evaluated, now=_NOW, horizon_days=14, macro_events=[])
    kinds = [(e.scope, e.kind, e.days_out) for e in events if e.kind == "earnings"]
    assert ("AAPL", "earnings", 3) in kinds     # in-window earnings surfaced
    assert all(s != "MSFT" for s, _, _ in kinds)  # 30d out — beyond horizon
    assert all(s != "SPY" for s, _, _ in kinds)   # no earnings date — skipped


def test_held_name_flagged_as_risk():
    evaluated = [_EC("DKNG", 2)]
    events = build_radar(evaluated, now=_NOW, horizon_days=14, macro_events=[],
                         held_tickers={"DKNG"})
    e = next(e for e in events if e.scope == "DKNG")
    assert "HELD" in e.label and "IV-crush" in e.note


def test_macro_and_opex_in_window():
    macro = [
        {"date": "2026-07-14", "kind": "cpi", "label": "CPI"},
        {"date": "2026-09-01", "kind": "fomc", "label": "FOMC"},  # beyond 14d
    ]
    events = build_radar([], now=_NOW, horizon_days=14, macro_events=macro)
    kinds = {e.kind for e in events}
    assert "cpi" in kinds          # 8d out — in window
    assert "opex" in kinds         # 2026-07-17 computed
    assert "fomc" not in kinds     # ~57d out — beyond horizon


def test_radar_sorted_soonest_first():
    macro = [{"date": "2026-07-14", "kind": "cpi", "label": "CPI"}]
    events = build_radar([_EC("AAPL", 1)], now=_NOW, horizon_days=14, macro_events=macro)
    days = [e.days_out for e in events]
    assert days == sorted(days)
    assert events[0].scope == "AAPL"   # earnings tomorrow leads


def test_render_radar_text():
    events = build_radar([_EC("AAPL", 1)], now=_NOW, horizon_days=14, macro_events=[])
    out = render_radar(events)
    assert "CATALYST RADAR" in out and "AAPL" in out
    empty = render_radar([])
    assert "no scheduled catalysts" in empty

"""Independent (conviction-free) expected-move model."""

from __future__ import annotations

import math

from options_scanner.expected_move import (
    estimate_expected_move, historical_earnings_move, realized_vol, statistical_move,
)


def _closes(vol_daily=0.02, n=120, start=100.0):
    # Deterministic zig-zag with a fixed daily amplitude → known-ish realized vol.
    out = [start]
    for i in range(1, n):
        step = vol_daily * (1 if i % 2 else -1)
        out.append(round(out[-1] * (1 + step), 4))
    return out


def test_realized_vol_positive():
    rv = realized_vol(_closes(0.02), 20)
    assert rv is not None and rv > 0


def test_statistical_move_scales_with_horizon():
    closes = _closes(0.02)
    short = statistical_move(closes, 5)
    long = statistical_move(closes, 60)
    assert short is not None and long is not None
    assert long > short  # sqrt(dte) scaling


def test_expected_move_is_conviction_free():
    # No conviction argument exists — the estimate depends only on price history.
    closes = _closes(0.02)
    em = estimate_expected_move(closes, 30)
    assert em is not None and em > 0


def test_historical_earnings_move():
    series = [{"date": f"2026-01-{d:02d}", "close": c}
              for d, c in zip(range(1, 11), [100, 101, 100, 108, 102, 103, 94, 95, 96, 97])]
    # earnings on the 4th (100→108, +8%) and 7th (103→94, -8.7%)
    em = historical_earnings_move(series, ["2026-01-04", "2026-01-07"])
    assert em is not None
    assert 0.07 < em < 0.10


def test_earnings_move_combines_with_drift():
    closes = _closes(0.02)
    series = [{"date": f"2026-01-{d:02d}", "close": c}
              for d, c in enumerate(closes[:40], start=1) if d <= 28]
    # With an earnings event the estimate should be >= the pure drift move.
    drift = statistical_move(closes, 10)
    combined = estimate_expected_move(
        closes, 10, is_earnings=True, series_dated=series,
        past_earnings_dates=[series[10]["date"]],
    )
    assert combined is not None and drift is not None
    assert combined >= drift

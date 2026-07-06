"""Independent expected-move model (spec §4, fixes the circularity flaw).

The old expected move was implied-move × a conviction factor — so if the engine
already "liked" a trade it mechanically manufactured a larger expected move,
which then rewarded long premium. That turned confidence into fake edge.

This model is **independent of conviction**. It estimates the move the underlying
is statistically likely to make over the trade's horizon from realized
volatility, plus — for earnings plays — the average *historical* move around the
last several earnings dates. That estimate is then compared honestly to the
option-implied move; long premium is only favored when statistics say the move
should exceed what the market has priced.

stdlib only.
"""

from __future__ import annotations

import math
from typing import Optional


def realized_vol(closes: list[float], window: int) -> Optional[float]:
    """Annualized close-to-close volatility over the last `window` returns."""
    if len(closes) < window + 1:
        return None
    rets = [
        math.log(closes[i] / closes[i - 1])
        for i in range(len(closes) - window, len(closes))
        if closes[i - 1] > 0
    ]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var * 252)


def statistical_move(closes: list[float], horizon_dte: int) -> Optional[float]:
    """1-sigma move (fraction of spot) over the horizon, from realized vol.

    Window scales with horizon: short trades use recent (10d) vol, longer trades
    a broader window. `move = RV_annual · sqrt(dte / 252)`.
    """
    window = 10 if horizon_dte <= 10 else 20 if horizon_dte <= 45 else 60
    rv = realized_vol(closes, window) or realized_vol(closes, 20) or realized_vol(closes, 10)
    if rv is None:
        return None
    dte = max(1, horizon_dte)
    return rv * math.sqrt(dte / 252.0)


def historical_earnings_move(
    series_dated: list[dict], past_earnings_dates: list[str], *, max_events: int = 8
) -> Optional[float]:
    """Average absolute overnight move around the last N earnings dates."""
    price_by_date = {r["date"]: r["close"] for r in series_dated}
    dates = [r["date"] for r in series_dated]
    moves: list[float] = []
    for ed in sorted(past_earnings_dates, reverse=True):
        if ed not in price_by_date:
            continue
        idx = dates.index(ed)
        if idx == 0:
            continue
        prev = price_by_date[dates[idx - 1]]
        cur = price_by_date[ed]
        if prev > 0:
            moves.append(abs(cur / prev - 1.0))
        if len(moves) >= max_events:
            break
    return sum(moves) / len(moves) if moves else None


def estimate_expected_move(
    closes: list[float],
    horizon_dte: int,
    *,
    is_earnings: bool = False,
    series_dated: list[dict] | None = None,
    past_earnings_dates: list[str] | None = None,
) -> Optional[float]:
    """Conviction-free expected move (fraction of spot) for the horizon.

    For earnings plays the event move and the drift move are treated as
    independent, so their variances add: `total = sqrt(event² + drift²)`.
    """
    drift = statistical_move(closes, horizon_dte)
    if is_earnings and series_dated and past_earnings_dates:
        event = historical_earnings_move(series_dated, past_earnings_dates)
        if event is not None:
            base = drift or 0.0
            return round(math.sqrt(event ** 2 + base ** 2), 4)
    return round(drift, 4) if drift is not None else None

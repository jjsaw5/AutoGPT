"""Deterministic in-memory DataProvider used by tests and the default dev run.

Generates a realistic-looking chain from a Black–Scholes pricer so the rest of
the stack can exercise real numbers without needing network access.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

from app.core.models import OptionChain, OptionContract, OptionRight
from app.data.base import DataProvider, IVHistoryPoint, PriceBar


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bsm_price(spot: float, strike: float, t: float, r: float, sigma: float, right: OptionRight) -> float:
    """Black–Scholes–Merton price (no dividends). Used only by the mock."""
    if t <= 0 or sigma <= 0:
        intrinsic = max(spot - strike, 0.0) if right is OptionRight.CALL else max(strike - spot, 0.0)
        return intrinsic
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma**2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    if right is OptionRight.CALL:
        return spot * _norm_cdf(d1) - strike * math.exp(-r * t) * _norm_cdf(d2)
    return strike * math.exp(-r * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def _bsm_delta(spot: float, strike: float, t: float, r: float, sigma: float, right: OptionRight) -> float:
    if t <= 0 or sigma <= 0:
        return 1.0 if (right is OptionRight.CALL and spot > strike) else 0.0
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma**2) * t) / (sigma * math.sqrt(t))
    return _norm_cdf(d1) if right is OptionRight.CALL else _norm_cdf(d1) - 1.0


class MockProvider:
    """Deterministic provider used for unit tests and offline demos."""

    name = "mock"

    def __init__(
        self,
        spot: float = 100.0,
        base_iv: float = 0.30,
        as_of: datetime | None = None,
        iv_history_high: float = 0.55,
        iv_history_low: float = 0.18,
    ):
        self._spot = spot
        self._base_iv = base_iv
        self._as_of = as_of or datetime(2026, 4, 22, 15, 0, tzinfo=timezone.utc)
        self._iv_high = iv_history_high
        self._iv_low = iv_history_low

    def now(self) -> datetime:
        return self._as_of

    def get_chain(self, ticker: str, expiry: date | None = None) -> OptionChain:
        spot = self._spot
        r = 0.045
        today = self._as_of.date()
        expiries = [today + timedelta(days=d) for d in (7, 30, 45, 60, 90)]
        if expiry is not None:
            expiries = [expiry] if expiry in expiries else [expiry]

        contracts: list[OptionContract] = []
        for exp in expiries:
            dte = max((exp - today).days, 0)
            t = dte / 365.0
            # Modest vol smile: further strikes have slightly higher IV.
            for strike_offset in range(-20, 21, 2):
                strike = round(spot + strike_offset, 2)
                if strike <= 0:
                    continue
                moneyness = abs(strike - spot) / spot
                iv = self._base_iv + 0.10 * moneyness
                for right in (OptionRight.CALL, OptionRight.PUT):
                    price = _bsm_price(spot, strike, t, r, iv, right)
                    delta = _bsm_delta(spot, strike, t, r, iv, right)
                    bid = max(price - 0.05, 0.01)
                    ask = price + 0.05
                    contracts.append(
                        OptionContract(
                            symbol=f"{ticker.upper()}{exp:%y%m%d}{right.value}{int(strike*1000):08d}",
                            underlying=ticker.upper(),
                            expiry=exp,
                            strike=strike,
                            right=right,
                            bid=round(bid, 2),
                            ask=round(ask, 2),
                            last=round(price, 2),
                            volume=100,
                            open_interest=500,
                            implied_vol=iv,
                            delta=delta,
                            as_of=self._as_of,
                        )
                    )
        return OptionChain(
            underlying=ticker.upper(),
            spot=spot,
            as_of=self._as_of,
            risk_free_rate=r,
            contracts=contracts,
        )

    def get_history(self, ticker: str, lookback_days: int) -> list[PriceBar]:
        bars: list[PriceBar] = []
        start = self._as_of.date() - timedelta(days=lookback_days)
        for i in range(lookback_days):
            d = start + timedelta(days=i)
            drift = math.sin(i / 20.0) * 2.0
            close = self._spot + drift
            bars.append(
                PriceBar(
                    date=d,
                    open=close - 0.5,
                    high=close + 1.0,
                    low=close - 1.0,
                    close=close,
                    volume=1_000_000,
                )
            )
        return bars

    def get_iv_history(self, ticker: str, lookback_days: int = 252) -> list[IVHistoryPoint]:
        # Deterministic sinusoid between iv_low and iv_high — lets tests pin IVR.
        history: list[IVHistoryPoint] = []
        start = self._as_of.date() - timedelta(days=lookback_days)
        mid = (self._iv_high + self._iv_low) / 2.0
        amp = (self._iv_high - self._iv_low) / 2.0
        for i in range(lookback_days):
            d = start + timedelta(days=i)
            iv = mid + amp * math.sin(i / 30.0)
            history.append(IVHistoryPoint(date=d, atm_iv=round(iv, 4)))
        # Last point matches base_iv so get_chain and get_iv_history agree.
        history[-1] = IVHistoryPoint(date=history[-1].date, atm_iv=self._base_iv)
        return history


_: DataProvider = MockProvider()
del _

"""Unusual Whales flow confirmation.

Verified against the live API. Two endpoints are used, both of which
return `data` as a list ordered **oldest first**, with premium values as
decimal *strings*:

  stock/{ticker}/net-prem-ticks
      Per-minute buckets (~405 rows/session). Each row is that minute's
      net premium, NOT a running total. Reading only the last row is
      therefore a single minute of noise -- on 2026-07-30 that produced a
      maximally bullish +1.00 for SPY while the trailing half hour was
      actually flat. This module sums a trailing window instead.

  market/{sector}/sector-tide
      Cumulative running totals for the session (~391 rows), so the last
      row is the day's net flow. Takes a sector *name* ("Technology"),
      not an ETF ticker -- passing "XLK" returns 400 Invalid sector.

Sign convention: net_call_premium is positive when calls are being bought
and net_put_premium is negative when puts are being sold, so
`net_call - net_put` is positive for bullish flow in both feeds.

Normalisation is scale-free: each reading is divided by the largest
absolute value that same series reached during the session, giving [-1, 1]
without hardcoding a dollar scale. The obvious alternative,
`(call - put) / (|call| + |put|)`, collapses to exactly +/-1 whenever the
two have opposite signs -- which is most of the time -- so it carries
almost no information.

UW remains a *confirmation* layer: it only adjusts conviction. It cannot
open a trade the price and regime gates rejected, nor veto one they
accepted. Without UW_API_KEY the whole module no-ops.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests

BASE_URL = "https://api.unusualwhales.com/api"
DEFAULT_TIMEOUT = 15
DEFAULT_WINDOW_MINUTES = 30

# sector-tide wants the sector name; the strategy thinks in ETFs.
SECTOR_BY_ETF = {
    "XLK": "Technology",
    "XLF": "Financial Services",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLY": "Consumer Cyclical",
    "XLP": "Consumer Defensive",
    "XLI": "Industrials",
    "XLU": "Utilities",
    "XLB": "Basic Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _net(row: dict) -> float:
    """Bullish-positive net premium for one row."""
    call = float(row.get("net_call_premium") or 0)
    put = float(row.get("net_put_premium") or 0)
    return call - put


def _scale_free(series: list[float], current: float) -> float:
    """Current reading against the largest absolute value the series reached."""
    if not series:
        return 0.0
    peak = max(abs(v) for v in series)
    if peak <= 0:
        return 0.0
    return _clamp(current / peak)


@dataclass
class UWContext:
    """Flow-derived confirmation, normalised to [-1, 1] where +1 is bullish."""

    net_premium_bias: float = 0.0
    sector_tide_bias: float = 0.0
    available: bool = False
    detail: str = "unavailable"

    @property
    def bias(self) -> float:
        if not self.available:
            return 0.0
        return _clamp((self.net_premium_bias + self.sector_tide_bias) / 2)


class UnusualWhalesClient:
    def __init__(
        self,
        api_key: str | None = None,
        session: requests.Session | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.api_key = api_key or os.getenv("UW_API_KEY")
        self._session = session or requests.Session()
        self._timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _get(self, path: str, **params) -> list[dict]:
        response = self._session.get(
            f"{BASE_URL}/{path}",
            params=params,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and "error" in payload:
            raise RuntimeError(f"unusual whales: {payload['error']}")
        rows = payload.get("data", payload) if isinstance(payload, dict) else payload
        return rows or []

    def net_premium_bias(
        self, ticker: str, window_minutes: int = DEFAULT_WINDOW_MINUTES
    ) -> float:
        """Trailing-window options flow for one ticker.

        Rows are per-minute, so the window is summed rather than sampled.
        The result is scored against every equivalent window in the session
        so that "flow is building" and "flow has faded" are distinguishable.
        """
        rows = self._get(f"stock/{ticker}/net-prem-ticks")
        if not rows:
            return 0.0
        per_minute = [_net(row) for row in rows]
        window = max(1, window_minutes)
        rolling = [
            sum(per_minute[max(0, i - window + 1) : i + 1])
            for i in range(len(per_minute))
        ]
        return _scale_free(rolling, rolling[-1])

    def sector_tide_bias(self, sector: str = "Technology") -> float:
        """Cumulative sector flow for the session.

        Accepts a sector name or a sector ETF ticker, which is mapped.
        """
        sector = SECTOR_BY_ETF.get(sector.upper(), sector)
        rows = self._get(f"market/{sector}/sector-tide")
        if not rows:
            return 0.0
        cumulative = [_net(row) for row in rows]
        return _scale_free(cumulative, cumulative[-1])


def load_uw_context(
    ticker: str,
    enabled: bool = True,
    sector: str = "Technology",
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
) -> UWContext | None:
    """Best-effort UW context. Never raises -- returns None when unavailable."""
    if not enabled:
        return None
    client = UnusualWhalesClient()
    if not client.enabled:
        return None
    try:
        flow = client.net_premium_bias(ticker, window_minutes)
        tide = client.sector_tide_bias(sector)
    except Exception as exc:  # noqa: BLE001 - confirmation must never block a trade
        return UWContext(available=False, detail=f"uw unavailable: {exc}")

    return UWContext(
        net_premium_bias=flow,
        sector_tide_bias=tide,
        available=True,
        detail=(
            f"{ticker} {window_minutes}m flow {flow:+.2f}, "
            f"{sector} tide {tide:+.2f}"
        ),
    )

"""Unusual Whales adapter -- optional, and currently unwired.

IMPORTANT, please read before relying on this module:

There is no Unusual Whales credential in this workspace and no UW connector
installed, so *none of the request/response handling below has been executed
against the live API*. The endpoint paths and field names reflect UW's
documented v1 shape but should be treated as unverified until someone runs
`UnusualWhalesClient(...).sector_tide("XLK")` with a real key and confirms.

The design keeps that risk contained:

  * Without `UW_API_KEY`, `load_uw_context()` returns `None` and the signal
    engine runs on FMP + broker data alone. Nothing breaks.
  * UW only ever adjusts *conviction*. It cannot open a trade the price and
    regime gates rejected, and it cannot veto one they accepted. So if the
    field names turn out to be wrong, the failure mode is a slightly
    mis-scored conviction number, not a bad entry.

To wire it up: set UW_API_KEY, run the CLI with --use-uw, and reconcile any
KeyError against the live payload.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests

BASE_URL = "https://api.unusualwhales.com/api"
DEFAULT_TIMEOUT = 15


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
        return max(-1.0, min(1.0, (self.net_premium_bias + self.sector_tide_bias) / 2))


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

    def _get(self, path: str, **params) -> dict:
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
        return response.json()

    def net_premium(self, ticker: str) -> float:
        """Call vs put premium imbalance for the session, normalised to [-1, 1]."""
        payload = self._get(f"stock/{ticker}/net-prem-ticks")
        rows = payload.get("data", payload) or []
        if not rows:
            return 0.0
        latest = rows[-1] if isinstance(rows, list) else rows
        calls = float(latest.get("net_call_premium") or 0)
        puts = float(latest.get("net_put_premium") or 0)
        total = abs(calls) + abs(puts)
        if total <= 0:
            return 0.0
        return max(-1.0, min(1.0, (calls - puts) / total))

    def sector_tide(self, etf: str = "XLK") -> float:
        """Net sector flow direction, normalised to [-1, 1]."""
        payload = self._get(f"market/{etf}/sector-tide")
        rows = payload.get("data", payload) or []
        if not rows:
            return 0.0
        latest = rows[-1] if isinstance(rows, list) else rows
        net = float(latest.get("net_call_premium") or 0) - float(
            latest.get("net_put_premium") or 0
        )
        scale = abs(float(latest.get("net_call_premium") or 0)) + abs(
            float(latest.get("net_put_premium") or 0)
        )
        if scale <= 0:
            return 0.0
        return max(-1.0, min(1.0, net / scale))


def load_uw_context(ticker: str, enabled: bool = True) -> UWContext | None:
    """Best-effort UW context. Never raises -- returns None when unavailable."""
    if not enabled:
        return None
    client = UnusualWhalesClient()
    if not client.enabled:
        return None
    try:
        return UWContext(
            net_premium_bias=client.net_premium(ticker),
            sector_tide_bias=client.sector_tide(),
            available=True,
            detail="unusual whales flow confirmation active",
        )
    except Exception as exc:  # noqa: BLE001 - confirmation layer must never block
        return UWContext(available=False, detail=f"uw unavailable: {exc}")

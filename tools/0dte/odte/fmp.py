"""Financial Modeling Prep client (stable API).

Only the `/stable/` endpoints are used. The legacy `/api/v3/` routes now
reject requests for keys issued after 2025-08-31 with a "Legacy Endpoint"
error, so nothing here should be ported back to them.

FMP covers regular-hours history and quotes. It does *not* serve premarket
bars -- a 1-minute request returns exactly 390 bars per session, 09:30 to
15:59 ET -- so premarket levels come from the broker feed instead
(see `brokers.py`).
"""

from __future__ import annotations

import os
from datetime import date, datetime

import requests

from .config import MARKET_TZ
from .models import Bar, Quote, Session

BASE_URL = "https://financialmodelingprep.com/stable"
DEFAULT_TIMEOUT = 20


class FMPError(RuntimeError):
    pass


class FMPClient:
    def __init__(
        self,
        api_key: str | None = None,
        session: requests.Session | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.api_key = api_key or os.getenv("FMP_API_KEY")
        if not self.api_key:
            raise FMPError("FMP_API_KEY is not set")
        self._session = session or requests.Session()
        self._timeout = timeout

    def _get(self, path: str, **params) -> list | dict:
        params["apikey"] = self.api_key
        response = self._session.get(
            f"{BASE_URL}/{path}", params=params, timeout=self._timeout
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and "Error Message" in payload:
            raise FMPError(payload["Error Message"])
        return payload

    def daily_bars(self, symbol: str, limit: int = 260) -> list[Bar]:
        """Daily bars, oldest first. Used for the 200-day SMA context."""
        rows = self._get("historical-price-eod/full", symbol=symbol, limit=limit)
        bars = [
            Bar(
                ts=datetime.strptime(row["date"], "%Y-%m-%d").replace(tzinfo=MARKET_TZ),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume") or 0),
            )
            for row in rows
        ]
        return sorted(bars, key=lambda b: b.ts)

    def intraday_bars(
        self,
        symbol: str,
        interval: str = "5min",
        day: date | None = None,
    ) -> list[Bar]:
        """Regular-hours intraday bars for one session, oldest first."""
        day = day or datetime.now(MARKET_TZ).date()
        rows = self._get(
            f"historical-chart/{interval}",
            symbol=symbol,
            **{"from": day.isoformat(), "to": day.isoformat()},
        )
        bars = [
            Bar(
                ts=datetime.strptime(row["date"], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=MARKET_TZ
                ),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume") or 0),
                session=Session.REGULAR,
            )
            for row in rows
        ]
        return sorted(bars, key=lambda b: b.ts)

    def batch_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        rows = self._get("batch-quote", symbols=",".join(symbols))
        quotes: dict[str, Quote] = {}
        for row in rows:
            symbol = row["symbol"]
            price = float(row.get("price") or 0)
            change = float(row.get("change") or 0)
            quotes[symbol] = Quote(
                symbol=symbol,
                price=price,
                prev_close=price - change,
                change_pct=float(row.get("changePercentage") or 0),
                volume=float(row.get("volume") or 0),
                day_high=_opt_float(row.get("dayHigh")),
                day_low=_opt_float(row.get("dayLow")),
            )
        return quotes


def _opt_float(value) -> float | None:
    return None if value is None else float(value)

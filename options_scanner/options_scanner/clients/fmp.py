"""Financial Modeling Prep client (data backbone).

Covers the FMP-owned signals from spec §2: company profile / market cap /
sector, quotes, price history, earnings calendar. Uses the ``/stable`` API.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import BaseHTTPClient, HTTPError

logger = logging.getLogger(__name__)


class FMPClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://financialmodelingprep.com",
        timeout: float = 20.0,
        cache_ttl: float = 300.0,
    ) -> None:
        self.api_key = api_key
        self._http = BaseHTTPClient(base_url, timeout=timeout, cache_ttl=cache_ttl)

    def clear_cache(self) -> None:
        self._http.clear_cache()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        params = dict(params or {})
        params["apikey"] = self.api_key
        return self._http.get(path, params=params)

    # --- endpoints -------------------------------------------------------------
    def profile(self, symbol: str) -> dict[str, Any] | None:
        """Company profile: market cap, sector, industry, avg volume, price."""
        try:
            data = self._get("/stable/profile", {"symbol": symbol})
        except HTTPError as exc:
            logger.warning("FMP profile(%s) failed: %s", symbol, exc)
            return None
        if isinstance(data, list) and data:
            return data[0]
        return None

    def quote(self, symbol: str) -> dict[str, Any] | None:
        try:
            data = self._get("/stable/quote", {"symbol": symbol})
        except HTTPError as exc:
            logger.warning("FMP quote(%s) failed: %s", symbol, exc)
            return None
        if isinstance(data, list) and data:
            return data[0]
        return None

    def earnings_calendar(
        self, symbol: str, *, limit: int = 4
    ) -> list[dict[str, Any]]:
        try:
            data = self._get(
                "/stable/earnings", {"symbol": symbol, "limit": limit}
            )
        except HTTPError as exc:
            logger.warning("FMP earnings(%s) failed: %s", symbol, exc)
            return []
        return data if isinstance(data, list) else []

    def historical_closes(self, symbol: str, *, limit: int = 300) -> list[float]:
        """Daily closes oldest→newest (FMP returns newest-first; we reverse)."""
        try:
            data = self._get(
                "/stable/historical-price-eod/light", {"symbol": symbol}
            )
        except HTTPError as exc:
            logger.warning("FMP historical(%s) failed: %s", symbol, exc)
            return []
        if not isinstance(data, list):
            return []
        closes = [
            float(row["price"])
            for row in reversed(data)
            if isinstance(row, dict) and row.get("price") is not None
        ]
        return closes[-limit:]

    def treasury_spread(self) -> float | None:
        """Latest 10Y − 2Y treasury yield spread (percentage points)."""
        try:
            data = self._get("/stable/treasury-rates", {})
        except HTTPError as exc:
            logger.warning("FMP treasury-rates failed: %s", exc)
            return None
        rows = data if isinstance(data, list) else [data]
        for row in rows:  # newest first
            if isinstance(row, dict) and row.get("year10") is not None and row.get("year2") is not None:
                return round(float(row["year10"]) - float(row["year2"]), 3)
        return None

    # --- normalized convenience ------------------------------------------------
    def snapshot(self, symbol: str) -> dict[str, Any]:
        """Merged profile + quote snapshot with normalized keys."""
        profile = self.profile(symbol) or {}
        quote = self.quote(symbol) or {}
        return {
            "price": quote.get("price") or profile.get("price"),
            "market_cap": profile.get("marketCap") or quote.get("marketCap"),
            "sector": profile.get("sector"),
            "industry": profile.get("industry"),
            "avg_volume": profile.get("averageVolume") or quote.get("avgVolume"),
            "volume": quote.get("volume") or profile.get("volume"),
            "company_name": profile.get("companyName") or quote.get("name"),
            "beta": profile.get("beta"),
            "price_avg_50": quote.get("priceAvg50"),
            "price_avg_200": quote.get("priceAvg200"),
            "year_high": quote.get("yearHigh"),
            "year_low": quote.get("yearLow"),
        }

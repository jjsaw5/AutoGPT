"""Async client for the Unusual Whales REST API.

Endpoint paths are centralized as module constants. If UW renames a path,
edit the constant — nothing else changes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


BASE_URL = "https://api.unusualwhales.com"

FLOW_ALERTS_PATH = "/api/option-trades/flow-alerts"
STOCK_INFO_PATH = "/api/stock/{ticker}/info"
IV_RANK_PATH = "/api/stock/{ticker}/iv-rank"
EARNINGS_PATH = "/api/stock/{ticker}/earnings"
NEWS_PATH = "/api/news/headlines"


class UnusualWhalesError(RuntimeError):
    pass


@dataclass
class UnusualWhalesClient:
    api_key: str
    base_url: str = BASE_URL
    timeout: float = 30.0

    @classmethod
    def from_env(cls) -> "UnusualWhalesClient":
        key = os.environ.get("UNUSUAL_WHALES_API_KEY")
        if not key:
            raise UnusualWhalesError(
                "UNUSUAL_WHALES_API_KEY is not set. Add it to .env or your shell."
            )
        return cls(api_key=key)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
            timeout=self.timeout,
        )

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        async with self._client() as c:
            r = await c.get(path, params=params)
            if r.status_code >= 400:
                raise UnusualWhalesError(
                    f"GET {path} -> {r.status_code}: {r.text[:300]}"
                )
            return r.json()

    @staticmethod
    def _unwrap(payload: Any) -> Any:
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    async def flow_alerts(
        self,
        *,
        min_premium: int | None = None,
        min_dte: int | None = None,
        max_dte: int | None = None,
        max_vol_oi: float | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if min_premium is not None:
            params["min_premium"] = min_premium
        if min_dte is not None:
            params["min_dte"] = min_dte
        if max_dte is not None:
            params["max_dte"] = max_dte
        if max_vol_oi is not None:
            params["max_volume_oi_ratio"] = max_vol_oi
        return self._unwrap(await self._get(FLOW_ALERTS_PATH, params=params)) or []

    async def stock_info(self, ticker: str) -> dict[str, Any]:
        return self._unwrap(await self._get(STOCK_INFO_PATH.format(ticker=ticker))) or {}

    async def iv_rank(self, ticker: str) -> float | None:
        try:
            payload = self._unwrap(await self._get(IV_RANK_PATH.format(ticker=ticker)))
        except UnusualWhalesError:
            return None
        if isinstance(payload, dict):
            for k in ("iv_rank", "ivRank", "iv_rank_pct"):
                v = payload.get(k)
                if v is not None:
                    return float(v)
        return None

    async def earnings(self, ticker: str) -> list[dict[str, Any]]:
        try:
            return self._unwrap(await self._get(EARNINGS_PATH.format(ticker=ticker))) or []
        except UnusualWhalesError:
            return []

    async def news(self, ticker: str, limit: int = 10) -> list[dict[str, Any]]:
        try:
            return self._unwrap(
                await self._get(NEWS_PATH, params={"ticker": ticker, "limit": limit})
            ) or []
        except UnusualWhalesError:
            return []

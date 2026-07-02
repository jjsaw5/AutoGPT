"""Unusual Whales client (edge layer).

Covers the UW-owned signals from spec §2: flow alerts, dark pool, net premium
ticks, IV rank, term structure, realized vol, GEX, max pain, and the
market-wide idea-generation feeds. Auth is ``Authorization: Bearer <key>``.

Base-tier reality (verified against the live API): per-ticker endpoints are
available, but several market-wide feeds (movers, optionable-tickers, ...)
require the Advanced tier. Every method degrades gracefully — an unavailable
or errored endpoint returns ``None``/``[]`` rather than raising, so the
pipeline keeps running on whatever signal it can get (spec §11 stale-data /
degrade behavior).
"""

from __future__ import annotations

import logging
from typing import Any

from .base import BaseHTTPClient, HTTPError

logger = logging.getLogger(__name__)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_error_envelope(payload: Any) -> bool:
    """UW returns {"msg"/"message"/"code": ...} with no "data" on error."""
    if not isinstance(payload, dict):
        return False
    if "data" in payload:
        return False
    return any(k in payload for k in ("msg", "message", "code", "error"))


class UnusualWhalesClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.unusualwhales.com",
        timeout: float = 20.0,
        cache_ttl: float = 300.0,
    ) -> None:
        self.api_key = api_key
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            # Documented required header (unusualwhales.com/skill.md).
            "UW-CLIENT-API-ID": "100001",
        }
        self._http = BaseHTTPClient(
            base_url, default_headers=headers, timeout=timeout, cache_ttl=cache_ttl
        )
        # Endpoints we've learned are gated so we stop hammering them this scan.
        self._unavailable: set[str] = set()

    def clear_cache(self) -> None:
        self._http.clear_cache()

    def _get_data(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if path in self._unavailable:
            return None
        try:
            payload = self._http.get(path, params=params)
        except HTTPError as exc:
            logger.warning("UW %s failed: %s", path, exc)
            return None
        if _is_error_envelope(payload):
            code = payload.get("code") or payload.get("msg") or payload.get("message")
            logger.info("UW %s unavailable (%s)", path, code)
            self._unavailable.add(path)
            return None
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    # --- per-ticker signals (base tier) ---------------------------------------
    def iv_rank(self, ticker: str) -> dict[str, float | None]:
        """Latest IV rank (0-100) and implied vol for the ticker."""
        rows = self._get_data(f"/api/stock/{ticker}/iv-rank")
        if not isinstance(rows, list) or not rows:
            return {"iv_rank": None, "iv": None}
        latest = rows[-1]
        return {
            "iv_rank": _to_float(latest.get("iv_rank_1y")),
            "iv": _to_float(latest.get("volatility")),
        }

    def realized_vol(self, ticker: str) -> dict[str, float | None]:
        """Latest implied vs realized vol (drives IV-vs-RV in P1)."""
        rows = self._get_data(f"/api/stock/{ticker}/volatility/realized")
        if not isinstance(rows, list) or not rows:
            return {"iv": None, "rv": None}
        latest = rows[-1]
        return {
            "iv": _to_float(latest.get("implied_volatility")),
            "rv": _to_float(latest.get("realized_volatility")),
        }

    def term_structure(self, ticker: str) -> list[dict[str, Any]]:
        rows = self._get_data(f"/api/stock/{ticker}/volatility/term-structure")
        return rows if isinstance(rows, list) else []

    def net_prem_ticks(self, ticker: str) -> dict[str, float]:
        """Aggregate net call/put premium and volume across the day's ticks."""
        rows = self._get_data(f"/api/stock/{ticker}/net-prem-ticks")
        agg = {
            "net_call_premium": 0.0,
            "net_put_premium": 0.0,
            "net_call_volume": 0.0,
            "net_put_volume": 0.0,
        }
        if not isinstance(rows, list):
            return agg
        for row in rows:
            agg["net_call_premium"] += _to_float(row.get("net_call_premium")) or 0.0
            agg["net_put_premium"] += _to_float(row.get("net_put_premium")) or 0.0
            agg["net_call_volume"] += _to_float(row.get("net_call_volume")) or 0.0
            agg["net_put_volume"] += _to_float(row.get("net_put_volume")) or 0.0
        return agg

    def flow_alerts(self, ticker: str, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._get_data(
            f"/api/stock/{ticker}/flow-alerts", {"limit": limit}
        )
        return rows if isinstance(rows, list) else []

    def darkpool(self, ticker: str, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._get_data(f"/api/darkpool/{ticker}", {"limit": limit})
        return rows if isinstance(rows, list) else []

    def max_pain(self, ticker: str) -> dict[str, float | None]:
        rows = self._get_data(f"/api/stock/{ticker}/max-pain")
        if not isinstance(rows, list) or not rows:
            return {"max_pain": None, "close": None}
        first = rows[0]
        return {
            "max_pain": _to_float(first.get("max_pain")),
            "close": _to_float(first.get("close")),
        }

    def greek_exposure(self, ticker: str) -> dict[str, Any]:
        rows = self._get_data(f"/api/stock/{ticker}/greek-exposure")
        if not isinstance(rows, list) or not rows:
            return {}
        return rows[-1]

    # --- per-contract chain (base tier; skill.md verified) --------------------
    def option_contracts(
        self, ticker: str, *, expiry: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Per-strike contract data: OI, volume, nbbo_bid/ask, IV, last price.

        Without ``expiry`` returns the ~500 most-active contracts (spanning
        expiries); with ``expiry=YYYY-MM-DD`` returns the full strike ladder for
        that expiry.
        """
        params: dict[str, Any] = {}
        if expiry:
            params["expiry"] = expiry
        if limit:
            params["limit"] = limit
        rows = self._get_data(f"/api/stock/{ticker}/option-contracts", params or None)
        return rows if isinstance(rows, list) else []

    def greeks(self, ticker: str, *, expiry: str | None = None) -> list[dict[str, Any]]:
        """Per-strike greeks (delta/gamma/theta/vega) for an expiry.

        Without ``expiry`` returns the front expiry only; pass ``expiry`` to get
        deltas at a swing/position/LEAPS expiry.
        """
        params = {"expiry": expiry} if expiry else None
        rows = self._get_data(f"/api/stock/{ticker}/greeks", params)
        return rows if isinstance(rows, list) else []

    # --- market-wide idea-generation feeds (may need Advanced tier) ------------
    def movers(self, **params: Any) -> list[dict[str, Any]]:
        rows = self._get_data("/api/market/movers", params or None)
        return rows if isinstance(rows, list) else []

    def hottest_chains(self, **params: Any) -> list[dict[str, Any]]:
        rows = self._get_data("/api/screener/option-contracts", params or None)
        return rows if isinstance(rows, list) else []

    def market_flow_alerts(self, **params: Any) -> list[dict[str, Any]]:
        rows = self._get_data("/api/option-trades/flow-alerts", params or None)
        return rows if isinstance(rows, list) else []

    def oi_change(self, **params: Any) -> list[dict[str, Any]]:
        rows = self._get_data("/api/market/oi-change", params or None)
        return rows if isinstance(rows, list) else []

    def vol_anomaly_top(
        self, *, direction: str = "long_vol", **params: Any
    ) -> list[dict[str, Any]]:
        # Endpoint requires `direction` ∈ {short_vol, long_vol}; long_vol
        # surfaces names with unusual demand to *buy* vol (asymmetric ideas).
        params["direction"] = direction
        rows = self._get_data("/api/volatility/anomaly/top", params)
        return rows if isinstance(rows, list) else []

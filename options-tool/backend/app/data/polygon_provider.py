"""Polygon DataProvider stub — filled in during Phase 2.

Polygon exposes per-expiry option snapshots under
``/v3/snapshot/options/{underlying}`` and historical IV via the derivatives
feed. See ``options-tool/backend/app/data/README.md`` for cost and rate limits.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from app.core.models import OptionChain
from app.data.base import DataProvider, IntradayBar, IVHistoryPoint, PriceBar


class PolygonProvider:
    """Placeholder — raises NotImplementedError until Phase 2."""

    name = "polygon"

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Polygon provider requires an API key")
        self._api_key = api_key

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def get_chain(self, ticker: str, expiry: date | None = None) -> OptionChain:
        raise NotImplementedError("PolygonProvider.get_chain is a Phase 2 deliverable")

    def get_history(self, ticker: str, lookback_days: int) -> list[PriceBar]:
        raise NotImplementedError("PolygonProvider.get_history is a Phase 2 deliverable")

    def get_iv_history(self, ticker: str, lookback_days: int = 252) -> list[IVHistoryPoint]:
        raise NotImplementedError("PolygonProvider.get_iv_history is a Phase 2 deliverable")

    def get_intraday_bars(
        self, ticker: str, session_date: date, interval_minutes: int = 1
    ) -> list[IntradayBar]:
        raise NotImplementedError("PolygonProvider.get_intraday_bars is a Phase 3 deliverable")


_: DataProvider = PolygonProvider.__new__(PolygonProvider)
del _

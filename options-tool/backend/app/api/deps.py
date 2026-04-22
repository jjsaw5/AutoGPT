"""FastAPI dependency wiring.

Default provider is Mock — swap via the ``OPTIONS_TOOL_PROVIDER`` env var to
``yfinance`` (or ``polygon`` once Phase 2 lands).
"""
from __future__ import annotations

import os
from functools import lru_cache

from app.data.base import DataProvider
from app.data.cache import ChainCache
from app.data.mock_provider import MockProvider


@lru_cache(maxsize=1)
def get_provider() -> DataProvider:
    name = os.environ.get("OPTIONS_TOOL_PROVIDER", "mock").lower()
    if name == "mock":
        return MockProvider()
    if name == "yfinance":
        from app.data.yfinance_provider import YFinanceProvider

        return YFinanceProvider(cache=ChainCache(path=os.environ.get("OPTIONS_TOOL_CACHE_DB", ":memory:")))
    if name == "polygon":
        from app.data.polygon_provider import PolygonProvider

        api_key = os.environ.get("POLYGON_API_KEY", "")
        return PolygonProvider(api_key=api_key)
    raise ValueError(f"Unknown provider: {name!r}")


def reset_provider_cache() -> None:
    """Test helper — drop the lru_cache so providers pick up env changes."""
    get_provider.cache_clear()

"""DataProvider protocol and shared DTOs."""
from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.core.models import OptionChain


class PriceBar(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class IntradayBar(BaseModel):
    """One-minute (or other interval) bar used by the 0DTE module."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class IVHistoryPoint(BaseModel):
    date: date
    atm_iv: float = Field(ge=0, description="Annualised at-the-money implied volatility.")


@runtime_checkable
class DataProvider(Protocol):
    """A read-only market-data interface.

    Implementations must be side-effect free aside from optional caching. Callers
    must be able to call multiple methods concurrently in a single analysis run
    without re-hitting an upstream API — the cache decorator handles this.
    """

    name: str

    def get_chain(self, ticker: str, expiry: date | None = None) -> OptionChain:
        """Return the live option chain. If ``expiry`` is None, return all expiries."""
        ...

    def get_history(self, ticker: str, lookback_days: int) -> list[PriceBar]:
        """Return daily OHLCV history for the last ``lookback_days`` sessions."""
        ...

    def get_iv_history(self, ticker: str, lookback_days: int = 252) -> list[IVHistoryPoint]:
        """Return daily ATM IV history used to compute IV Rank / IV Percentile."""
        ...

    def get_intraday_bars(
        self, ticker: str, session_date: date, interval_minutes: int = 1
    ) -> list[IntradayBar]:
        """Return regular-session intraday bars for ``session_date``. Used by 0DTE."""
        ...

    def now(self) -> datetime:
        """Provider's sense of the current time — test providers override this."""
        ...

"""Trading-day calendar.

A scheduler that does not know about holidays will happily fire on
Thanksgiving and, worse, run the normal windows on a half-day when the
close is 13:00 -- which would put the "flat by 15:30" rule two and a half
hours after the market shut.

Holidays come from FMP's `holidays-by-exchange`, which also carries
`adjCloseTime` for early closes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .config import MARKET_TZ
from .fmp import FMPClient

REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)


@dataclass(frozen=True)
class SessionHours:
    trading: bool
    open: time = REGULAR_OPEN
    close: time = REGULAR_CLOSE
    note: str = ""

    @property
    def early_close(self) -> bool:
        return self.trading and self.close < REGULAR_CLOSE


def _parse_clock(value: str | None) -> time | None:
    if not value:
        return None
    text = value.strip()
    for fmt in ("%I:%M %p", "%H:%M", "%I:%M%p"):
        try:
            return datetime.strptime(text.split(" -")[0].strip(), fmt).time()
        except ValueError:
            continue
    return None


class MarketCalendar:
    def __init__(self, client: FMPClient | None = None) -> None:
        self._client = client
        self._holidays: dict[str, dict] | None = None

    def _load(self) -> dict[str, dict]:
        if self._holidays is not None:
            return self._holidays
        self._holidays = {}
        try:
            client = self._client or FMPClient()
            rows = client._get("holidays-by-exchange", exchange="NASDAQ")
            for row in rows or []:
                if row.get("date"):
                    self._holidays[row["date"]] = row
        except Exception:  # noqa: BLE001 - calendar is best effort
            self._holidays = {}
        return self._holidays

    def hours(self, day: date) -> SessionHours:
        if day.weekday() >= 5:
            return SessionHours(trading=False, note="weekend")

        row = self._load().get(day.isoformat())
        if row is None:
            return SessionHours(trading=True)

        if row.get("isClosed"):
            return SessionHours(
                trading=False, note=row.get("name") or "exchange holiday"
            )

        close = _parse_clock(row.get("adjCloseTime")) or REGULAR_CLOSE
        open_ = _parse_clock(row.get("adjOpenTime")) or REGULAR_OPEN
        return SessionHours(
            trading=True,
            open=open_,
            close=close,
            note=row.get("name") or "",
        )

    def is_trading_day(self, day: date) -> bool:
        return self.hours(day).trading


def shift_windows(hours: SessionHours, no_entry_after: time, flat_by: time):
    """Pull the cutoffs in when the exchange closes early.

    On a 13:00 close the normal 15:00 / 15:30 cutoffs are meaningless, so
    they collapse to one hour and thirty minutes before the actual close.
    """
    if not hours.early_close:
        return no_entry_after, flat_by

    close_dt = datetime.combine(date.today(), hours.close)
    return (
        (close_dt - timedelta(hours=1)).time(),
        (close_dt - timedelta(minutes=30)).time(),
    )

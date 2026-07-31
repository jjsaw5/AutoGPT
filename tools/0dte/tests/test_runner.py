from datetime import date, datetime, time

from odte.calendar import MarketCalendar, SessionHours, _parse_clock, shift_windows
from odte.config import DEFAULT_CONFIG, MARKET_TZ
from odte.runner import in_entry_window, next_tick


class StubClient:
    def __init__(self, rows):
        self._rows = rows

    def _get(self, path, **params):
        return self._rows


def at(hour, minute, second=0):
    return datetime(2026, 7, 31, hour, minute, second, tzinfo=MARKET_TZ)


def test_next_tick_lands_on_the_bar_close_plus_settle():
    assert next_tick(at(9, 46, 12)) == at(9, 50, 10)


def test_next_tick_from_exactly_on_a_boundary_advances():
    """Standing at 09:45:00 the 09:45 bar is not closed yet."""
    assert next_tick(at(9, 45, 0)) == at(9, 50, 10)


def test_next_tick_crosses_the_hour():
    assert next_tick(at(10, 58, 30)) == at(11, 0, 10)


def test_entry_windows_accept_the_trend_hours():
    after = DEFAULT_CONFIG.timing.no_entry_after
    for hour, minute in [(9, 45), (11, 25), (13, 30), (14, 55)]:
        assert in_entry_window(at(hour, minute), DEFAULT_CONFIG, after)


def test_entry_windows_reject_open_midday_and_late():
    after = DEFAULT_CONFIG.timing.no_entry_after
    for hour, minute in [(9, 31), (11, 35), (12, 45), (15, 5)]:
        assert not in_entry_window(at(hour, minute), DEFAULT_CONFIG, after)


def test_weekend_is_not_a_trading_day():
    calendar = MarketCalendar(client=StubClient([]))
    assert not calendar.is_trading_day(date(2026, 8, 1))  # Saturday
    assert not calendar.is_trading_day(date(2026, 8, 2))  # Sunday


def test_ordinary_weekday_is_a_trading_day():
    calendar = MarketCalendar(client=StubClient([]))
    hours = calendar.hours(date(2026, 7, 31))
    assert hours.trading
    assert hours.close == time(16, 0)
    assert not hours.early_close


def test_closed_holiday_is_detected():
    calendar = MarketCalendar(
        client=StubClient(
            [{"date": "2026-07-03", "isClosed": True, "name": "Independence Day"}]
        )
    )
    hours = calendar.hours(date(2026, 7, 3))
    assert not hours.trading
    assert "Independence" in hours.note


def test_half_day_reports_an_early_close():
    calendar = MarketCalendar(
        client=StubClient(
            [
                {
                    "date": "2026-11-27",
                    "isClosed": False,
                    "name": "Thanksgiving (early close)",
                    "adjCloseTime": "01:00 PM -05:00",
                }
            ]
        )
    )
    hours = calendar.hours(date(2026, 11, 27))
    assert hours.trading
    assert hours.close == time(13, 0)
    assert hours.early_close


def test_early_close_pulls_the_cutoffs_in():
    """A 13:00 close must not leave 'flat by 15:30' in the schedule."""
    hours = SessionHours(trading=True, close=time(13, 0))
    no_entry_after, flat_by = shift_windows(hours, time(15, 0), time(15, 30))
    assert no_entry_after == time(12, 0)
    assert flat_by == time(12, 30)


def test_normal_day_leaves_cutoffs_alone():
    hours = SessionHours(trading=True)
    assert shift_windows(hours, time(15, 0), time(15, 30)) == (
        time(15, 0),
        time(15, 30),
    )


def test_calendar_failure_degrades_to_trading():
    """A calendar outage must not silently cancel the session."""

    class Boom:
        def _get(self, *a, **k):
            raise RuntimeError("down")

    assert MarketCalendar(client=Boom()).is_trading_day(date(2026, 7, 31))


def test_parse_clock_handles_the_fmp_formats():
    assert _parse_clock("01:00 PM -05:00") == time(13, 0)
    assert _parse_clock("09:30 AM -04:00") == time(9, 30)
    assert _parse_clock(None) is None
    assert _parse_clock("garbage") is None

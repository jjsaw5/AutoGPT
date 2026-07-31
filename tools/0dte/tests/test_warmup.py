"""EMA warm-up across sessions, and as-of truncation.

Both exist because of the same discovery: 21 five-minute bars do not exist
until 11:15 ET. A session-scoped EMA21 is therefore undefined for almost
the entire morning entry window, which silently made 09:40-11:15 a dead
zone where every signal failed the data gate.
"""

from datetime import date, datetime, timedelta

from odte.config import MARKET_TZ, TrendConfig
from odte.levels import build_levels
from odte.models import Bar, Session

TODAY = date(2026, 7, 30)


def session_bars(day: date, count: int, start_price: float = 700.0) -> list[Bar]:
    open_ts = datetime(day.year, day.month, day.day, 9, 30, tzinfo=MARKET_TZ)
    return [
        Bar(
            ts=open_ts + timedelta(minutes=5 * i),
            open=start_price + i * 0.1,
            high=start_price + i * 0.1 + 0.5,
            low=start_price + i * 0.1 - 0.5,
            close=start_price + i * 0.1,
            volume=1000,
            session=Session.REGULAR,
        )
        for i in range(count)
    ]


def test_single_session_cannot_form_ema21_in_the_morning():
    """Three bars is 09:45. Without history the trend gate has nothing."""
    today = session_bars(TODAY, 3)
    levels = build_levels(intraday_bars=today, daily_bars=[], day=TODAY, price=700.0)
    assert levels.ema_slow is None
    assert levels.atr is None


def test_prior_sessions_warm_the_emas_for_an_0940_signal():
    prior = session_bars(date(2026, 7, 29), 78, start_price=690.0)
    today = session_bars(TODAY, 3)
    levels = build_levels(
        intraday_bars=today,
        daily_bars=[],
        day=TODAY,
        price=700.0,
        history_bars=prior + today,
    )
    assert levels.ema_fast is not None
    assert levels.ema_slow is not None
    assert levels.atr is not None


def test_as_of_truncates_future_bars():
    """A replayed 10:00 must not see the 15:00 bars."""
    prior = session_bars(date(2026, 7, 29), 78, start_price=690.0)
    today = session_bars(TODAY, 78)
    as_of = datetime(2026, 7, 30, 10, 0, tzinfo=MARKET_TZ)

    truncated = build_levels(
        intraday_bars=today,
        daily_bars=[],
        day=TODAY,
        price=700.0,
        history_bars=prior + today,
        as_of=as_of,
    )
    full = build_levels(
        intraday_bars=today,
        daily_bars=[],
        day=TODAY,
        price=700.0,
        history_bars=prior + today,
    )
    assert truncated.ema_fast != full.ema_fast
    assert truncated.vwap != full.vwap


def test_vwap_stays_session_scoped_even_with_history():
    """VWAP anchors to today only; the EMAs are the continuous ones."""
    prior = session_bars(date(2026, 7, 29), 78, start_price=500.0)
    today = session_bars(TODAY, 20, start_price=700.0)
    levels = build_levels(
        intraday_bars=today,
        daily_bars=[],
        day=TODAY,
        price=702.0,
        history_bars=prior + today,
    )
    # prior session traded near 500; if VWAP leaked across sessions it
    # would be dragged far below today's range
    assert levels.vwap > 690.0


def test_opening_range_ignores_prior_sessions():
    prior = session_bars(date(2026, 7, 29), 78, start_price=500.0)
    today = session_bars(TODAY, 20, start_price=700.0)
    levels = build_levels(
        intraday_bars=today,
        daily_bars=[],
        day=TODAY,
        price=702.0,
        history_bars=prior + today,
    )
    assert levels.opening_range_low > 690.0


def test_lookback_default_covers_a_weekend():
    assert TrendConfig().intraday_lookback_days >= 4

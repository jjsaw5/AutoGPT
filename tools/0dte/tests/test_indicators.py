from datetime import datetime, timedelta

from odte.config import MARKET_TZ
from odte.indicators import atr, ema, ema_series, sma, true_range, vwap
from odte.models import Bar


def make_bars(rows):
    start = datetime(2026, 7, 30, 9, 30, tzinfo=MARKET_TZ)
    return [
        Bar(
            ts=start + timedelta(minutes=5 * i),
            open=o,
            high=h,
            low=lo,
            close=c,
            volume=v,
        )
        for i, (o, h, lo, c, v) in enumerate(rows)
    ]


def test_sma_uses_only_the_trailing_window():
    assert sma([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 3) == 9.0


def test_sma_returns_none_when_history_is_short():
    assert sma([1, 2], 3) is None


def test_ema_is_sma_seeded():
    # period 3 over 1..10 seeds at 2.0 and converges to 9.0
    series = ema_series(list(range(1, 11)), 3)
    assert series[0] == 2.0
    assert series[-1] == 9.0
    assert ema(list(range(1, 11)), 3) == 9.0


def test_ema_returns_none_when_history_is_short():
    assert ema([1, 2], 5) is None


def test_true_range_spans_the_prior_close():
    previous = Bar(datetime(2026, 7, 30, tzinfo=MARKET_TZ), 10, 11, 9, 10, 1)
    current = Bar(datetime(2026, 7, 30, tzinfo=MARKET_TZ), 14, 15, 13, 14, 1)
    # gap up: 15 - 10 beats the 15 - 13 intrabar range
    assert true_range(current, previous) == 5


def test_atr_needs_more_bars_than_the_period():
    bars = make_bars([(10, 11, 9, 10, 100)] * 3)
    assert atr(bars, 14) is None


def test_atr_of_constant_range_equals_that_range():
    bars = make_bars([(10, 11, 9, 10, 100)] * 20)
    assert atr(bars, 14) == 2.0


def test_vwap_weights_by_volume():
    bars = make_bars(
        [
            (10, 10, 10, 10, 100),
            (20, 20, 20, 20, 300),
        ]
    )
    # typical prices 10 and 20 with 1:3 volume -> 17.5
    assert vwap(bars) == 17.5


def test_vwap_returns_none_without_volume():
    bars = make_bars([(10, 10, 10, 10, 0)])
    assert vwap(bars) is None

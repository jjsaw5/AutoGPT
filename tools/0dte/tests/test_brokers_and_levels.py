"""Parsing and level construction against the real MCP payload shape.

The fixture below is trimmed from an actual
`mcp__Robinhood__get_equity_historicals` response for SPY on 2026-07-30 with
bounds='extended' -- including the session tags, the UTC left-edge
timestamps and the string-typed prices.
"""

from datetime import date

from odte.brokers import parse_historicals, parse_quotes
from odte.levels import build_levels, opening_range, premarket_levels
from odte.models import Session

HISTORICALS = {
    "data": {
        "results": [
            {
                "symbol": "SPY",
                "interval": "5minute",
                "bounds": "extended",
                "bars": [
                    # premarket, 08:00Z == 04:00 ET
                    {
                        "begins_at": "2026-07-30T08:00:00Z",
                        "open_price": "730.590000",
                        "close_price": "730.297100",
                        "high_price": "732.795200",
                        "low_price": "729.890000",
                        "volume": 12911,
                        "session": "pre",
                    },
                    {
                        "begins_at": "2026-07-30T11:35:00Z",
                        "open_price": "734.120700",
                        "close_price": "734.400000",
                        "high_price": "734.480000",
                        "low_price": "734.100000",
                        "volume": 36017,
                        "session": "pre",
                    },
                    {
                        "begins_at": "2026-07-30T13:25:00Z",
                        "open_price": "735.300000",
                        "close_price": "736.040000",
                        "high_price": "736.060000",
                        "low_price": "735.150000",
                        "volume": 44385,
                        "session": "pre",
                    },
                    # regular, 13:30Z == 09:30 ET
                    {
                        "begins_at": "2026-07-30T13:30:00Z",
                        "open_price": "736.050000",
                        "close_price": "735.445100",
                        "high_price": "736.270000",
                        "low_price": "734.970000",
                        "volume": 849728,
                        "session": "reg",
                    },
                    {
                        "begins_at": "2026-07-30T13:35:00Z",
                        "open_price": "735.450000",
                        "close_price": "735.280000",
                        "high_price": "736.050000",
                        "low_price": "734.980000",
                        "volume": 519772,
                        "session": "reg",
                    },
                    {
                        "begins_at": "2026-07-30T13:40:00Z",
                        "open_price": "735.310000",
                        "close_price": "736.400000",
                        "high_price": "736.790000",
                        "low_price": "734.640100",
                        "volume": 523907,
                        "session": "reg",
                    },
                    {
                        "begins_at": "2026-07-30T13:45:00Z",
                        "open_price": "736.380000",
                        "close_price": "737.400000",
                        "high_price": "737.430000",
                        "low_price": "736.360000",
                        "volume": 614755,
                        "session": "reg",
                    },
                    {
                        "begins_at": "2026-07-30T13:50:00Z",
                        "open_price": "737.390000",
                        "close_price": "737.870000",
                        "high_price": "738.370000",
                        "low_price": "737.070000",
                        "volume": 453079,
                        "session": "reg",
                    },
                    {
                        "begins_at": "2026-07-30T13:55:00Z",
                        "open_price": "737.850000",
                        "close_price": "738.625000",
                        "high_price": "738.650000",
                        "low_price": "737.590000",
                        "volume": 509038,
                        "session": "reg",
                    },
                ],
            }
        ]
    }
}


def test_parses_bars_and_converts_utc_to_market_time():
    bars = parse_historicals(HISTORICALS)["SPY"]
    assert len(bars) == 9
    assert bars[0].ts.hour == 4  # 08:00Z -> 04:00 ET
    assert bars[0].session is Session.PRE
    assert bars[-1].ts.hour == 9 and bars[-1].ts.minute == 55
    assert bars[-1].session is Session.REGULAR
    assert bars[0].close == 730.2971


def test_bars_are_sorted_oldest_first():
    bars = parse_historicals(HISTORICALS)["SPY"]
    assert bars == sorted(bars, key=lambda b: b.ts)


def test_interpolated_bars_are_dropped():
    payload = {
        "data": {
            "results": [
                {
                    "symbol": "SPY",
                    "bars": [
                        {
                            "begins_at": "2026-07-30T13:30:00Z",
                            "open_price": "1",
                            "close_price": "1",
                            "high_price": "1",
                            "low_price": "1",
                            "volume": 1,
                            "session": "reg",
                        },
                        {
                            "begins_at": "2026-07-30T13:35:00Z",
                            "open_price": "1",
                            "close_price": "1",
                            "high_price": "1",
                            "low_price": "1",
                            "volume": 0,
                            "session": "reg",
                            "interpolated": True,
                        },
                    ],
                }
            ]
        }
    }
    assert len(parse_historicals(payload)["SPY"]) == 1


def test_premarket_levels_use_only_pre_session_bars():
    bars = parse_historicals(HISTORICALS)["SPY"]
    high, low = premarket_levels(bars, date(2026, 7, 30))
    assert high == 736.06
    assert low == 729.89


def test_opening_range_covers_the_first_fifteen_minutes():
    bars = parse_historicals(HISTORICALS)["SPY"]
    high, low = opening_range(bars, date(2026, 7, 30))
    # 09:30, 09:35, 09:40 bars only
    assert high == 736.79
    assert low == 734.6401


def test_build_levels_combines_both_feeds():
    bars = parse_historicals(HISTORICALS)["SPY"]
    regular = [b for b in bars if b.session is Session.REGULAR]
    premarket = [b for b in bars if b.session is Session.PRE]

    levels = build_levels(
        intraday_bars=regular,
        daily_bars=[],
        day=date(2026, 7, 30),
        price=739.0,
        premarket_bars=premarket,
    )
    assert levels.premarket_high == 736.06
    assert levels.premarket_low == 729.89
    assert levels.price == 739.0
    assert levels.vwap is not None
    # only six regular bars, so the 9/21 EMAs cannot be formed yet
    assert levels.ema_slow is None
    assert levels.sma_daily is None


def test_quotes_parse_with_previous_close():
    payload = {
        "data": {
            "quotes": [
                {
                    "symbol": "SPY",
                    "last_trade_price": "741.69",
                    "previous_close": "729.46",
                }
            ]
        }
    }
    quote = parse_quotes(payload)["SPY"]
    assert quote.price == 741.69
    assert round(quote.change_pct, 2) == 1.68


def test_empty_payload_parses_to_nothing():
    assert parse_historicals({}) == {}
    assert parse_quotes({}) == {}

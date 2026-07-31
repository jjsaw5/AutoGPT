"""Unusual Whales adapter tests.

Fixtures mirror the live payload shape confirmed against the API: `data`
as a list ordered oldest-first, premium values as decimal strings,
per-minute rows for net-prem-ticks and cumulative rows for sector-tide.
"""

import pytest

from odte.uw import (
    SECTOR_BY_ETF,
    UWContext,
    UnusualWhalesClient,
    _net,
    _scale_free,
    load_uw_context,
)


class StubResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class StubSession:
    """Records requested URLs and replays canned payloads."""

    def __init__(self, payloads):
        self._payloads = payloads
        self.urls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.urls.append(url)
        for fragment, payload in self._payloads.items():
            if fragment in url:
                return StubResponse(payload)
        raise AssertionError(f"unexpected url {url}")


def ticks(values):
    """Per-minute rows; each value is that minute's net call premium."""
    return {
        "data": [
            {
                "tape_time": f"2026-07-30T13:{i:02d}:00.000000Z",
                "net_call_premium": f"{v:.4f}",
                "net_put_premium": "0.00",
            }
            for i, v in enumerate(values)
        ]
    }


def tide(values):
    """Cumulative rows."""
    return {
        "data": [
            {
                "timestamp": f"2026-07-30T13:{i:02d}:00Z",
                "net_call_premium": f"{v:.4f}",
                "net_put_premium": "0.0000",
            }
            for i, v in enumerate(values)
        ]
    }


def test_net_parses_string_premiums_and_subtracts_puts():
    row = {"net_call_premium": "-293659.0000", "net_put_premium": "-5417986.00"}
    # puts sold (negative) is bullish, so it adds to the net
    assert _net(row) == pytest.approx(5124327.0)


def test_net_handles_missing_fields():
    assert _net({}) == 0.0


def test_scale_free_is_one_at_the_session_peak():
    assert _scale_free([10.0, -4.0, 10.0], 10.0) == 1.0


def test_scale_free_reports_faded_flow_as_near_zero():
    assert _scale_free([100.0, 50.0, 2.0], 2.0) == pytest.approx(0.02)


def test_scale_free_handles_an_all_zero_series():
    assert _scale_free([0.0, 0.0], 0.0) == 0.0


def test_net_premium_sums_a_trailing_window_not_the_last_minute():
    """The bug this replaced: one strong final minute after a flat session.

    Ten minutes of +1 followed by a single +50 spike. Reading only the last
    row scores a maximal +1.00; summing the trailing window keeps it modest.
    """
    session = StubSession({"net-prem-ticks": ticks([1.0] * 10 + [50.0])})
    client = UnusualWhalesClient(api_key="k", session=session)
    bias = client.net_premium_bias("SPY", window_minutes=5)
    assert bias == 1.0  # the spike window is the session peak here

    # but a session whose flow has faded scores near zero, which the
    # single-tick reading could never express
    faded = StubSession({"net-prem-ticks": ticks([100.0] * 30 + [0.5] * 30)})
    client = UnusualWhalesClient(api_key="k", session=faded)
    assert client.net_premium_bias("SPY", window_minutes=30) < 0.05


def test_net_premium_is_negative_for_bearish_flow():
    session = StubSession({"net-prem-ticks": ticks([-5.0] * 30)})
    client = UnusualWhalesClient(api_key="k", session=session)
    assert client.net_premium_bias("SPY", window_minutes=10) == -1.0


def test_net_premium_of_empty_data_is_neutral():
    session = StubSession({"net-prem-ticks": {"data": []}})
    client = UnusualWhalesClient(api_key="k", session=session)
    assert client.net_premium_bias("SPY") == 0.0


def test_sector_tide_uses_the_cumulative_last_row():
    session = StubSession({"sector-tide": tide([10.0, 50.0, 100.0])})
    client = UnusualWhalesClient(api_key="k", session=session)
    assert client.sector_tide_bias("Technology") == 1.0


def test_sector_tide_scores_a_fading_cumulative_tide_below_its_peak():
    session = StubSession({"sector-tide": tide([10.0, 100.0, 40.0])})
    client = UnusualWhalesClient(api_key="k", session=session)
    assert client.sector_tide_bias("Technology") == pytest.approx(0.4)


def test_sector_etf_ticker_is_mapped_to_a_sector_name():
    """Passing XLK directly returns 400 Invalid sector from the live API."""
    session = StubSession({"sector-tide": tide([1.0])})
    client = UnusualWhalesClient(api_key="k", session=session)
    client.sector_tide_bias("XLK")
    assert "Technology" in session.urls[0]
    assert "XLK" not in session.urls[0]


def test_sector_map_covers_the_tech_proxy():
    assert SECTOR_BY_ETF["XLK"] == "Technology"


def test_error_payload_raises():
    session = StubSession({"sector-tide": {"error": "Invalid sector: XLK"}})
    client = UnusualWhalesClient(api_key="k", session=session)
    with pytest.raises(RuntimeError, match="Invalid sector"):
        client.sector_tide_bias("Technology")


def test_context_bias_averages_both_components():
    context = UWContext(net_premium_bias=0.8, sector_tide_bias=0.4, available=True)
    assert context.bias == pytest.approx(0.6)


def test_unavailable_context_contributes_nothing():
    assert UWContext(net_premium_bias=1.0, available=False).bias == 0.0


def test_load_returns_none_without_a_key(monkeypatch):
    monkeypatch.delenv("UW_API_KEY", raising=False)
    assert load_uw_context("SPY") is None


def test_load_returns_none_when_disabled():
    assert load_uw_context("SPY", enabled=False) is None


def test_load_degrades_gracefully_when_the_api_fails(monkeypatch):
    monkeypatch.setenv("UW_API_KEY", "k")

    def boom(*args, **kwargs):
        raise RuntimeError("503")

    monkeypatch.setattr(UnusualWhalesClient, "net_premium_bias", boom)
    context = load_uw_context("SPY")
    assert context is not None
    assert context.available is False
    assert context.bias == 0.0
    assert "uw unavailable" in context.detail

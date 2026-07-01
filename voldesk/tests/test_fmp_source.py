"""Tests for voldesk.sources.fmp.FmpClient.

All tests inject a fake ``transport`` callable that returns canned JSON --
no real HTTP calls are made.
"""

from __future__ import annotations

import pytest

from voldesk.sources.fmp import FmpApiError, FmpClient


def _canned_transport(responses):
    """Build a transport that returns responses[url] and records calls."""
    calls = []

    def transport(url):
        calls.append(url)
        for prefix, response in responses.items():
            if prefix in url:
                return response
        raise AssertionError(f"No canned response registered for URL: {url}")

    transport.calls = calls
    return transport


class TestGetOptionChain:
    def test_normalizes_records_with_chosen_alias_names(self):
        raw = [
            {
                "strike": 100.0,
                "optionType": "call",
                "openInterest": 250,
                "volume": 40,
                "impliedVolatility": 0.32,
                "expirationDate": "2026-08-21",
            },
            {
                "strikePrice": 95.0,
                "type": "PUT",
                "open_interest": 300,
                "totalVolume": 60,
                "iv": 0.41,
                "expiration": "2026-08-21",
            },
        ]
        transport = _canned_transport({"options-chain": raw})
        client = FmpClient(api_key="fake-key", transport=transport)

        contracts = client.get_option_chain("TSLA")

        assert len(contracts) == 2
        c1, c2 = contracts
        assert c1.strike == 100.0
        assert c1.option_type == "call"
        assert c1.open_interest == 250
        assert c1.volume == 40
        assert c1.implied_volatility == 0.32
        assert c1.expiration == "2026-08-21"

        assert c2.strike == 95.0
        assert c2.option_type == "put"
        assert c2.open_interest == 300
        assert c2.volume == 60
        assert c2.implied_volatility == 0.41

    def test_missing_required_field_raises_value_error(self):
        raw = [
            {
                "strike": 100.0,
                # option type missing entirely
                "openInterest": 250,
                "impliedVolatility": 0.32,
                "expirationDate": "2026-08-21",
            },
        ]
        transport = _canned_transport({"options-chain": raw})
        client = FmpClient(api_key="fake-key", transport=transport)

        with pytest.raises(ValueError, match="option_type"):
            client.get_option_chain("TSLA")

    def test_missing_open_interest_raises_value_error_not_defaulted(self):
        raw = [
            {
                "strike": 100.0,
                "optionType": "call",
                "impliedVolatility": 0.32,
                "expirationDate": "2026-08-21",
            },
        ]
        transport = _canned_transport({"options-chain": raw})
        client = FmpClient(api_key="fake-key", transport=transport)

        with pytest.raises(ValueError, match="open_interest"):
            client.get_option_chain("TSLA")

    def test_missing_volume_defaults_to_zero(self):
        raw = [
            {
                "strike": 100.0,
                "optionType": "call",
                "openInterest": 250,
                "impliedVolatility": 0.32,
                "expirationDate": "2026-08-21",
            },
        ]
        transport = _canned_transport({"options-chain": raw})
        client = FmpClient(api_key="fake-key", transport=transport)

        contracts = client.get_option_chain("TSLA")
        assert contracts[0].volume == 0.0

    def test_wrapped_response_shape(self):
        raw = {
            "data": [
                {
                    "strike": 100.0,
                    "optionType": "call",
                    "openInterest": 10,
                    "impliedVolatility": 0.2,
                    "expirationDate": "2026-08-21",
                }
            ]
        }
        transport = _canned_transport({"options-chain": raw})
        client = FmpClient(api_key="fake-key", transport=transport)
        contracts = client.get_option_chain("TSLA")
        assert len(contracts) == 1

    def test_unexpected_shape_raises_fmp_api_error(self):
        transport = _canned_transport({"options-chain": {"unexpected": "shape"}})
        client = FmpClient(api_key="fake-key", transport=transport)
        with pytest.raises(FmpApiError):
            client.get_option_chain("TSLA")

    def test_request_url_includes_symbol_and_apikey(self):
        transport = _canned_transport({"options-chain": []})
        client = FmpClient(api_key="secret123", transport=transport)
        client.get_option_chain("TSLA", expiration="2026-08-21")
        assert len(transport.calls) == 1
        url = transport.calls[0]
        assert "symbol=TSLA" in url
        assert "apikey=secret123" in url
        assert "expiration=2026-08-21" in url


class TestGetQuote:
    def test_get_quote_price_resolves_alias(self):
        transport = _canned_transport({"quote": [{"symbol": "TSLA", "price": 251.30}]})
        client = FmpClient(api_key="fake-key", transport=transport)
        price = client.get_quote_price("TSLA")
        assert price == 251.30

    def test_get_quote_missing_price_raises(self):
        transport = _canned_transport({"quote": [{"symbol": "TSLA"}]})
        client = FmpClient(api_key="fake-key", transport=transport)
        with pytest.raises(ValueError, match="price"):
            client.get_quote("TSLA")

    def test_get_quote_empty_list_raises_fmp_api_error(self):
        transport = _canned_transport({"quote": []})
        client = FmpClient(api_key="fake-key", transport=transport)
        with pytest.raises(FmpApiError):
            client.get_quote("TSLA")


class TestClientConstruction:
    def test_requires_api_key(self):
        with pytest.raises(ValueError):
            FmpClient(api_key="")

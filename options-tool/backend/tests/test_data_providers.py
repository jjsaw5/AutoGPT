"""Mock provider + cache coverage. Protocol compliance tested at import-time."""
from __future__ import annotations

import time
from datetime import timedelta

import pytest

from app.data.base import DataProvider
from app.data.cache import ChainCache
from app.data.mock_provider import MockProvider


def test_mock_provider_is_data_provider() -> None:
    assert isinstance(MockProvider(), DataProvider)


def test_mock_provider_chain_has_both_rights_and_realistic_deltas(mock_provider: MockProvider) -> None:
    chain = mock_provider.get_chain("TEST")
    calls = [c for c in chain.contracts if c.right.value == "C"]
    puts = [c for c in chain.contracts if c.right.value == "P"]
    assert calls and puts
    # ATM call delta should be near 0.5, not negative; ATM put near -0.5.
    atm_call = min(calls, key=lambda c: abs(c.strike - chain.spot))
    atm_put = min(puts, key=lambda c: abs(c.strike - chain.spot))
    assert atm_call.delta is not None and 0.3 < atm_call.delta < 0.7
    assert atm_put.delta is not None and -0.7 < atm_put.delta < -0.3


def test_mock_provider_chain_has_expected_expiries(mock_provider: MockProvider) -> None:
    chain = mock_provider.get_chain("TEST")
    dtes = sorted((e - mock_provider.now().date()).days for e in chain.expiries())
    assert dtes == [7, 30, 45, 60, 90]


def test_mock_provider_iv_history_length_and_shape(mock_provider: MockProvider) -> None:
    history = mock_provider.get_iv_history("TEST", lookback_days=252)
    assert len(history) == 252
    assert all(0 < p.atm_iv < 1 for p in history)
    # Last point should equal base_iv to keep chain and history in sync.
    assert history[-1].atm_iv == pytest.approx(0.30)


def test_chain_cache_round_trip(cache: ChainCache) -> None:
    cache.set("mock", "chain", "SPY", {"foo": 1})
    assert cache.get("mock", "chain", "SPY") == {"foo": 1}


def test_chain_cache_expires(tmp_path) -> None:  # type: ignore[no-untyped-def]
    cache = ChainCache(path=tmp_path / "c.db", ttl_seconds=0)
    cache.set("mock", "chain", "SPY", {"foo": 1})
    time.sleep(0.01)
    assert cache.get("mock", "chain", "SPY") is None


def test_mock_provider_respects_requested_expiry(mock_provider: MockProvider) -> None:
    today = mock_provider.now().date()
    chain = mock_provider.get_chain("TEST", expiry=today + timedelta(days=45))
    assert chain.expiries() == [today + timedelta(days=45)]

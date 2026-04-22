"""Pytest fixtures shared across modules."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.models import Account
from app.data.cache import ChainCache
from app.data.mock_provider import MockProvider
from app.strategists.sosnoff import SosnoffStrategist


@pytest.fixture
def as_of() -> datetime:
    return datetime(2026, 4, 22, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def mock_provider(as_of: datetime) -> MockProvider:
    """Spot=100, base_iv=0.30, IV history 0.18–0.55 -> current IV sits near the low."""
    return MockProvider(spot=100.0, base_iv=0.30, as_of=as_of)


@pytest.fixture
def high_ivr_provider(as_of: datetime) -> MockProvider:
    """base_iv=0.52 sits near the top of 0.18–0.55 -> IVR ~92."""
    return MockProvider(spot=100.0, base_iv=0.52, as_of=as_of)


@pytest.fixture
def mid_ivr_provider(as_of: datetime) -> MockProvider:
    """base_iv=0.34 -> IVR ~43, inside the condor band."""
    return MockProvider(spot=100.0, base_iv=0.34, as_of=as_of)


@pytest.fixture
def low_ivr_provider(as_of: datetime) -> MockProvider:
    """base_iv=0.20 -> IVR <30, Sosnoff should skip."""
    return MockProvider(spot=100.0, base_iv=0.20, as_of=as_of)


@pytest.fixture
def account() -> Account:
    return Account(cash=100_000, kelly_fraction=0.25, max_pct_per_trade=0.05)


@pytest.fixture
def sosnoff(mid_ivr_provider: MockProvider) -> SosnoffStrategist:
    return SosnoffStrategist(provider=mid_ivr_provider)


@pytest.fixture
def cache(tmp_path) -> ChainCache:  # type: ignore[no-untyped-def]
    return ChainCache(path=tmp_path / "cache.db", ttl_seconds=60)

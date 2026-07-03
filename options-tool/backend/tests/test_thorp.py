"""Thorp strategist tests."""
from __future__ import annotations

from copy import deepcopy

import pytest

from app.core.models import Account, OptionChain, OptionRight
from app.data.mock_provider import MockProvider
from app.strategists.thorp import ThorpStrategist


def _inject_mispricing(chain: OptionChain, strike: float, right: OptionRight, delta_iv: float) -> OptionChain:
    """Return a copy of the chain with one contract's IV nudged."""
    new = deepcopy(chain)
    for c in new.contracts:
        if (
            c.strike == strike
            and c.right is right
            and (c.expiry - new.as_of.date()).days == 45
        ):
            c.implied_vol = (c.implied_vol or 0.3) + delta_iv
    return new


def test_thorp_skips_when_surface_is_flat(mock_provider: MockProvider) -> None:
    """Mock chain uses the same formula Thorp fits; there should be no edge."""
    strategist = ThorpStrategist(provider=mock_provider)
    chain = mock_provider.get_chain("TEST")
    setup = strategist.analyze("TEST", chain)
    assert setup is not None
    assert setup.strategy == "skip"


def test_thorp_flags_overpriced_contract_as_sell(mock_provider: MockProvider) -> None:
    chain = _inject_mispricing(mock_provider.get_chain("TEST"), 106.0, OptionRight.CALL, +0.10)
    setup = ThorpStrategist(provider=mock_provider).analyze("TEST", chain)
    assert setup is not None
    assert setup.strategy.startswith("thorp_edge")
    primary = setup.legs[0]
    # Overpriced -> sell -> negative quantity on the primary leg.
    assert primary.quantity < 0
    assert primary.contract.right is OptionRight.CALL
    assert primary.contract.strike == 106.0


def test_thorp_flags_underpriced_contract_as_buy(mock_provider: MockProvider) -> None:
    chain = _inject_mispricing(mock_provider.get_chain("TEST"), 94.0, OptionRight.PUT, -0.08)
    setup = ThorpStrategist(provider=mock_provider).analyze("TEST", chain)
    assert setup is not None
    assert setup.strategy.startswith("thorp_edge")
    primary = setup.legs[0]
    assert primary.quantity > 0  # underpriced -> buy
    assert primary.contract.right is OptionRight.PUT


def test_thorp_pair_includes_opposite_right_hedge(mock_provider: MockProvider) -> None:
    chain = _inject_mispricing(mock_provider.get_chain("TEST"), 106.0, OptionRight.CALL, +0.10)
    setup = ThorpStrategist(provider=mock_provider).analyze("TEST", chain)
    assert setup is not None
    assert setup.strategy == "thorp_edge_pair"
    rights = {leg.contract.right for leg in setup.legs}
    assert rights == {OptionRight.CALL, OptionRight.PUT}


def test_thorp_size_capped_by_max_pct_per_trade(
    mock_provider: MockProvider, account: Account
) -> None:
    chain = _inject_mispricing(mock_provider.get_chain("TEST"), 106.0, OptionRight.CALL, +0.20)
    strategist = ThorpStrategist(provider=mock_provider)
    setup = strategist.analyze("TEST", chain)
    assert setup is not None
    sized = strategist.size(setup, account)
    assert sized.capital_at_risk <= account.cash * account.max_pct_per_trade + 1e-6


def test_thorp_size_returns_zero_when_no_edge(
    mock_provider: MockProvider, account: Account
) -> None:
    strategist = ThorpStrategist(provider=mock_provider)
    setup = strategist.analyze("TEST", mock_provider.get_chain("TEST"))
    assert setup is not None
    sized = strategist.size(setup, account)
    assert sized.contracts == 0

"""Saliba strategist tests."""
from __future__ import annotations

import pytest

from app.core.models import Account, ManagementVerdict, MarketSnapshot, Position, PositionSize
from app.data.mock_provider import MockProvider
from app.strategists.saliba import SalibaConfig, SalibaStrategist


def test_saliba_returns_defined_risk_setup(mock_provider: MockProvider) -> None:
    strategist = SalibaStrategist(provider=mock_provider)
    setup = strategist.analyze("TEST", mock_provider.get_chain("TEST"))
    assert setup is not None
    # All Saliba trades except 'skip' are defined-risk with 3+ legs.
    if setup.strategy != "skip":
        assert len(setup.legs) >= 3
        assert setup.max_loss > 0
        assert setup.pop is not None


def test_saliba_rr_threshold_filters_weak_candidates(mock_provider: MockProvider) -> None:
    strict = SalibaStrategist(provider=mock_provider, config=SalibaConfig(min_reward_risk=50.0))
    setup = strict.analyze("TEST", mock_provider.get_chain("TEST"))
    assert setup is not None and setup.strategy == "skip"


def test_saliba_breakevens_bracket_profit_zone(mock_provider: MockProvider) -> None:
    strategist = SalibaStrategist(provider=mock_provider)
    setup = strategist.analyze("TEST", mock_provider.get_chain("TEST"))
    assert setup is not None
    if setup.strategy != "skip":
        assert len(setup.breakevens) == 2
        lo, hi = sorted(setup.breakevens)
        assert lo < hi


def test_saliba_size_respects_account_caps(
    mock_provider: MockProvider, account: Account
) -> None:
    strategist = SalibaStrategist(provider=mock_provider)
    setup = strategist.analyze("TEST", mock_provider.get_chain("TEST"))
    assert setup is not None
    sized = strategist.size(setup, account)
    assert sized.capital_at_risk <= account.cash * account.max_pct_per_trade + 1e-6


def test_saliba_close_winner_at_50_pct(mock_provider: MockProvider) -> None:
    strategist = SalibaStrategist(provider=mock_provider)
    setup = strategist.analyze("TEST", mock_provider.get_chain("TEST"))
    assert setup is not None and setup.strategy != "skip"
    contracts = 2
    max_profit_dollars = setup.max_profit * 100 * contracts
    pos = Position(
        setup=setup,
        size=PositionSize(
            contracts=contracts,
            capital_at_risk=setup.max_loss * 100 * contracts,
            pct_of_account=0.05,
            rationale="test",
        ),
        opened_at=mock_provider.now(),
        current_pnl=max_profit_dollars * 0.6,
    )
    action = strategist.manage(
        pos, MarketSnapshot(ticker="TEST", spot=mock_provider.get_chain("TEST").spot, as_of=mock_provider.now())
    )
    assert action.verdict == ManagementVerdict.CLOSE_WINNER

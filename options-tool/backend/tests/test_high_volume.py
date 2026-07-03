"""HighVolume strategist tests — the *guardrail* rules are the point."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.models import (
    CONTRACT_MULTIPLIER,
    Account,
    JournalEntry,
    JournalOutcome,
    ManagementVerdict,
    MarketSnapshot,
    Position,
    PositionSize,
)
from app.data.mock_provider import MockProvider
from app.risk.guard import RiskCaps
from app.strategists.high_volume import HighVolumeStrategist


def test_high_volume_produces_undefined_risk_strangle(mock_provider: MockProvider) -> None:
    strategist = HighVolumeStrategist(provider=mock_provider)
    setup = strategist.analyze("SPY", mock_provider.get_chain("SPY"))
    assert setup is not None
    assert setup.strategy == "wide_short_strangle"
    assert setup.max_theoretical_loss is not None and setup.max_theoretical_loss > 0
    # No stop-loss by design — the whole module's deal.
    assert setup.stop_loss is None
    # But the notes must make that explicit.
    assert any("UNDEFINED RISK" in n for n in setup.notes)


def test_high_volume_blocks_new_entries_over_daily_loss_cap(
    mock_provider: MockProvider,
) -> None:
    now = mock_provider.now()
    losing_entry = JournalEntry(
        ticker="SPY",
        strategy="wide_short_strangle",
        strategist="high_volume",
        thesis="stale",
        opened_at=now - timedelta(hours=2),
        closed_at=now - timedelta(minutes=5),
        contracts=10,
        entry_credit=0.5,
        max_loss=10.0,
        outcome=JournalOutcome.LOSS,
        realized_pnl=-2_000,  # over default $1500 cap
    )
    strategist = HighVolumeStrategist(
        provider=mock_provider,
        journal=[losing_entry],
        risk_caps=RiskCaps(max_daily_loss=1_500),
    )
    setup = strategist.analyze("SPY", mock_provider.get_chain("SPY"))
    assert setup is not None
    assert setup.strategy == "skip"
    assert "Daily loss" in setup.thesis


def test_high_volume_scale_in_recommended_when_losing_and_under_cap(
    mock_provider: MockProvider,
) -> None:
    strategist = HighVolumeStrategist(provider=mock_provider)
    setup = strategist.analyze("SPY", mock_provider.get_chain("SPY"))
    assert setup is not None and setup.strategy == "wide_short_strangle"
    contracts = 2
    max_profit_dollars = setup.max_profit * CONTRACT_MULTIPLIER * contracts
    position = Position(
        setup=setup,
        size=PositionSize(
            contracts=contracts,
            capital_at_risk=setup.max_loss * CONTRACT_MULTIPLIER * contracts,
            pct_of_account=0.05,
            rationale="test",
        ),
        opened_at=mock_provider.now(),
        current_pnl=-0.9 * max_profit_dollars,
    )
    action = strategist.manage(
        position, MarketSnapshot(ticker="SPY", spot=100.0, as_of=mock_provider.now())
    )
    assert action.verdict == ManagementVerdict.ADJUST
    assert "Scale-in permitted" in action.reason


def test_high_volume_scale_in_refused_when_at_cap(mock_provider: MockProvider) -> None:
    strategist = HighVolumeStrategist(
        provider=mock_provider, risk_caps=RiskCaps(max_contracts_per_ticker=3)
    )
    setup = strategist.analyze("SPY", mock_provider.get_chain("SPY"))
    assert setup is not None
    # Position already at the cap.
    contracts = 3
    position = Position(
        setup=setup,
        size=PositionSize(
            contracts=contracts,
            capital_at_risk=setup.max_loss * CONTRACT_MULTIPLIER * contracts,
            pct_of_account=0.05,
            rationale="test",
        ),
        opened_at=mock_provider.now(),
        current_pnl=-0.9 * setup.max_profit * CONTRACT_MULTIPLIER * contracts,
    )
    action = strategist.manage(
        position, MarketSnapshot(ticker="SPY", spot=100.0, as_of=mock_provider.now())
    )
    assert action.verdict == ManagementVerdict.CLOSE_TIME


def test_high_volume_size_respects_risk_guard(
    mock_provider: MockProvider, account: Account
) -> None:
    # Force a blocked state by planting a maxed-out losing journal.
    losing = JournalEntry(
        ticker="SPY",
        strategy="wide_short_strangle",
        strategist="high_volume",
        thesis="stale",
        opened_at=mock_provider.now() - timedelta(hours=2),
        closed_at=mock_provider.now() - timedelta(minutes=5),
        contracts=10,
        entry_credit=0.5,
        max_loss=10.0,
        outcome=JournalOutcome.LOSS,
        realized_pnl=-5_000,
    )
    strategist = HighVolumeStrategist(
        provider=mock_provider,
        journal=[losing],
        risk_caps=RiskCaps(max_daily_loss=1_500),
    )
    # Re-analyse normally elsewhere, but try sizing an arbitrary setup manually.
    setup = strategist.analyze("SPY", mock_provider.get_chain("SPY"))
    assert setup is not None
    # analyze() returned a skip because of the guard; sizing it still yields zero.
    sized = strategist.size(setup, account)
    assert sized.contracts == 0

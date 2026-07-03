"""0DTE strategist tests — guardrails first."""
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
from app.strategists.zero_dte import ALLOWED_UNIVERSE, ZeroDTEStrategist


def test_zero_dte_rejects_tickers_outside_allowed_universe(
    mock_provider: MockProvider,
) -> None:
    setup = ZeroDTEStrategist(provider=mock_provider).analyze(
        "AAPL", mock_provider.get_chain("AAPL")
    )
    assert setup is not None and setup.strategy == "skip"
    assert "0DTE only trades" in setup.thesis


def test_zero_dte_builds_setup_with_mandatory_stop_loss(
    mock_provider: MockProvider,
) -> None:
    setup = ZeroDTEStrategist(provider=mock_provider).analyze(
        "SPY", mock_provider.get_chain("SPY")
    )
    assert setup is not None
    assert setup.strategy != "skip"
    assert setup.stop_loss is not None
    assert setup.stop_loss.dollar_loss > 0
    # Must advertise itself as 0 DTE.
    assert setup.dte == 0
    # max_theoretical_loss surfaced even for a long option.
    assert setup.max_theoretical_loss is not None


def test_zero_dte_manage_closes_on_stop_hit(mock_provider: MockProvider) -> None:
    strategist = ZeroDTEStrategist(provider=mock_provider)
    setup = strategist.analyze("SPY", mock_provider.get_chain("SPY"))
    assert setup is not None and setup.stop_loss is not None
    contracts = 2
    pos = Position(
        setup=setup,
        size=PositionSize(
            contracts=contracts,
            capital_at_risk=setup.max_loss * CONTRACT_MULTIPLIER * contracts,
            pct_of_account=0.01,
            rationale="test",
        ),
        opened_at=mock_provider.now(),
        current_pnl=-setup.stop_loss.dollar_loss * contracts - 1,
    )
    action = strategist.manage(
        pos, MarketSnapshot(ticker="SPY", spot=100.0, as_of=mock_provider.now())
    )
    assert action.verdict == ManagementVerdict.CLOSE_TIME
    assert "stop" in action.reason.lower()


def test_zero_dte_session_circuit_breaker_halts_new_entries(
    mock_provider: MockProvider,
) -> None:
    now = mock_provider.now()
    losses = [
        JournalEntry(
            ticker="SPY",
            strategy="zero_dte_long_atm",
            strategist="zero_dte",
            thesis="stale",
            opened_at=now - timedelta(minutes=60 - 10 * i),
            closed_at=now - timedelta(minutes=55 - 10 * i),
            contracts=1,
            entry_credit=-1.0,
            max_loss=1.0,
            outcome=JournalOutcome.LOSS,
            realized_pnl=-60,
        )
        for i in range(3)
    ]
    strategist = ZeroDTEStrategist(
        provider=mock_provider,
        journal=losses,
        risk_caps=RiskCaps(session_max_consecutive_losses=3, session_max_drawdown_pct=None),
    )
    setup = strategist.analyze("SPY", mock_provider.get_chain("SPY"))
    assert setup is not None and setup.strategy == "skip"
    assert "circuit breaker" in setup.thesis.lower()


def test_zero_dte_size_blocks_when_session_halted(mock_provider: MockProvider) -> None:
    now = mock_provider.now()
    losses = [
        JournalEntry(
            ticker="SPY",
            strategy="zero_dte_long_atm",
            strategist="zero_dte",
            thesis="stale",
            opened_at=now - timedelta(minutes=60 - 10 * i),
            closed_at=now - timedelta(minutes=55 - 10 * i),
            contracts=1,
            entry_credit=-1.0,
            max_loss=1.0,
            outcome=JournalOutcome.LOSS,
            realized_pnl=-60,
        )
        for i in range(3)
    ]
    # Build a normal setup first (empty journal), then size it with halted journal.
    strategist = ZeroDTEStrategist(provider=mock_provider)
    setup = strategist.analyze("SPY", mock_provider.get_chain("SPY"))
    assert setup is not None and setup.strategy != "skip"
    halted = ZeroDTEStrategist(
        provider=mock_provider,
        journal=losses,
        risk_caps=RiskCaps(session_max_consecutive_losses=3, session_max_drawdown_pct=None),
    )
    sized = halted.size(setup, Account(cash=100_000))
    assert sized.contracts == 0
    assert "circuit breaker" in sized.rationale.lower()


def test_allowed_universe_contains_spx_spy_qqq() -> None:
    assert {"SPX", "SPY", "QQQ"} <= ALLOWED_UNIVERSE

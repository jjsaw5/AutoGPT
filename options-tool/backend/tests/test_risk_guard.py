"""RiskGuard unit tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.models import Account, JournalEntry, JournalOutcome
from app.risk.guard import RiskCaps, RiskGuard, RiskVerdict


def _entry(
    *,
    ticker: str = "SPY",
    opened_at: datetime | None = None,
    closed_at: datetime | None = None,
    realized_pnl: float = 0.0,
    outcome: JournalOutcome = JournalOutcome.OPEN,
    contracts: int = 5,
    max_loss: float = 2.0,
) -> JournalEntry:
    t0 = opened_at or datetime(2026, 4, 22, 13, 30, tzinfo=timezone.utc)
    return JournalEntry(
        ticker=ticker,
        strategy="test",
        strategist="test",
        thesis="test",
        opened_at=t0,
        closed_at=closed_at,
        contracts=contracts,
        entry_credit=1.0,
        max_loss=max_loss,
        outcome=outcome,
        realized_pnl=realized_pnl,
    )


def test_allow_with_empty_journal() -> None:
    guard = RiskGuard()
    decision = guard.check_entry(
        ticker="SPY",
        proposed_contracts=2,
        account=Account(cash=100_000),
        journal=[],
        as_of=datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc),
    )
    assert decision.verdict is RiskVerdict.ALLOW
    assert decision.allowed is True


def test_blocks_on_per_ticker_cap() -> None:
    guard = RiskGuard(caps=RiskCaps(max_contracts_per_ticker=10))
    entries = [_entry(contracts=8, outcome=JournalOutcome.OPEN)]
    decision = guard.check_entry(
        ticker="SPY",
        proposed_contracts=3,
        account=Account(cash=100_000),
        journal=entries,
        as_of=datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc),
    )
    assert decision.verdict is RiskVerdict.BLOCK_TICKER_CAP


def test_blocks_on_daily_loss_cap() -> None:
    guard = RiskGuard(caps=RiskCaps(max_daily_loss=1_000))
    now = datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc)
    entries = [
        _entry(
            closed_at=now - timedelta(minutes=5),
            realized_pnl=-1_200,
            outcome=JournalOutcome.LOSS,
            ticker="IWM",
        )
    ]
    decision = guard.check_entry(
        ticker="SPY",
        proposed_contracts=1,
        account=Account(cash=100_000),
        journal=entries,
        as_of=now,
    )
    assert decision.verdict is RiskVerdict.BLOCK_DAILY_LOSS


def test_blocks_on_weekly_loss_cap() -> None:
    guard = RiskGuard(caps=RiskCaps(max_weekly_loss=2_000))
    now = datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc)
    entries = [
        _entry(
            opened_at=now - timedelta(days=i, hours=1),
            closed_at=now - timedelta(days=i),
            realized_pnl=-800,
            outcome=JournalOutcome.LOSS,
            ticker="SPY",
        )
        for i in range(1, 4)  # 3 days ago, 2 days ago, 1 day ago -> $2,400 loss
    ]
    decision = guard.check_entry(
        ticker="SPY",
        proposed_contracts=1,
        account=Account(cash=100_000),
        journal=entries,
        as_of=now,
    )
    assert decision.verdict is RiskVerdict.BLOCK_WEEKLY_LOSS


def test_session_mode_halts_on_consecutive_losses() -> None:
    guard = RiskGuard(caps=RiskCaps(session_max_consecutive_losses=3))
    now = datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc)
    entries = [
        _entry(
            opened_at=now - timedelta(minutes=60 - 10 * i),
            closed_at=now - timedelta(minutes=55 - 10 * i),
            realized_pnl=-200,
            outcome=JournalOutcome.LOSS,
        )
        for i in range(3)
    ]
    decision = guard.check_entry(
        ticker="SPY",
        proposed_contracts=1,
        account=Account(cash=100_000),
        journal=entries,
        as_of=now,
        session_only=True,
    )
    assert decision.verdict is RiskVerdict.BLOCK_CONSECUTIVE_LOSSES


def test_session_mode_halts_on_drawdown() -> None:
    guard = RiskGuard(caps=RiskCaps(session_max_drawdown_pct=0.02))
    now = datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc)
    entries = [
        _entry(
            opened_at=now - timedelta(minutes=30),
            closed_at=now - timedelta(minutes=25),
            realized_pnl=-2_500,  # 2.5% of 100k -> over 2% cap
            outcome=JournalOutcome.LOSS,
        )
    ]
    decision = guard.check_entry(
        ticker="SPY",
        proposed_contracts=1,
        account=Account(cash=100_000),
        journal=entries,
        as_of=now,
        session_only=True,
    )
    assert decision.verdict is RiskVerdict.BLOCK_SESSION_DRAWDOWN


def test_session_mode_allows_when_last_trade_was_a_win() -> None:
    """Consecutive-loss counter must reset after a winning trade."""
    guard = RiskGuard(caps=RiskCaps(session_max_consecutive_losses=2))
    now = datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc)
    entries = [
        _entry(
            opened_at=now - timedelta(minutes=50),
            closed_at=now - timedelta(minutes=45),
            realized_pnl=-200,
            outcome=JournalOutcome.LOSS,
        ),
        _entry(
            opened_at=now - timedelta(minutes=40),
            closed_at=now - timedelta(minutes=35),
            realized_pnl=-200,
            outcome=JournalOutcome.LOSS,
        ),
        _entry(
            opened_at=now - timedelta(minutes=20),
            closed_at=now - timedelta(minutes=15),
            realized_pnl=+400,
            outcome=JournalOutcome.WIN,
        ),
    ]
    decision = guard.check_entry(
        ticker="SPY",
        proposed_contracts=1,
        account=Account(cash=100_000),
        journal=entries,
        as_of=now,
        session_only=True,
    )
    assert decision.verdict is RiskVerdict.ALLOW

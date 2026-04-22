"""Journal storage + analytics."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.models import JournalEntry, JournalOutcome
from app.journal.analytics import compute_analytics
from app.journal.store import TradeJournal


def _entry(**overrides: object) -> JournalEntry:
    defaults: dict[str, object] = dict(
        ticker="SPY",
        strategy="iron_condor",
        strategist="sosnoff",
        thesis="test",
        opened_at=datetime(2026, 4, 22, 13, 30, tzinfo=timezone.utc),
        contracts=5,
        entry_credit=1.50,
        max_loss=3.50,
        outcome=JournalOutcome.OPEN,
        realized_pnl=0.0,
    )
    defaults.update(overrides)
    return JournalEntry(**defaults)  # type: ignore[arg-type]


def test_journal_round_trip_in_memory() -> None:
    j = TradeJournal(":memory:")
    recorded = j.record(_entry())
    assert recorded.id is not None
    fetched = j.get(recorded.id)
    assert fetched is not None
    assert fetched.ticker == "SPY"
    assert fetched.outcome is JournalOutcome.OPEN


def test_journal_close_updates_outcome_and_pnl() -> None:
    j = TradeJournal(":memory:")
    recorded = j.record(_entry())
    assert recorded.id is not None
    updated = j.close(
        recorded.id,
        exit_credit=0.75,
        realized_pnl=350.0,
        closed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
        outcome=JournalOutcome.WIN,
    )
    assert updated is not None
    assert updated.outcome is JournalOutcome.WIN
    assert updated.realized_pnl == 350.0


def test_journal_list_filters_ticker_and_strategist() -> None:
    j = TradeJournal(":memory:")
    j.record(_entry(ticker="SPY", strategist="sosnoff"))
    j.record(_entry(ticker="QQQ", strategist="thorp"))
    j.record(_entry(ticker="SPY", strategist="thorp"))
    assert len(j.list(ticker="SPY")) == 2
    assert len(j.list(strategist="thorp")) == 2
    assert len(j.list(ticker="SPY", strategist="thorp")) == 1


def test_r_multiple_on_closed_loss() -> None:
    e = _entry(
        contracts=2,
        max_loss=2.0,
        outcome=JournalOutcome.LOSS,
        realized_pnl=-400.0,
        closed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
    )
    # risk = 2 * 2 * 100 = $400 -> R = -1.0
    assert e.r_multiple == pytest.approx(-1.0)


def test_r_multiple_is_none_while_open() -> None:
    assert _entry().r_multiple is None


def test_analytics_counts_are_consistent() -> None:
    entries = [
        _entry(outcome=JournalOutcome.WIN, realized_pnl=200, closed_at=datetime(2026, 4, 23, tzinfo=timezone.utc)),
        _entry(outcome=JournalOutcome.LOSS, realized_pnl=-100, closed_at=datetime(2026, 4, 23, tzinfo=timezone.utc)),
        _entry(outcome=JournalOutcome.WIN, realized_pnl=300, closed_at=datetime(2026, 4, 23, tzinfo=timezone.utc)),
        _entry(outcome=JournalOutcome.OPEN),
    ]
    a = compute_analytics(entries)
    assert a.trades == 4
    assert a.closed_trades == 3
    assert a.open_trades == 1
    assert a.wins == 2 and a.losses == 1
    assert a.win_rate == pytest.approx(2 / 3)
    assert a.profit_factor == pytest.approx(500 / 100)


def test_analytics_surfaces_kelly_drift() -> None:
    e = _entry(
        planned_size_contracts=3,
        contracts=10,
        outcome=JournalOutcome.WIN,
        realized_pnl=500,
        closed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
    )
    a = compute_analytics([e])
    assert len(a.kelly_implied_vs_actual) == 1
    drift = a.kelly_implied_vs_actual[0]
    assert drift["planned"] == 3
    assert drift["actual"] == 10
    assert drift["drift_pct"] == pytest.approx((10 - 3) / 3)


def test_analytics_breaks_down_by_strategist() -> None:
    entries = [
        _entry(strategist="sosnoff", outcome=JournalOutcome.WIN, realized_pnl=200, closed_at=datetime(2026, 4, 23, tzinfo=timezone.utc)),
        _entry(strategist="thorp", outcome=JournalOutcome.LOSS, realized_pnl=-300, closed_at=datetime(2026, 4, 23, tzinfo=timezone.utc)),
    ]
    a = compute_analytics(entries)
    assert set(a.by_strategist.keys()) == {"sosnoff", "thorp"}
    assert a.by_strategist["sosnoff"]["win_rate"] == 1.0
    assert a.by_strategist["thorp"]["win_rate"] == 0.0

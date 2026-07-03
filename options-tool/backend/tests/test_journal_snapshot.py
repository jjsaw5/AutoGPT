"""Journal ``setup_snapshot`` round-trip — the Phase-5 enabler."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.core.models import (
    JournalEntry,
    JournalOutcome,
    OptionContract,
    OptionRight,
    StopLoss,
    TradeLeg,
    TradeSetup,
)
from app.journal.store import TradeJournal


def _contract() -> OptionContract:
    return OptionContract(
        symbol="SPY260522P00400000",
        underlying="SPY",
        expiry=date(2026, 5, 22),
        strike=400.0,
        right=OptionRight.PUT,
        bid=2.0,
        ask=2.2,
        last=2.1,
        delta=-0.25,
        gamma=0.02,
        theta=-0.05,
        vega=0.3,
        implied_vol=0.25,
        as_of=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )


def _setup() -> TradeSetup:
    return TradeSetup(
        ticker="SPY",
        strategy="short_put",
        thesis="test",
        legs=[TradeLeg(contract=_contract(), quantity=-1)],
        net_credit=2.1,
        max_profit=2.1,
        max_loss=10.0,
        max_theoretical_loss=397.9,
        breakevens=[397.9],
        pop=0.75,
        dte=30,
        stop_loss=StopLoss(dollar_loss=50.0, kind="dollar_loss"),
    )


def test_setup_snapshot_round_trips_through_sqlite() -> None:
    j = TradeJournal(":memory:")
    entry = JournalEntry(
        ticker="SPY",
        strategy="short_put",
        strategist="sosnoff",
        thesis="test",
        opened_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
        contracts=5,
        entry_credit=2.1,
        max_loss=10.0,
        outcome=JournalOutcome.OPEN,
        setup_snapshot=_setup(),
    )
    recorded = j.record(entry)
    assert recorded.id is not None

    fetched = j.get(recorded.id)
    assert fetched is not None
    assert fetched.setup_snapshot is not None
    assert fetched.setup_snapshot.legs[0].contract.strike == 400.0
    # StopLoss round-trips too.
    assert fetched.setup_snapshot.stop_loss is not None
    assert fetched.setup_snapshot.stop_loss.dollar_loss == pytest.approx(50.0)


def test_entries_without_snapshot_still_round_trip() -> None:
    j = TradeJournal(":memory:")
    entry = JournalEntry(
        ticker="SPY",
        strategy="short_put",
        strategist="sosnoff",
        thesis="test",
        opened_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
        contracts=1,
        entry_credit=1.0,
        max_loss=1.0,
        outcome=JournalOutcome.OPEN,
    )
    recorded = j.record(entry)
    assert recorded.id is not None
    fetched = j.get(recorded.id)
    assert fetched is not None
    assert fetched.setup_snapshot is None


def test_legacy_schema_without_snapshot_column_is_migrated(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A DB created before Phase 5 must still open cleanly."""
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE journal_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            strategy TEXT NOT NULL,
            strategist TEXT NOT NULL,
            thesis TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            contracts INTEGER NOT NULL,
            entry_credit REAL NOT NULL,
            exit_credit REAL,
            max_loss REAL NOT NULL,
            outcome TEXT NOT NULL,
            realized_pnl REAL NOT NULL DEFAULT 0,
            planned_size_contracts INTEGER,
            notes TEXT NOT NULL DEFAULT ''
        );
        """
    )
    conn.execute(
        "INSERT INTO journal_entries (ticker, strategy, strategist, thesis, opened_at, "
        "contracts, entry_credit, max_loss, outcome) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("SPY", "x", "y", "z", "2026-04-22T00:00:00+00:00", 1, 1.0, 1.0, "open"),
    )
    conn.commit()
    conn.close()

    j = TradeJournal(db)
    entries = j.list()
    assert len(entries) == 1
    assert entries[0].setup_snapshot is None

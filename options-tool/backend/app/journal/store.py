"""SQLite-backed trade journal.

Kept dependency-free (stdlib ``sqlite3``) so tests are fast and the file has no
migration tooling to babysit. Schema is explicit and additive — adding columns
is a no-op for existing rows because every write names its columns.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.core.models import JournalEntry, JournalOutcome, TradeSetup


_SCHEMA = """
CREATE TABLE IF NOT EXISTS journal_entries (
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
    notes TEXT NOT NULL DEFAULT '',
    setup_snapshot TEXT
);

CREATE INDEX IF NOT EXISTS idx_journal_ticker ON journal_entries(ticker);
CREATE INDEX IF NOT EXISTS idx_journal_opened ON journal_entries(opened_at);
CREATE INDEX IF NOT EXISTS idx_journal_outcome ON journal_entries(outcome);
"""


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Additive migration: add ``setup_snapshot`` to pre-Phase-5 databases."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(journal_entries)")}
    if "setup_snapshot" not in cols:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN setup_snapshot TEXT")
        conn.commit()


class TradeJournal:
    """Persistent journal. ``:memory:`` is valid; tests use it."""

    def __init__(self, path: str | Path = ":memory:"):
        self._path = str(path)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        _ensure_columns(self._conn)

    # ------------------------------------------------------------------ CRUD
    def record(self, entry: JournalEntry) -> JournalEntry:
        snapshot_json = (
            entry.setup_snapshot.model_dump_json() if entry.setup_snapshot is not None else None
        )
        cur = self._conn.execute(
            """
            INSERT INTO journal_entries (
                ticker, strategy, strategist, thesis,
                opened_at, closed_at, contracts,
                entry_credit, exit_credit, max_loss,
                outcome, realized_pnl, planned_size_contracts, notes,
                setup_snapshot
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                entry.ticker.upper(),
                entry.strategy,
                entry.strategist,
                entry.thesis,
                _dt_to_str(entry.opened_at),
                _dt_to_str(entry.closed_at) if entry.closed_at else None,
                entry.contracts,
                entry.entry_credit,
                entry.exit_credit,
                entry.max_loss,
                entry.outcome.value,
                entry.realized_pnl,
                entry.planned_size_contracts,
                entry.notes,
                snapshot_json,
            ),
        )
        self._conn.commit()
        return entry.model_copy(update={"id": cur.lastrowid})

    def close(
        self,
        entry_id: int,
        *,
        exit_credit: float,
        realized_pnl: float,
        closed_at: datetime,
        outcome: JournalOutcome,
        notes: str | None = None,
    ) -> JournalEntry | None:
        cur = self._conn.execute(
            """
            UPDATE journal_entries
               SET exit_credit = ?, realized_pnl = ?, closed_at = ?, outcome = ?,
                   notes = COALESCE(?, notes)
             WHERE id = ?
            """,
            (exit_credit, realized_pnl, _dt_to_str(closed_at), outcome.value, notes, entry_id),
        )
        self._conn.commit()
        if cur.rowcount == 0:
            return None
        return self.get(entry_id)

    def get(self, entry_id: int) -> JournalEntry | None:
        row = self._conn.execute(
            "SELECT * FROM journal_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        return _row_to_entry(row) if row else None

    def list(
        self,
        *,
        ticker: str | None = None,
        strategist: str | None = None,
        outcomes: Iterable[JournalOutcome] | None = None,
        limit: int = 500,
    ) -> list[JournalEntry]:
        q = "SELECT * FROM journal_entries"
        where: list[str] = []
        args: list[object] = []
        if ticker:
            where.append("ticker = ?")
            args.append(ticker.upper())
        if strategist:
            where.append("strategist = ?")
            args.append(strategist)
        if outcomes:
            placeholders = ",".join("?" * len(list(outcomes)))
            where.append(f"outcome IN ({placeholders})")
            args.extend(o.value for o in outcomes)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY opened_at DESC LIMIT ?"
        args.append(limit)
        rows = self._conn.execute(q, args).fetchall()
        return [_row_to_entry(r) for r in rows]

    def clear(self) -> None:
        self._conn.execute("DELETE FROM journal_entries")
        self._conn.commit()

    def export_json(self) -> str:
        return json.dumps([e.model_dump(mode="json") for e in self.list(limit=10_000)])


# ------------------------------------------------------------------- helpers
def _dt_to_str(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _str_to_dt(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def _row_to_entry(row: sqlite3.Row) -> JournalEntry:
    snapshot_raw = _row_value(row, "setup_snapshot")
    snapshot = TradeSetup.model_validate_json(snapshot_raw) if snapshot_raw else None
    return JournalEntry(
        id=row["id"],
        ticker=row["ticker"],
        strategy=row["strategy"],
        strategist=row["strategist"],
        thesis=row["thesis"],
        opened_at=_str_to_dt(row["opened_at"]),
        closed_at=_str_to_dt(row["closed_at"]) if row["closed_at"] else None,
        contracts=row["contracts"],
        entry_credit=row["entry_credit"],
        exit_credit=row["exit_credit"],
        max_loss=row["max_loss"],
        outcome=JournalOutcome(row["outcome"]),
        realized_pnl=row["realized_pnl"],
        planned_size_contracts=row["planned_size_contracts"],
        notes=row["notes"] or "",
        setup_snapshot=snapshot,
    )


def _row_value(row: sqlite3.Row, key: str) -> str | None:
    """sqlite3.Row raises IndexError on unknown keys — tolerate missing columns."""
    try:
        value = row[key]
    except (IndexError, KeyError):
        return None
    return str(value) if value is not None else None

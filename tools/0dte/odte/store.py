"""Persistence for signals and trades (Turso / libSQL).

Market data is deliberately *not* stored. Both providers serve history on
demand -- UW's net-prem-ticks and sector-tide accept `?date=`, and FMP's
5-minute chart reaches back months -- so bars and flow can always be
refetched. What no API can give back is the record of what this process
decided and what happened next, so that is what lives here.

Every evaluation is written, including the no-trades. The rejections are
the more informative half: they are the only way to answer "what did the
regime gate actually cost me" after a month.

Two executors implement the same tiny interface:

  TursoExecutor   the hosted database, over the libSQL v2 HTTP pipeline
  SqliteExecutor  a local file or :memory:, used by the tests and usable
                  offline

Both run identical SQL, since Turso is SQLite. Credentials come from
TURSO_DATABASE_URL and TURSO_AUTH_TOKEN and are never stored in the repo.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

import requests

from .models import Decision, Signal

DEFAULT_TIMEOUT = 30


class StoreError(RuntimeError):
    pass


class Executor(Protocol):
    def execute(self, sql: str, params: Sequence[Any] = ()) -> list[dict]: ...


def _encode(value: Any) -> dict:
    """Python value -> libSQL wire type."""
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    return {"type": "text", "value": str(value)}


def _decode(cell: dict) -> Any:
    kind = cell.get("type")
    value = cell.get("value")
    if kind == "null":
        return None
    if kind == "integer":
        return int(value)
    if kind == "float":
        return float(value)
    return value


class TursoExecutor:
    """libSQL v2 pipeline client.

    A `libsql://` URL is the same host over HTTPS; the scheme is swapped
    rather than requiring the caller to know that.
    """

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        session: requests.Session | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        url = url or os.getenv("TURSO_DATABASE_URL") or ""
        self.token = token or os.getenv("TURSO_AUTH_TOKEN")
        if not url or not self.token:
            raise StoreError("TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must be set")
        self.url = url.replace("libsql://", "https://").rstrip("/")
        self._session = session or requests.Session()
        self._timeout = timeout

    def execute(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        payload = {
            "requests": [
                {
                    "type": "execute",
                    "stmt": {"sql": sql, "args": [_encode(p) for p in params]},
                },
                {"type": "close"},
            ]
        }
        response = self._session.post(
            f"{self.url}/v2/pipeline",
            json=payload,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        body = response.json()

        for result in body.get("results", []):
            if result.get("type") == "error":
                raise StoreError(result.get("error", {}).get("message", "unknown"))

        first = body.get("results", [{}])[0]
        result = first.get("response", {}).get("result")
        if not result:
            return []
        columns = [c["name"] for c in result.get("cols", [])]
        return [
            dict(zip(columns, (_decode(cell) for cell in row)))
            for row in result.get("rows", [])
        ]


class SqliteExecutor:
    """Local SQLite, for tests and offline runs."""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        cursor = self._conn.execute(sql, tuple(params))
        rows = [dict(r) for r in cursor.fetchall()] if cursor.description else []
        self._conn.commit()
        return rows


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS signals (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        asof           TEXT    NOT NULL,
        session_date   TEXT    NOT NULL,
        symbol         TEXT    NOT NULL,
        decision       TEXT    NOT NULL,
        conviction     INTEGER NOT NULL,
        regime         TEXT,
        regime_score   REAL,
        sector_rs      REAL,
        breadth        REAL,
        qqq_rs         REAL,
        uw_bias        REAL,
        uw_detail      TEXT,
        price          REAL,
        premarket_high REAL,
        premarket_low  REAL,
        ema_fast       REAL,
        ema_slow       REAL,
        sma_daily      REAL,
        vwap           REAL,
        atr            REAL,
        blocking_gate  TEXT,
        gates_json     TEXT NOT NULL,
        plan_json      TEXT,
        UNIQUE (asof, symbol)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_signals_day ON signals (session_date, symbol)",
    "CREATE INDEX IF NOT EXISTS idx_signals_blocking ON signals (blocking_gate)",
    """
    CREATE TABLE IF NOT EXISTS trades (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id      INTEGER REFERENCES signals (id),
        session_date   TEXT    NOT NULL,
        symbol         TEXT    NOT NULL,
        direction      INTEGER NOT NULL,
        expiration     TEXT,
        strike         REAL,
        option_type    TEXT,
        quantity       INTEGER NOT NULL,
        entry_premium  REAL    NOT NULL,
        entry_at       TEXT    NOT NULL,
        conviction     INTEGER,
        exit_premium   REAL,
        exit_at        TEXT,
        exit_reason    TEXT,
        pnl            REAL,
        pnl_pct        REAL,
        notes          TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trades_day ON trades (session_date)",
]


class SignalStore:
    def __init__(self, executor: Executor) -> None:
        self._db = executor

    def migrate(self) -> None:
        for statement in SCHEMA:
            self._db.execute(statement)

    def record_signal(self, signal: Signal) -> None:
        """Persist one evaluation. Idempotent per (asof, symbol).

        Re-running the same minute overwrites rather than duplicating, so a
        retried cron tick does not corrupt the sample.
        """
        blocking = signal.blocking_gates
        levels = signal.levels
        self._db.execute(
            """
            INSERT INTO signals (
                asof, session_date, symbol, decision, conviction,
                regime, regime_score, sector_rs, breadth, qqq_rs,
                uw_bias, uw_detail, price, premarket_high, premarket_low,
                ema_fast, ema_slow, sma_daily, vwap, atr,
                blocking_gate, gates_json, plan_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (asof, symbol) DO UPDATE SET
                decision      = excluded.decision,
                conviction    = excluded.conviction,
                blocking_gate = excluded.blocking_gate,
                gates_json    = excluded.gates_json,
                plan_json     = excluded.plan_json
            """,
            (
                signal.asof.isoformat(),
                signal.asof.date().isoformat(),
                signal.symbol,
                signal.decision.value,
                signal.conviction,
                signal.regime.regime.value,
                signal.regime.score,
                signal.regime.sector_rs,
                signal.regime.breadth,
                signal.regime.qqq_rs,
                signal.uw_bias,
                signal.uw_detail,
                levels.price,
                levels.premarket_high,
                levels.premarket_low,
                levels.ema_fast,
                levels.ema_slow,
                levels.sma_daily,
                levels.vwap,
                levels.atr,
                blocking[0].name if blocking else None,
                json.dumps(
                    [
                        {"name": g.name, "passed": g.passed, "detail": g.detail}
                        for g in signal.gates
                    ]
                ),
                json.dumps(signal.to_dict()["plan"]) if signal.plan else None,
            ),
        )

    def signal_id(self, symbol: str, asof: datetime) -> int | None:
        rows = self._db.execute(
            "SELECT id FROM signals WHERE symbol = ? AND asof = ?",
            (symbol, asof.isoformat()),
        )
        return rows[0]["id"] if rows else None

    def record_entry(
        self,
        symbol: str,
        session_date: str,
        direction: int,
        quantity: int,
        entry_premium: float,
        entry_at: datetime,
        expiration: str | None = None,
        strike: float | None = None,
        option_type: str | None = None,
        conviction: int | None = None,
        signal_id: int | None = None,
    ) -> None:
        self._db.execute(
            """
            INSERT INTO trades (
                signal_id, session_date, symbol, direction, expiration,
                strike, option_type, quantity, entry_premium, entry_at,
                conviction
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                signal_id,
                session_date,
                symbol,
                direction,
                expiration,
                strike,
                option_type,
                quantity,
                entry_premium,
                entry_at.isoformat(),
                conviction,
            ),
        )

    def close_trade(
        self,
        trade_id: int,
        exit_premium: float,
        exit_at: datetime,
        exit_reason: str,
    ) -> None:
        rows = self._db.execute(
            "SELECT quantity, entry_premium FROM trades WHERE id = ?", (trade_id,)
        )
        if not rows:
            raise StoreError(f"no trade {trade_id}")
        quantity = rows[0]["quantity"]
        entry = rows[0]["entry_premium"]

        pnl = (exit_premium - entry) * 100 * quantity
        pnl_pct = ((exit_premium - entry) / entry) if entry else 0.0
        self._db.execute(
            """
            UPDATE trades
               SET exit_premium = ?, exit_at = ?, exit_reason = ?,
                   pnl = ?, pnl_pct = ?
             WHERE id = ?
            """,
            (exit_premium, exit_at.isoformat(), exit_reason, pnl, pnl_pct, trade_id),
        )

    def open_trades(self) -> list[dict]:
        return self._db.execute(
            "SELECT * FROM trades WHERE exit_at IS NULL ORDER BY entry_at"
        )

    def counts_today(self, session_date: str) -> tuple[int, int]:
        """Trades taken and losses closed today -- feeds the risk-budget gate."""
        rows = self._db.execute(
            """
            SELECT COUNT(*) AS taken,
                   COALESCE(SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END), 0) AS losses
              FROM trades WHERE session_date = ?
            """,
            (session_date,),
        )
        if not rows:
            return 0, 0
        return int(rows[0]["taken"] or 0), int(rows[0]["losses"] or 0)

    def blocking_gate_counts(self) -> list[dict]:
        """Why the process stood aside, most common first."""
        return self._db.execute(
            """
            SELECT blocking_gate AS gate, COUNT(*) AS n
              FROM signals
             WHERE decision = ? AND blocking_gate IS NOT NULL
             GROUP BY blocking_gate
             ORDER BY n DESC
            """,
            (Decision.NO_TRADE.value,),
        )

    def performance(self) -> list[dict]:
        return self._db.execute("""
            SELECT COUNT(*)                                          AS trades,
                   COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
                   COALESCE(SUM(pnl), 0)                             AS net_pnl,
                   COALESCE(AVG(pnl_pct), 0)                         AS avg_pct
              FROM trades WHERE exit_at IS NOT NULL
            """)

    def performance_by_conviction(self) -> list[dict]:
        """Does conviction predict anything?

        It is deliberately excluded from sizing, so this is the check on
        whether that was the right call.
        """
        return self._db.execute("""
            SELECT CASE WHEN conviction >= 80 THEN 'high (80+)'
                        WHEN conviction >= 60 THEN 'mid (60-79)'
                        ELSE 'low (<60)' END                         AS bucket,
                   COUNT(*)                                          AS trades,
                   COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
                   COALESCE(SUM(pnl), 0)                             AS net_pnl
              FROM trades WHERE exit_at IS NOT NULL
             GROUP BY bucket ORDER BY bucket
            """)

    def performance_by_window(self) -> list[dict]:
        return self._db.execute("""
            SELECT CASE WHEN substr(entry_at, 12, 5) < '11:30'
                        THEN 'morning' ELSE 'afternoon' END          AS window,
                   COUNT(*)                                          AS trades,
                   COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
                   COALESCE(SUM(pnl), 0)                             AS net_pnl
              FROM trades WHERE exit_at IS NOT NULL
             GROUP BY window ORDER BY window
            """)


def default_store(migrate: bool = False) -> SignalStore | None:
    """Store from the environment, or None when unconfigured.

    Recording must never break a signal run, so an unconfigured or
    unreachable database degrades to no persistence.
    """
    try:
        store = SignalStore(TursoExecutor())
        if migrate:
            store.migrate()
        return store
    except (StoreError, requests.RequestException):
        return None

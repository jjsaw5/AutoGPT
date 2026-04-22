"""Small SQLite-backed cache for option chains and price history.

Keeps each provider's upstream call count down to one per analysis run and
serialises chain blobs so the UI can replay "what did we see at 10:00am?".
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

DEFAULT_TTL_SECONDS = 300


class ChainCache:
    """Tiny key-value cache keyed on (provider, kind, ticker, args)."""

    def __init__(self, path: str | Path = ":memory:", ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._path = str(path)
        self._ttl = ttl_seconds
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                stored_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    def _key(self, provider: str, kind: str, ticker: str, extra: str = "") -> str:
        return f"{provider}::{kind}::{ticker.upper()}::{extra}"

    def get(self, provider: str, kind: str, ticker: str, extra: str = "") -> Any | None:
        key = self._key(provider, kind, ticker, extra)
        row = self._conn.execute(
            "SELECT payload, stored_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        payload, stored_at = row
        if time.time() - stored_at > self._ttl:
            return None
        return json.loads(payload)

    def set(
        self, provider: str, kind: str, ticker: str, value: Any, extra: str = ""
    ) -> None:
        key = self._key(provider, kind, ticker, extra)
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, payload, stored_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, default=str), time.time()),
        )
        self._conn.commit()

    def clear(self) -> None:
        self._conn.execute("DELETE FROM cache")
        self._conn.commit()

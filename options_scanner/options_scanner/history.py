"""Durable run history — the time-series record of every scan.

Why this exists: the scanner runs in an ephemeral container (reclaimed on
inactivity, repo re-cloned fresh), so anything not committed is lost. Yet the
whole calibration loop — and questions like "how did SPY's score drift across
today's runs, and was that GO on a *real* chain?" — depend on keeping history.

The design is two layers, deliberately separated:

* **Append-only JSONL is the source of truth.** ``history/scans/YYYY-MM.jsonl``
  (one candidate row per scan) and ``history/runs/YYYY-MM.jsonl`` (one manifest
  row per run). Text, git-diffable, committed — so it survives the container.
  Monthly partitions keep files small and diffs clean.

* **A query DB is *materialized* from the JSONL** for fast SQL. It is fully
  rebuildable from the JSONL, so it is never committed. Today that backend is
  local SQLite (:class:`SqliteQueryDB`); the hosted Turso/libSQL backend speaks
  the *same SQLite dialect over HTTPS* and drops in behind :class:`QueryDB`
  with no query changes — which is exactly why Turso was chosen for the
  HTTPS-only egress in this environment.

The scanner writes JSONL every run (:meth:`HistoryStore.record`); ``rebuild``
replays the JSONL into the query DB. Nothing here makes network calls; the
Turso backend (Phase 2) will, behind the same interface.
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

# Candidate-row columns persisted to the query DB. Mirrors the JSONL keys
# emitted by ``pipeline.logbook.candidate_to_row`` (lower-cased, P1->p1, etc.).
_CANDIDATE_COLUMNS = [
    "scan_id", "timestamp", "ticker", "cap_tier", "tier", "structure", "legs",
    "thesis_tag", "direction", "vol_regime", "catalyst_type", "days_to_catalyst",
    "iv_rank", "implied_move", "expected_move",
    "p1", "p2", "p3", "p4", "p5", "p6",
    "composite", "effective_composite", "regime_adj", "from_chain",
    "pop_predicted", "max_profit", "max_loss", "decision", "gate_flags",
]

# Map JSONL row keys -> query-DB column names (only where they differ).
_ROW_KEY_TO_COLUMN = {
    "P1": "p1", "P2": "p2", "P3": "p3", "P4": "p4", "P5": "p5", "P6": "p6",
    "POP_predicted": "pop_predicted",
}


def _month_of(timestamp: str) -> str:
    """YYYY-MM partition key from an ISO timestamp (first 7 chars)."""
    return (timestamp or "0000-00")[:7]


def normalize_candidate_row(row: dict[str, Any]) -> dict[str, Any]:
    """A JSONL candidate row -> a dict keyed by query-DB column names.

    Unknown keys are dropped; missing columns default to ``None``. ``from_chain``
    is coerced to 0/1 so SQLite can index it as an integer boolean.
    """
    out: dict[str, Any] = {c: None for c in _CANDIDATE_COLUMNS}
    for k, v in row.items():
        col = _ROW_KEY_TO_COLUMN.get(k, k)
        if col in out:
            out[col] = v
    if out.get("from_chain") is not None:
        out["from_chain"] = 1 if out["from_chain"] else 0
    return out


# --------------------------------------------------------------------------- #
# Run manifest — one row per scan (the run-level context that made a throttled
# run's phantom GO explicable: regime, decision mix, chain coverage).
# --------------------------------------------------------------------------- #
@dataclass
class RunManifest:
    scan_id: str
    timestamp: str
    regime_direction: Optional[int] = None
    regime_composite: Optional[float] = None
    n_candidates: int = 0
    n_go: int = 0
    n_watch: int = 0
    n_pass: int = 0
    n_placeholder: int = 0          # tradeable structures priced off a placeholder
    chain_coverage: Optional[float] = None   # real-chain fraction of tradeables

    def to_row(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in (
            "scan_id", "timestamp", "regime_direction", "regime_composite",
            "n_candidates", "n_go", "n_watch", "n_pass", "n_placeholder",
            "chain_coverage",
        )}
        d["month"] = _month_of(self.timestamp)
        return d


def build_run_manifest(
    candidate_rows: list[dict[str, Any]], *, scan_id: str, timestamp: str,
    regime: Any = None,
) -> RunManifest:
    """Summarize a scan's candidate rows into a run manifest.

    ``chain_coverage`` and ``n_placeholder`` are computed over *tradeable*
    candidates only (those with a structure that isn't the no-trade sentinel),
    since a PASS with no structure has no chain to be real or placeholder.
    """
    def _dec(r):
        return (r.get("decision") or "").upper()

    tradeable = [r for r in candidate_rows if (r.get("structure") or "none") != "none"]
    real = [r for r in tradeable if r.get("from_chain")]
    coverage = (len(real) / len(tradeable)) if tradeable else None

    rdir = rcomp = None
    if regime is not None:
        rdir = getattr(regime, "direction", None)
        rcomp = getattr(regime, "composite", None)

    return RunManifest(
        scan_id=scan_id, timestamp=timestamp,
        regime_direction=rdir, regime_composite=rcomp,
        n_candidates=len(candidate_rows),
        n_go=sum(1 for r in candidate_rows if _dec(r) == "GO"),
        n_watch=sum(1 for r in candidate_rows if _dec(r) == "WATCH"),
        n_pass=sum(1 for r in candidate_rows if _dec(r) == "PASS"),
        n_placeholder=len(tradeable) - len(real),
        chain_coverage=round(coverage, 3) if coverage is not None else None,
    )


# --------------------------------------------------------------------------- #
# Query DB backend — swappable. SqliteQueryDB now; TursoQueryDB (HTTPS) next,
# same dialect, same methods.
# --------------------------------------------------------------------------- #
class QueryDB(ABC):
    @abstractmethod
    def apply_run(self, manifest: RunManifest) -> None: ...
    @abstractmethod
    def apply_candidates(self, rows: Iterable[dict[str, Any]]) -> None: ...
    @abstractmethod
    def apply_reviews(self, rows: Iterable[dict[str, Any]]) -> None: ...
    @abstractmethod
    def ticker_timeline(self, ticker: str) -> list[dict[str, Any]]: ...
    @abstractmethod
    def position_history(self, ticker: str) -> list[dict[str, Any]]: ...
    @abstractmethod
    def runs(self, limit: int = 100) -> list[dict[str, Any]]: ...
    @abstractmethod
    def close(self) -> None: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    scan_id           TEXT PRIMARY KEY,
    timestamp         TEXT NOT NULL,
    month             TEXT NOT NULL,
    regime_direction  INTEGER,
    regime_composite  REAL,
    n_candidates      INTEGER,
    n_go              INTEGER,
    n_watch           INTEGER,
    n_pass            INTEGER,
    n_placeholder     INTEGER,
    chain_coverage    REAL
);
CREATE TABLE IF NOT EXISTS scan_candidates (
    scan_id             TEXT NOT NULL,
    timestamp           TEXT NOT NULL,
    ticker              TEXT NOT NULL,
    cap_tier            TEXT,
    tier                TEXT,
    structure           TEXT,
    legs                TEXT,
    thesis_tag          TEXT,
    direction           TEXT,
    vol_regime          TEXT,
    catalyst_type       TEXT,
    days_to_catalyst    INTEGER,
    iv_rank             REAL,
    implied_move        REAL,
    expected_move       REAL,
    p1 REAL, p2 REAL, p3 REAL, p4 REAL, p5 REAL, p6 REAL,
    composite           REAL,
    effective_composite REAL,
    regime_adj          REAL,
    from_chain          INTEGER,
    pop_predicted       REAL,
    max_profit          REAL,
    max_loss            REAL,
    decision            TEXT,
    gate_flags          TEXT,
    PRIMARY KEY (scan_id, ticker)
);
CREATE INDEX IF NOT EXISTS ix_cand_ticker   ON scan_candidates(ticker, timestamp);
CREATE INDEX IF NOT EXISTS ix_cand_decision ON scan_candidates(decision);
CREATE TABLE IF NOT EXISTS position_reviews (
    scan_id           TEXT NOT NULL,
    timestamp         TEXT NOT NULL,
    ticker            TEXT NOT NULL,
    account           TEXT NOT NULL DEFAULT '',
    structure         TEXT,
    grade             TEXT,
    action            TEXT,
    reason            TEXT,
    score             REAL,
    aligned           INTEGER,
    direction         INTEGER,
    is_long_premium   INTEGER,
    pnl_pct           REAL,
    dte               INTEGER,
    days_to_earnings  INTEGER,
    PRIMARY KEY (scan_id, ticker, account)
);
CREATE INDEX IF NOT EXISTS ix_review_ticker ON position_reviews(ticker, timestamp);
"""

# Columns persisted for a position review (mirrors the JSONL keys).
_REVIEW_COLUMNS = [
    "scan_id", "timestamp", "ticker", "account", "structure", "grade", "action",
    "reason", "score", "aligned", "direction", "is_long_premium", "pnl_pct",
    "dte", "days_to_earnings",
]

# Idempotent column adds for tables that predate a column (the hosted DB is
# persistent, so CREATE IF NOT EXISTS won't backfill it). Run best-effort.
_MIGRATIONS = [
    ("position_reviews", "structure", "ALTER TABLE position_reviews ADD COLUMN structure TEXT"),
]


def normalize_review_row(row: dict[str, Any]) -> dict[str, Any]:
    """A review JSONL row -> a dict keyed by review columns; bools -> 0/1."""
    out: dict[str, Any] = {c: None for c in _REVIEW_COLUMNS}
    out["account"] = ""
    for k, v in row.items():
        if k in out:
            out[k] = v
    for b in ("aligned", "is_long_premium"):
        if out.get(b) is not None:
            out[b] = 1 if out[b] else 0
    return out


class SqliteQueryDB(QueryDB):
    """Local SQLite materialization. Rebuildable from JSONL, so not committed."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        # Best-effort column adds for pre-existing tables.
        for table, col, ddl in _MIGRATIONS:
            have = {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            if col not in have:
                self._conn.execute(ddl)
        self._conn.commit()

    def apply_run(self, manifest: RunManifest) -> None:
        row = manifest.to_row()
        cols = ", ".join(row)
        placeholders = ", ".join(f":{c}" for c in row)
        self._conn.execute(
            f"INSERT OR REPLACE INTO runs ({cols}) VALUES ({placeholders})", row
        )
        self._conn.commit()

    def apply_candidates(self, rows: Iterable[dict[str, Any]]) -> None:
        norm = [normalize_candidate_row(r) for r in rows]
        if not norm:
            return
        cols = ", ".join(_CANDIDATE_COLUMNS)
        placeholders = ", ".join(f":{c}" for c in _CANDIDATE_COLUMNS)
        self._conn.executemany(
            f"INSERT OR REPLACE INTO scan_candidates ({cols}) VALUES ({placeholders})",
            norm,
        )
        self._conn.commit()

    def apply_reviews(self, rows: Iterable[dict[str, Any]]) -> None:
        norm = [normalize_review_row(r) for r in rows]
        if not norm:
            return
        cols = ", ".join(_REVIEW_COLUMNS)
        placeholders = ", ".join(f":{c}" for c in _REVIEW_COLUMNS)
        self._conn.executemany(
            f"INSERT OR REPLACE INTO position_reviews ({cols}) VALUES ({placeholders})",
            norm,
        )
        self._conn.commit()

    def ticker_timeline(self, ticker: str) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT timestamp, composite, effective_composite, regime_adj, "
            "decision, from_chain, structure, vol_regime, iv_rank "
            "FROM scan_candidates WHERE ticker = ? ORDER BY timestamp",
            (ticker.upper(),),
        )
        return [dict(r) for r in cur.fetchall()]

    def position_history(self, ticker: str) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT timestamp, account, grade, action, score, pnl_pct, dte, reason "
            "FROM position_reviews WHERE ticker = ? ORDER BY timestamp",
            (ticker.upper(),),
        )
        return [dict(r) for r in cur.fetchall()]

    def runs(self, limit: int = 100) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT * FROM runs ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in cur.fetchall()]

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Escape hatch for ad-hoc calibration queries (read-only by convention)."""
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def close(self) -> None:
        self._conn.close()


# --------------------------------------------------------------------------- #
# Turso backend — hosted libSQL over its HTTP pipeline API (Phase 2).
#
# We talk to `POST {url}/v2/pipeline` with `requests` rather than a native
# libSQL client on purpose: `requests` honors this environment's HTTPS_PROXY and
# CA bundle, which is the only way out to the network here. Same SQLite dialect
# and same DDL as the local backend, so the QueryDB interface is unchanged.
# --------------------------------------------------------------------------- #
# poster(payload) -> parsed JSON response. Injectable so the encode/parse logic
# is testable without a live DB or network.
Poster = Callable[[dict[str, Any]], dict[str, Any]]


def _encode_arg(v: Any) -> dict[str, Any]:
    """Python value -> a libSQL typed argument. Integers travel as strings."""
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def _decode_value(cell: dict[str, Any]) -> Any:
    t = cell.get("type")
    val = cell.get("value")
    if t == "null":
        return None
    if t == "integer":
        return int(val)
    if t == "float":
        return float(val)
    return val  # text / blob (base64) returned as-is


def _requests_poster(url: str, auth_token: str, *, timeout: float = 20.0) -> Poster:
    import requests  # local import: only needed when a live Turso is configured

    endpoint = url.rstrip("/") + "/v2/pipeline"
    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}

    def _post(payload: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            raise RuntimeError(f"Turso pipeline {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    return _post


def _normalize_turso_url(url: str) -> str:
    """`libsql://x.turso.io` -> `https://x.turso.io` for the HTTP pipeline API."""
    if url.startswith("libsql://"):
        return "https://" + url[len("libsql://"):]
    return url


class TursoQueryDB(QueryDB):
    def __init__(self, poster: Poster, *, ensure_schema: bool = True) -> None:
        self._post = poster
        if ensure_schema:
            self._execute_batch(
                [(stmt, ()) for stmt in _SCHEMA.split(";") if stmt.strip()]
            )
            # Best-effort column adds for a pre-existing hosted table; ignore the
            # "duplicate column" error when it's already there.
            for _table, _col, ddl in _MIGRATIONS:
                try:
                    self._execute_batch([(ddl, ())])
                except Exception:
                    pass

    @classmethod
    def from_env(cls, url: str, auth_token: str, **kw) -> "TursoQueryDB":
        return cls(_requests_poster(_normalize_turso_url(url), auth_token), **kw)

    def _execute_batch(self, statements: list[tuple[str, tuple]]) -> list[dict[str, Any]]:
        """Run statements in one pipeline round-trip; return each execute result."""
        requests_ = [
            {"type": "execute",
             "stmt": {"sql": sql, "args": [_encode_arg(a) for a in args]}}
            for sql, args in statements
        ]
        requests_.append({"type": "close"})
        payload = {"requests": requests_}
        body = self._post(payload)
        results = []
        for item in body.get("results", []):
            if item.get("type") == "error":
                err = item.get("error", {})
                raise RuntimeError(f"Turso stmt error: {err.get('message', err)}")
            resp = item.get("response", {})
            if resp.get("type") == "execute":
                results.append(resp.get("result", {}))
        return results

    @staticmethod
    def _rows_to_dicts(result: dict[str, Any]) -> list[dict[str, Any]]:
        cols = [c.get("name") for c in result.get("cols", [])]
        return [
            {cols[i]: _decode_value(cell) for i, cell in enumerate(row)}
            for row in result.get("rows", [])
        ]

    def apply_run(self, manifest: RunManifest) -> None:
        row = manifest.to_row()
        cols = ", ".join(row)
        placeholders = ", ".join("?" for _ in row)
        self._execute_batch([(
            f"INSERT OR REPLACE INTO runs ({cols}) VALUES ({placeholders})",
            tuple(row.values()),
        )])

    def apply_candidates(self, rows: Iterable[dict[str, Any]]) -> None:
        norm = [normalize_candidate_row(r) for r in rows]
        if not norm:
            return
        cols = ", ".join(_CANDIDATE_COLUMNS)
        placeholders = ", ".join("?" for _ in _CANDIDATE_COLUMNS)
        sql = f"INSERT OR REPLACE INTO scan_candidates ({cols}) VALUES ({placeholders})"
        self._execute_batch([(sql, tuple(r[c] for c in _CANDIDATE_COLUMNS)) for r in norm])

    def apply_reviews(self, rows: Iterable[dict[str, Any]]) -> None:
        norm = [normalize_review_row(r) for r in rows]
        if not norm:
            return
        cols = ", ".join(_REVIEW_COLUMNS)
        placeholders = ", ".join("?" for _ in _REVIEW_COLUMNS)
        sql = f"INSERT OR REPLACE INTO position_reviews ({cols}) VALUES ({placeholders})"
        self._execute_batch([(sql, tuple(r[c] for c in _REVIEW_COLUMNS)) for r in norm])

    def ticker_timeline(self, ticker: str) -> list[dict[str, Any]]:
        res = self._execute_batch([(
            "SELECT timestamp, composite, effective_composite, regime_adj, "
            "decision, from_chain, structure, vol_regime, iv_rank "
            "FROM scan_candidates WHERE ticker = ? ORDER BY timestamp",
            (ticker.upper(),),
        )])
        return self._rows_to_dicts(res[0]) if res else []

    def position_history(self, ticker: str) -> list[dict[str, Any]]:
        res = self._execute_batch([(
            "SELECT timestamp, account, grade, action, score, pnl_pct, dte, reason "
            "FROM position_reviews WHERE ticker = ? ORDER BY timestamp",
            (ticker.upper(),),
        )])
        return self._rows_to_dicts(res[0]) if res else []

    def runs(self, limit: int = 100) -> list[dict[str, Any]]:
        res = self._execute_batch([(
            "SELECT * FROM runs ORDER BY timestamp DESC LIMIT ?", (limit,),
        )])
        return self._rows_to_dicts(res[0]) if res else []

    def close(self) -> None:
        # Each pipeline call already sends a `close`; nothing persistent to shut.
        pass


# --------------------------------------------------------------------------- #
# HistoryStore — owns the JSONL source-of-truth and (optionally) a query DB.
# --------------------------------------------------------------------------- #
@dataclass
class HistoryStore:
    base_dir: Path
    query_db: Optional[QueryDB] = None
    _scans_dir: Path = field(init=False)
    _runs_dir: Path = field(init=False)
    _reviews_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir)
        self._scans_dir = self.base_dir / "scans"
        self._runs_dir = self.base_dir / "runs"
        self._reviews_dir = self.base_dir / "reviews"

    # -- write path (called once per scan) --
    def record(
        self, candidate_rows: list[dict[str, Any]], *, manifest: RunManifest,
        review_rows: Optional[list[dict[str, Any]]] = None,
    ) -> int:
        """Append a scan to the durable JSONL and mirror into the query DB.

        ``review_rows`` (optional) are the position-review rows for the same
        session — persisted alongside candidates so a holding's grade/action can
        be tracked across sessions, the same way candidate scores are.

        Returns the number of candidate rows written. Idempotent per scan_id:
        the query DB upserts on (scan_id, ticker[, account]), and JSONL is an
        append log de-duplicated on rebuild.
        """
        month = _month_of(manifest.timestamp)
        self._append(self._scans_dir / f"{month}.jsonl", candidate_rows)
        self._append(self._runs_dir / f"{month}.jsonl", [manifest.to_row()])
        if review_rows:
            self._append(self._reviews_dir / f"{month}.jsonl", review_rows)
        if self.query_db is not None:
            self.query_db.apply_run(manifest)
            self.query_db.apply_candidates(candidate_rows)
            if review_rows:
                self.query_db.apply_reviews(review_rows)
        return len(candidate_rows)

    @staticmethod
    def _append(path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")

    # -- read path --
    def iter_candidate_rows(self) -> Iterator[dict[str, Any]]:
        for path in sorted(self._scans_dir.glob("*.jsonl")):
            for line in _read_jsonl(path):
                yield line

    def iter_run_rows(self) -> Iterator[dict[str, Any]]:
        for path in sorted(self._runs_dir.glob("*.jsonl")):
            for line in _read_jsonl(path):
                yield line

    def iter_review_rows(self) -> Iterator[dict[str, Any]]:
        for path in sorted(self._reviews_dir.glob("*.jsonl")):
            for line in _read_jsonl(path):
                yield line

    def rebuild(self) -> int:
        """Replay all JSONL into ``self.query_db``. Returns candidate rows loaded."""
        if self.query_db is None:
            raise RuntimeError("rebuild() needs a query_db")
        return self.sync_to(self.query_db)

    def sync_to(self, target: QueryDB) -> int:
        """Replay all JSONL into any query DB. Returns candidate rows loaded.

        This is both the local rebuild and the remote-sync path: point ``target``
        at a :class:`TursoQueryDB` to push the durable JSONL up to the hosted DB
        (and to resync after an ephemeral-container blip). Upserts on
        (scan_id, ticker) / scan_id, so replaying an append log with overlaps is
        idempotent — the last write for a key wins.
        """
        for row in self.iter_run_rows():
            target.apply_run(_row_to_manifest(row))
        rows = list(self.iter_candidate_rows())
        target.apply_candidates(rows)
        target.apply_reviews(list(self.iter_review_rows()))
        return len(rows)


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _row_to_manifest(row: dict[str, Any]) -> RunManifest:
    fields = {
        "scan_id", "timestamp", "regime_direction", "regime_composite",
        "n_candidates", "n_go", "n_watch", "n_pass", "n_placeholder",
        "chain_coverage",
    }
    return RunManifest(**{k: v for k, v in row.items() if k in fields})


# --------------------------------------------------------------------------- #
# Backfill — pull the scattered legacy runs/*.jsonl into the canonical store so
# history-to-date (incl. the SPY GO run) is captured before the container dies.
# --------------------------------------------------------------------------- #
def backfill_from_legacy(
    legacy_paths: Iterable[str | Path], store: HistoryStore
) -> dict[str, int]:
    """Load legacy per-candidate JSONL runs into the canonical store.

    Legacy rows may predate the enriched schema (no from_chain/effective_*);
    those columns simply stay null. De-duplicates on (scan_id, ticker) across
    all input files so overlapping runs aren't double-counted. Returns
    {'runs': n_scans, 'candidates': n_rows}.
    """
    by_scan: dict[str, dict[str, dict[str, Any]]] = {}
    for p in legacy_paths:
        path = Path(p)
        if not path.exists():
            continue
        for row in _read_jsonl(path):
            sid = row.get("scan_id")
            tkr = row.get("ticker")
            if not sid or not tkr:
                continue
            by_scan.setdefault(sid, {})[tkr] = row

    total = 0
    for sid, ticker_rows in sorted(by_scan.items()):
        rows = list(ticker_rows.values())
        ts = rows[0].get("timestamp") or sid.replace("scan_", "")
        manifest = build_run_manifest(rows, scan_id=sid, timestamp=ts)
        total += store.record(rows, manifest=manifest)
    return {"runs": len(by_scan), "candidates": total}

"""Durable run history — JSONL source-of-truth + SQLite materialization."""

from __future__ import annotations

import json

from options_scanner.history import (
    HistoryStore,
    SqliteQueryDB,
    TursoQueryDB,
    build_run_manifest,
    backfill_from_legacy,
    normalize_candidate_row,
    _encode_arg,
    _decode_value,
    _normalize_turso_url,
)


def _row(ticker, scan_id, ts, **kw):
    base = dict(
        scan_id=scan_id, timestamp=ts, ticker=ticker, structure="debit_vertical",
        P1=70, P2=70, P3=70, P4=20, P5=100, P6=75, composite=69.0,
        effective_composite=69.0, regime_adj=0.0, from_chain=False,
        decision="GO", vol_regime="cheap", iv_rank=22.0,
    )
    base.update(kw)
    return base


def _store(tmp_path):
    return HistoryStore(base_dir=tmp_path / "history", query_db=SqliteQueryDB())


def test_record_writes_jsonl_and_db(tmp_path):
    store = _store(tmp_path)
    rows = [_row("SPY", "scan_A", "2026-07-06T13:00:00Z")]
    manifest = build_run_manifest(rows, scan_id="scan_A", timestamp="2026-07-06T13:00:00Z")
    n = store.record(rows, manifest=manifest)
    assert n == 1

    # JSONL partitioned by month, is the durable record.
    scan_file = tmp_path / "history" / "scans" / "2026-07.jsonl"
    assert scan_file.exists()
    written = json.loads(scan_file.read_text().strip())
    assert written["ticker"] == "SPY" and written["from_chain"] is False

    # Query DB mirrors it.
    tl = store.query_db.ticker_timeline("SPY")
    assert len(tl) == 1 and tl[0]["decision"] == "GO"


def test_ticker_timeline_orders_and_tracks_chain(tmp_path):
    # The SPY-drift question: score bounces run to run, all on placeholder chains.
    store = _store(tmp_path)
    for ts, comp, dec, chain in [
        ("2026-07-06T12:00:00Z", 55.4, "WATCH", False),
        ("2026-07-06T13:47:00Z", 69.0, "GO", False),
        ("2026-07-06T15:00:00Z", 48.0, "PASS", False),
    ]:
        rows = [_row("SPY", f"scan_{ts}", ts, composite=comp,
                     effective_composite=comp, decision=dec, from_chain=chain)]
        store.record(rows, manifest=build_run_manifest(
            rows, scan_id=f"scan_{ts}", timestamp=ts))

    tl = store.query_db.ticker_timeline("SPY")
    assert [r["decision"] for r in tl] == ["WATCH", "GO", "PASS"]      # ordered
    assert all(r["from_chain"] == 0 for r in tl)                       # all placeholder


def test_manifest_computes_chain_coverage(tmp_path):
    rows = [
        _row("AAA", "s", "2026-07-06T13:00:00Z", from_chain=True, decision="GO"),
        _row("BBB", "s", "2026-07-06T13:00:00Z", from_chain=False, decision="WATCH"),
        _row("CCC", "s", "2026-07-06T13:00:00Z", structure="none", decision="PASS"),
    ]
    m = build_run_manifest(rows, scan_id="s", timestamp="2026-07-06T13:00:00Z")
    # coverage is over tradeables only (AAA real, BBB placeholder; CCC has no structure)
    assert m.n_candidates == 3 and m.n_go == 1 and m.n_watch == 1 and m.n_pass == 1
    assert m.n_placeholder == 1
    assert m.chain_coverage == 0.5


def test_rebuild_from_jsonl_dedupes(tmp_path):
    store = _store(tmp_path)
    ts = "2026-07-06T13:00:00Z"
    # Same (scan_id, ticker) written twice with different composites → last wins.
    for comp in (60.0, 65.0):
        rows = [_row("SPY", "scan_dup", ts, composite=comp, effective_composite=comp)]
        store.record(rows, manifest=build_run_manifest(rows, scan_id="scan_dup", timestamp=ts))

    fresh = HistoryStore(base_dir=store.base_dir, query_db=SqliteQueryDB())
    loaded = fresh.rebuild()
    tl = fresh.query_db.ticker_timeline("SPY")
    assert len(tl) == 1                        # deduped on (scan_id, ticker)
    assert tl[0]["composite"] == 65.0          # last write wins
    assert loaded == 2                         # both raw lines were read


def test_backfill_from_legacy(tmp_path):
    legacy = tmp_path / "legacy.jsonl"
    with open(legacy, "w") as fh:
        fh.write(json.dumps({"scan_id": "old1", "ticker": "SPY", "timestamp": "2026-07-02T10:00:00Z",
                             "composite": 55.4, "decision": "WATCH"}) + "\n")
        fh.write(json.dumps({"scan_id": "old1", "ticker": "TSM", "timestamp": "2026-07-02T10:00:00Z",
                             "composite": 80.0, "decision": "WATCH"}) + "\n")
    store = _store(tmp_path)
    stats = backfill_from_legacy([legacy], store)
    assert stats == {"runs": 1, "candidates": 2}
    # Legacy rows lacking from_chain load with a null, not a crash.
    tl = store.query_db.ticker_timeline("SPY")
    assert tl[0]["from_chain"] is None


def test_normalize_maps_pillar_keys():
    row = normalize_candidate_row({"P1": 77.3, "POP_predicted": 0.6, "from_chain": True, "junk": 1})
    assert row["p1"] == 77.3 and row["pop_predicted"] == 0.6
    assert row["from_chain"] == 1            # bool coerced to int for indexing
    assert "junk" not in row


# --- Turso backend (HTTP pipeline) -------------------------------------------

def test_turso_arg_and_url_encoding():
    assert _encode_arg(None) == {"type": "null"}
    assert _encode_arg(True) == {"type": "integer", "value": "1"}
    assert _encode_arg(7) == {"type": "integer", "value": "7"}     # ints as strings
    assert _encode_arg(1.5) == {"type": "float", "value": 1.5}
    assert _encode_arg("x") == {"type": "text", "value": "x"}
    assert _decode_value({"type": "integer", "value": "42"}) == 42
    assert _decode_value({"type": "null"}) is None
    # libsql:// scheme is rewritten to https for the HTTP pipeline endpoint.
    assert _normalize_turso_url("libsql://db.turso.io") == "https://db.turso.io"


class _FakeTurso:
    """A libSQL HTTP-pipeline server backed by real sqlite3 — exercises the full
    encode -> SQL -> decode path without a network or live DB."""

    def __init__(self):
        import sqlite3
        self._c = sqlite3.connect(":memory:")

    def __call__(self, payload):
        results = []
        for req in payload["requests"]:
            if req["type"] == "close":
                results.append({"type": "ok", "response": {"type": "close"}})
                continue
            stmt = req["stmt"]
            args = [_decode_value(a) for a in stmt.get("args", [])]
            cur = self._c.execute(stmt["sql"], args)
            if cur.description:
                cols = [{"name": d[0]} for d in cur.description]
                rows = [[_enc(v) for v in row] for row in cur.fetchall()]
            else:
                cols, rows = [], []
            self._c.commit()
            results.append({"type": "ok", "response": {
                "type": "execute", "result": {"cols": cols, "rows": rows}}})
        return {"results": results}


def _enc(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def test_turso_roundtrip_against_fake_server(tmp_path):
    db = TursoQueryDB(_FakeTurso())    # ensure_schema runs the DDL through the poster
    rows = [
        _row("SPY", "s1", "2026-07-06T13:00:00Z", composite=69.0, from_chain=False, decision="GO"),
        _row("SPY", "s2", "2026-07-06T14:00:00Z", composite=48.0, from_chain=True, decision="PASS"),
    ]
    db.apply_run(build_run_manifest(rows[:1], scan_id="s1", timestamp="2026-07-06T13:00:00Z"))
    db.apply_candidates(rows)

    tl = db.ticker_timeline("SPY")
    assert [r["decision"] for r in tl] == ["GO", "PASS"]       # ordered by timestamp
    assert tl[0]["from_chain"] == 0 and tl[1]["from_chain"] == 1  # bool survived round-trip
    assert db.runs()[0]["n_candidates"] == 1


def test_history_sync_to_pushes_to_backend(tmp_path):
    # JSONL source of truth -> sync_to any QueryDB (the Turso push path).
    store = _store(tmp_path)
    ts = "2026-07-06T13:00:00Z"
    r = [_row("SPY", "s1", ts)]
    store.record(r, manifest=build_run_manifest(r, scan_id="s1", timestamp=ts))

    remote = TursoQueryDB(_FakeTurso())
    n = store.sync_to(remote)
    assert n == 1
    assert remote.ticker_timeline("SPY")[0]["decision"] == "GO"

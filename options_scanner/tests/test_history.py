"""Durable run history — JSONL source-of-truth + SQLite materialization."""

from __future__ import annotations

import json

from options_scanner.history import (
    HistoryStore,
    SqliteQueryDB,
    build_run_manifest,
    backfill_from_legacy,
    normalize_candidate_row,
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

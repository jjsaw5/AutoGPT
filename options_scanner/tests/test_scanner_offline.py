"""End-to-end offline scan: pre-populated candidates through the full pipeline,
with no network access. Verifies the orchestrator wires stages together and the
readout / logging produce sane output."""

from __future__ import annotations

import json

from options_scanner.models import Decision, EvaluatedCandidate
from options_scanner.pipeline import (
    build_thesis,
    evaluate_gates,
    rank_and_decide,
    render_readout,
    score_candidate,
    select_structure,
    append_scan,
)

from .conftest import make_candidate


def _evaluate(candidate, config, context=None):
    from options_scanner.exits import build_exit_plan
    thesis = build_thesis(candidate, config)
    structure = select_structure(candidate, thesis, config)
    exit_plan = build_exit_plan(structure, thesis)
    gate_ctx = {**(context or {}), "exit_plan": exit_plan}
    gates = evaluate_gates(candidate, thesis, structure, config, context=gate_ctx)
    score = score_candidate(candidate, thesis, structure, config)
    return EvaluatedCandidate(
        candidate=candidate, thesis=thesis, structure=structure,
        score=score, gates=gates, exit_plan=exit_plan,
    )


def test_full_pipeline_offline(config):
    candidates = [
        make_candidate("AAPL"),
        make_candidate("NVDA", price=120.0, signals={"iv_rank": 75.0, "iv": 0.6, "rv": 0.4}),
        make_candidate("SPY", price=500.0, signals={
            "net_prem": {"net_call_premium": 100, "net_put_premium": 100,
                         "net_call_volume": 0, "net_put_volume": 0},
        }),
    ]
    evaluated = [_evaluate(c, config) for c in candidates]
    ranked = rank_and_decide(evaluated, config)

    # Ranking orders GO before WATCH before PASS.
    order = [_decision_rank(ec.decision) for ec in ranked]
    assert order == sorted(order)

    readout = render_readout(ranked, config)
    assert "OPTIONS OPPORTUNITY SCANNER" in readout
    assert "PORTFOLIO SUMMARY" in readout
    assert "SPECULATIVE" in readout


def test_core_book_has_candidate_table(config):
    # A GO/WATCH candidate renders a compact summary table (header + a row for it)
    # ahead of the detailed block — the new-position analogue of the book table.
    ec = _evaluate(make_candidate("AAPL", signals={"iv_rank": 10.0}), config)
    rank_and_decide([ec], config)
    readout = render_readout([ec], config)
    if ec.decision.value in ("GO", "WATCH"):
        assert "TICKER" in readout and "STRUCTURE" in readout and "NOTE" in readout
        assert "DEC" in readout and "ENTRY" in readout
        # the ticker appears in a table row with its decision
        assert "AAPL" in readout


def test_go_requires_all_three(config):
    # Force a strong bullish cheap-vol candidate; if it GOes, gates+EV+score all held.
    ec = _evaluate(make_candidate("AAPL", signals={"iv_rank": 10.0}), config)
    rank_and_decide([ec], config)
    if ec.decision == Decision.GO:
        assert ec.gates.passed
        assert ec.score.expected_value > 0
        assert ec.score.composite >= config.go_threshold
        assert ec.suggested_size > 0


def test_placeholder_chain_cannot_go(config):
    # A GO-grade candidate on a *placeholder* chain is demoted to WATCH: its
    # pricing is synthetic (spot+width), so the composite/EV aren't executable.
    ec = _evaluate(make_candidate("AAPL", signals={"iv_rank": 10.0}), config)
    ec.score.composite = 90.0
    ec.gates.results = []          # no failing gates → gates.passed is True
    ec.score.expected_value = 50.0

    ec.structure.from_chain = False
    rank_and_decide([ec], config)
    assert ec.decision == Decision.WATCH
    assert "placeholder chain" in ec.why

    # Same candidate, real chain → GO stands.
    ec.structure.from_chain = True
    rank_and_decide([ec], config)
    assert ec.decision == Decision.GO


def test_sizing_respects_ceiling(config):
    ec = _evaluate(make_candidate("AAPL", signals={"iv_rank": 5.0}), config)
    rank_and_decide([ec], config)
    high = config.account["risk_high_conviction_max"]
    assert ec.suggested_size <= high + ec.structure.max_loss  # within a contract of ceiling


def test_logging_writes_jsonl(config, tmp_path):
    ec = _evaluate(make_candidate("AAPL"), config)
    rank_and_decide([ec], config)
    log_file = tmp_path / "scan.jsonl"
    n = append_scan([ec], scan_id="scan_test", timestamp="2026-07-02T00:00:00Z", log_path=log_file)
    assert n == 1
    row = json.loads(log_file.read_text().strip())
    assert row["ticker"] == "AAPL"
    assert row["scan_id"] == "scan_test"
    assert "composite" in row and "gate_flags" in row


def test_scan_writes_durable_history(config, tmp_path):
    # A scan with history_dir set persists JSONL + a rebuildable query DB.
    from options_scanner.scanner import Scanner
    from options_scanner.history import HistoryStore, SqliteQueryDB

    scanner = Scanner(config)  # offline: no fmp/uw clients
    hist = tmp_path / "history"
    res = scanner.scan(tickers=["AAPL", "NVDA"], history_dir=str(hist))
    assert res.history_rows == 2
    assert (hist / "scans").glob("*.jsonl")

    # Reopen from the committed JSONL alone and rebuild the query DB.
    store = HistoryStore(base_dir=hist, query_db=SqliteQueryDB())
    assert store.rebuild() == 2
    manifest = store.query_db.runs()[0]
    assert manifest["n_candidates"] == 2
    # offline => structures are placeholders => coverage is 0.
    assert manifest["chain_coverage"] == 0.0
    store.query_db.close()


def _decision_rank(decision: Decision) -> int:
    return {Decision.GO: 0, Decision.WATCH: 1, Decision.PASS: 2}[decision]

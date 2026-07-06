"""Trade journal: shadow recording, live-chain resolution, calibration report."""

from __future__ import annotations

from datetime import datetime, timezone

from options_scanner import calibration
from options_scanner.journal import (
    Ledger, record_shadows, resolve_open, reconcile_taken, is_shadow_candidate,
)
from options_scanner.models import (
    Catalyst, Decision, Direction, EvaluatedCandidate, GateReport, GateResult,
    Horizon, Leg, Score, Structure, StructureType, Thesis, VolRegime,
)

from .conftest import make_candidate


def _ec(*, ticker="ABC", composite=78.0, ev=50.0, decision=Decision.GO,
        gate_fail=None, structure_type=StructureType.CREDIT_VERTICAL,
        legs=None, expiry="2026-08-21", pop=0.65):
    legs = legs or [
        Leg("sell", "put", 100.0, expiry, mid=6.0),
        Leg("buy", "put", 95.0, expiry, mid=4.0),
    ]
    results = [GateResult(g, True) for g in ("G1", "G2", "G3", "G4", "G5")]
    for g in (gate_fail or []):
        results.append(GateResult(g, False, "blocked"))
    structure = Structure(
        structure_type=structure_type, legs=legs,
        max_profit=200.0, max_loss=300.0, breakevens=[98.0],
        expiry=expiry, from_chain=True,
    )
    thesis = Thesis(
        direction=Direction.BULLISH, conviction=0.6, vol_regime=VolRegime.RICH,
        horizon=Horizon.POSITION, catalyst=Catalyst.FLOW_ONLY,
    )
    score = Score(composite=composite, pop=pop, expected_value=ev)
    return EvaluatedCandidate(
        candidate=make_candidate(ticker), thesis=thesis, structure=structure,
        score=score, gates=GateReport(results), decision=decision,
        size_tier="standard",
    )


def test_is_shadow_candidate(config):
    assert is_shadow_candidate(_ec(decision=Decision.GO), config)
    # budget-blocked: GO-worthy but only G6 fails
    blocked = _ec(composite=80, ev=10, decision=Decision.WATCH, gate_fail=["G6"])
    assert is_shadow_candidate(blocked, config)
    # blocked by a non-budget gate => NOT a shadow
    real_fail = _ec(composite=80, ev=10, decision=Decision.WATCH, gate_fail=["G1"])
    assert not is_shadow_candidate(real_fail, config)
    # low composite => not a shadow
    assert not is_shadow_candidate(_ec(composite=40, decision=Decision.PASS), config)
    # clean WATCH: passes all gates, positive EV, above the watch line => tracked
    clean_watch = _ec(composite=66, ev=40, decision=Decision.WATCH)
    assert is_shadow_candidate(clean_watch, config)
    # a WATCH with a failing gate is NOT tracked
    dirty_watch = _ec(composite=66, ev=40, decision=Decision.WATCH, gate_fail=["G2"])
    assert not is_shadow_candidate(dirty_watch, config)


def test_record_and_dedupe(config, tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    now = datetime(2026, 7, 2, tzinfo=timezone.utc)
    n = record_shadows(ledger, [_ec(ticker="ABC")], scan_id="s1", config=config, now=now)
    assert n == 1
    # same setup next scan => not re-opened
    n2 = record_shadows(ledger, [_ec(ticker="ABC")], scan_id="s2", config=config, now=now)
    assert n2 == 0
    assert len(ledger.open_entries()) == 1


def test_resolution_win(config, tmp_path):
    ledger = Ledger(tmp_path / "l.json")
    now = datetime(2026, 7, 2, tzinfo=timezone.utc)
    record_shadows(ledger, [_ec(ticker="ABC")], scan_id="s1", config=config, now=now)

    # Credit spread decays in the seller's favor (both puts cheaper).
    def provider(ticker, expiry):
        return {("put", 100.0): 0.5, ("put", 95.0): 0.2}

    later = datetime(2026, 8, 15, tzinfo=timezone.utc)  # past the +35d resolve_by
    resolved = resolve_open(ledger, provider, now=later)
    assert resolved == 1
    e = ledger.resolved()[0]
    # sell 100p: (0.5-6.0)*-100=+550 ; buy 95p: (0.2-4.0)*100=-380 ; net +170
    assert e.pnl == 170.0
    assert e.outcome == "win"
    assert e.status == "closed"
    assert e.resolution_method == "chain_reprice"


def test_resolution_respects_resolve_by(config, tmp_path):
    ledger = Ledger(tmp_path / "l.json")
    now = datetime(2026, 7, 2, tzinfo=timezone.utc)
    record_shadows(ledger, [_ec()], scan_id="s1", config=config, now=now)
    provider = lambda t, e: {("put", 100.0): 0.5, ("put", 95.0): 0.2}
    # Same day => not yet due.
    assert resolve_open(ledger, provider, now=now) == 0
    # force overrides.
    assert resolve_open(ledger, provider, now=now, force=True) == 1


def test_reconcile_taken(config, tmp_path):
    ledger = Ledger(tmp_path / "l.json")
    now = datetime(2026, 7, 2, tzinfo=timezone.utc)
    record_shadows(ledger, [_ec(ticker="ABC")], scan_id="s1", config=config, now=now)
    positions = [
        {"ticker": "ABC", "expiry": "2026-08-21", "action": "sell",
         "option_type": "put", "strike": 100.0, "quantity": 1, "entry_price": 210.0},
        {"ticker": "ABC", "expiry": "2026-08-21", "action": "buy",
         "option_type": "put", "strike": 95.0, "quantity": 1, "entry_price": 0.0},
    ]
    out = reconcile_taken(ledger, positions, now=now)
    assert out["promoted"] == 1
    e = next(iter(ledger.entries.values()))
    assert e.kind == "taken"


def test_calibration_report_runs(config, tmp_path):
    ledger = Ledger(tmp_path / "l.json")
    now = datetime(2026, 7, 2, tzinfo=timezone.utc)
    record_shadows(ledger, [_ec(ticker="ABC", pop=0.7)], scan_id="s1", config=config, now=now)
    record_shadows(ledger, [_ec(ticker="XYZ", pop=0.4)], scan_id="s1", config=config, now=now)
    # Resolve one win, one loss.
    resolve_open(ledger, lambda t, e: {("put", 100.0): 0.2, ("put", 95.0): 0.1},
                 now=now, force=True)
    text = calibration.report(ledger)
    assert "CALIBRATION REPORT" in text
    assert "Brier score" in text
    brier = calibration.brier_score(list(ledger.entries.values()))
    assert brier is None or 0.0 <= brier <= 1.0

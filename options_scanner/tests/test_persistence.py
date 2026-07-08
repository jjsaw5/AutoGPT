"""GO persistence — a single-session GO is provisional; a repeated one confirms."""

from __future__ import annotations

from options_scanner.persistence import (
    CONFIRMED, PROVISIONAL, go_persistence_status,
)


def _row(decision=None, composite=None):
    return {"decision": decision, "effective_composite": composite}


def test_first_time_go_is_provisional():
    # No prior scans at GO-grade => this GO is the first => provisional.
    assert go_persistence_status([], go_threshold=72) == PROVISIONAL
    assert go_persistence_status(
        [_row("WATCH", 60), _row("PASS", 40)], go_threshold=72
    ) == PROVISIONAL


def test_second_session_confirms():
    # One prior GO-grade scan + the current one = 2 sessions => confirmed.
    assert go_persistence_status([_row("GO", 78)], go_threshold=72) == CONFIRMED
    # Composite over the line (even if decision wasn't GO) counts as GO-grade.
    assert go_persistence_status([_row("WATCH", 74)], go_threshold=72) == CONFIRMED


def test_lookback_window_excludes_stale_go():
    # An old GO outside the lookback window doesn't confirm a fresh one.
    timeline = [_row("GO", 80)] + [_row("PASS", 30) for _ in range(5)]
    assert go_persistence_status(
        timeline, go_threshold=72, lookback=4
    ) == PROVISIONAL  # the lone GO is 5 scans back, outside the last 4


def test_min_sessions_one_disables_gate():
    # min_sessions=1 => persistence off, every GO confirmed immediately.
    assert go_persistence_status([], go_threshold=72, min_sessions=1) == CONFIRMED


def test_higher_min_sessions_needs_more_history():
    # Requiring 3 sessions: one prior GO isn't enough (1 prior + current = 2 < 3).
    assert go_persistence_status(
        [_row("GO", 80)], go_threshold=72, min_sessions=3
    ) == PROVISIONAL
    assert go_persistence_status(
        [_row("GO", 80), _row("GO", 79)], go_threshold=72, min_sessions=3
    ) == CONFIRMED


def test_scanner_marks_go_provisional_without_history(config):
    # A GO with no history to check against can't be confirmed => provisional.
    from types import SimpleNamespace
    from options_scanner.models import Decision
    from options_scanner.scanner import Scanner
    ec = SimpleNamespace(decision=Decision.GO, ticker="BAC", go_persistence="")
    Scanner(config)._annotate_persistence([ec], None)
    assert ec.go_persistence == PROVISIONAL


def test_scanner_confirms_go_with_prior_go_in_history(config, tmp_path):
    # A prior GO-grade scan for the ticker in the mirror => this GO confirms.
    from types import SimpleNamespace
    from options_scanner.models import Decision
    from options_scanner.scanner import Scanner
    from options_scanner.history import SqliteQueryDB

    db = SqliteQueryDB(f"{tmp_path}/scanner.sqlite")
    db.apply_candidates([{
        "scan_id": "s1", "timestamp": "2026-07-07T15:00:00Z", "ticker": "BAC",
        "decision": "GO", "composite": 75, "effective_composite": 75,
    }])
    db.close()
    ec = SimpleNamespace(decision=Decision.GO, ticker="BAC", go_persistence="")
    Scanner(config)._annotate_persistence([ec], str(tmp_path))
    assert ec.go_persistence == CONFIRMED

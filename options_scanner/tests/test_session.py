"""Full session orchestration — scan + position review + combined persistence."""

from __future__ import annotations

import json

from options_scanner.history import HistoryStore, SqliteQueryDB
from options_scanner.scanner import Scanner
from options_scanner.session import (
    PositionInput,
    SessionRunner,
    load_positions,
)


def test_load_positions_from_file(tmp_path):
    p = tmp_path / "positions.json"
    p.write_text(json.dumps([
        {"ticker": "dkng", "direction": 1, "is_long_premium": True,
         "pnl_pct": 0.02, "dte": 46, "days_to_earnings": 30, "account": "Individual"},
    ]))
    pos = load_positions(p)
    assert len(pos) == 1
    assert pos[0].ticker == "DKNG" and pos[0].account == "Individual"


def test_session_reviews_held_names_and_persists(config, tmp_path):
    # Offline scanner; a held name (AAPL) gets scanned via extra_tickers so the
    # review is graded against a live thesis and persisted alongside candidates.
    scanner = Scanner(config)
    positions = [
        PositionInput("AAPL", direction=1, is_long_premium=True,
                      pnl_pct=0.05, dte=40, account="Individual"),
    ]
    hist = tmp_path / "history"
    result = SessionRunner(scanner).run(positions, history_dir=str(hist))

    # A review was produced for the holding.
    assert len(result.reviews) == 1
    r = result.reviews[0]
    assert r.ticker == "AAPL" and r.action in {"CLOSE", "TRIM", "ROLL", "HOLD", "WATCH"}

    # Combined readout carries both sections.
    assert "POSITION REVIEW" in result.readout
    assert "AAPL" in result.readout

    # Held name was scanned (extra_tickers) — it's in the candidate set.
    assert "AAPL" in {ec.ticker for ec in result.scan.evaluated}

    # Persisted: reviews queryable from the rebuilt store.
    store = HistoryStore(base_dir=hist, query_db=SqliteQueryDB())
    store.rebuild()
    ph = store.query_db.position_history("AAPL")
    assert len(ph) == 1 and ph[0]["account"] == "Individual"


def test_session_scan_only_when_no_positions(config, tmp_path):
    # No positions -> scan still runs; review section notes the empty book.
    result = SessionRunner(Scanner(config)).run([], history_dir=str(tmp_path / "h"))
    assert result.reviews == []
    assert "no open positions" in result.readout.lower()


def test_unscannable_holding_still_reviewed(config):
    # A holding whose underlying isn't scannable falls back to a neutral thesis
    # rather than dropping off the book.
    scanner = Scanner(config)
    # Ticker unlikely to resolve offline still yields a review row.
    pos = [PositionInput("ZZZZ", direction=1, is_long_premium=True, pnl_pct=-0.5)]
    result = SessionRunner(scanner).run(pos)
    assert len(result.reviews) == 1
    # Blew the stop -> CLOSE regardless of thesis availability.
    assert result.reviews[0].action == "CLOSE"

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


def test_exposure_from_positions_maps_direction_and_ticker():
    from options_scanner.session import _exposure_from_positions
    pos = [
        PositionInput("NFLX", direction=1, is_long_premium=False, risk=311, sector="Comm"),
        PositionInput("PFE", direction=-1, is_long_premium=True),
    ]
    exp = _exposure_from_positions(pos)
    assert exp[0] == {"ticker": "NFLX", "direction": "bullish", "sector": "Comm", "risk": 311.0}
    assert exp[1]["ticker"] == "PFE" and exp[1]["direction"] == "bearish" and exp[1]["risk"] == 0.0


def test_session_blocks_candidate_on_held_name(config):
    # Holding NFLX => the scan's NFLX candidate must fail G12 (already held),
    # so the session never re-proposes a name that's already on the book.
    scanner = Scanner(config)
    pos = [PositionInput("NFLX", direction=1, is_long_premium=False, pnl_pct=0.0, dte=17)]
    result = SessionRunner(scanner).run(pos)
    nflx = next((ec for ec in result.scan.evaluated if ec.ticker == "NFLX"), None)
    assert nflx is not None
    g12 = next(r for r in nflx.gates.results if r.gate_id == "G12")
    assert not g12.passed and "already hold" in g12.detail


def test_review_render_flags_stale_pnl(config):
    # A holding with no pnl_asof shows a '*' and the stale-book footnote; a
    # live-stamped one does not.
    from options_scanner.session import _render_reviews, _review_from_scan
    stale = PositionInput("ZZZZ", direction=1, is_long_premium=True, pnl_pct=-0.5)
    live = PositionInput("YYYY", direction=1, is_long_premium=True, pnl_pct=-0.5,
                         pnl_asof="2026-07-08T14:00:00Z")
    rows = [(_review_from_scan(p, {}), p) for p in (stale, live)]
    out = _render_reviews(rows)
    assert "-50%*" in out and "entry value, not live" in out
    # The live-stamped row's P&L carries no star.
    assert "-50% " in out or "-50%\n" in out
    # A holding whose underlying isn't scannable falls back to a neutral thesis
    # rather than dropping off the book.
    scanner = Scanner(config)
    # Ticker unlikely to resolve offline still yields a review row.
    pos = [PositionInput("ZZZZ", direction=1, is_long_premium=True, pnl_pct=-0.5)]
    result = SessionRunner(scanner).run(pos)
    assert len(result.reviews) == 1
    # Blew the stop -> CLOSE regardless of thesis availability.
    assert result.reviews[0].action == "CLOSE"

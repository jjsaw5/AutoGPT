"""Full session — one operation that runs *everything*, the same way every time.

The motivation is process integrity: "run a full session" must not depend on how
the request is phrased. A session is a fixed, ordered checklist:

    1. Market regime
    2. New-entry scan  -> ranked GO / WATCH / PASS readout
    3. Position review of the live book -> grade + action per holding
    4. Journal: shadow-track candidates (taken-trade reconcile is separate)
    5. Durable history + Turso — BOTH candidates AND position reviews
    6. Combined readout

The one human-gated input is the live book: option positions come from the
Robinhood MCP (read-only, agent-driven), so the caller passes them in as
``PositionInput`` rows. Everything downstream is deterministic. The scanner is
told to *also* scan every held underlying (``extra_tickers``) so each review is
graded against a live thesis, not a stale one.

Recommend-only: a review's action (CLOSE/TRIM/HOLD/…) is a suggestion; no order
is ever placed here.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .models import Direction
from .position_review import PositionReview, review_position
from .scanner import ScanResult, Scanner

logger = logging.getLogger(__name__)


@dataclass
class PositionInput:
    """Broker-derived facts about one held option position (from Robinhood).

    These are the things only the broker knows; the *thesis* on the underlying
    (direction/conviction/vol regime/IV rank) is supplied fresh by the scan.
    """
    ticker: str
    direction: int              # +1 bullish / -1 bearish / 0 neutral (position bias)
    is_long_premium: bool
    pnl_pct: Optional[float] = None
    dte: Optional[int] = None
    days_to_earnings: Optional[int] = None
    account: str = ""           # which book (e.g. "Individual" / "Agentic")

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PositionInput":
        return cls(
            ticker=str(d["ticker"]).upper(),
            direction=int(d.get("direction", 0)),
            is_long_premium=bool(d.get("is_long_premium", True)),
            pnl_pct=d.get("pnl_pct"),
            dte=d.get("dte"),
            days_to_earnings=d.get("days_to_earnings"),
            account=str(d.get("account", "")),
        )


def load_positions(path: str | Path) -> list[PositionInput]:
    """Load a positions JSON file (a list of position objects)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):            # tolerate {"positions": [...]}
        data = data.get("positions", [])
    return [PositionInput.from_dict(d) for d in data]


@dataclass
class SessionResult:
    scan: ScanResult
    reviews: list[PositionReview]
    readout: str
    history_rows: int = 0


_DIR_TO_INT = {Direction.BULLISH: 1, Direction.BEARISH: -1, Direction.NEUTRAL: 0}


def _review_from_scan(pos: PositionInput, evaluated_by_ticker: dict) -> PositionReview:
    """Grade one held position against its *current* scanned thesis.

    Falls back to a neutral, low-conviction thesis when the underlying couldn't
    be scanned (e.g. no data), so an un-scannable holding still gets a review
    rather than silently dropping off the book.
    """
    ec = evaluated_by_ticker.get(pos.ticker)
    days_to_earnings = pos.days_to_earnings
    if ec is not None:
        t = ec.thesis
        thesis_dir = _DIR_TO_INT.get(t.direction, 0)
        conviction = t.conviction
        vol_regime = t.vol_regime.value
        iv_rank = t.iv_rank
        driver = t.direction_driver()
        # Earnings timing is market data, not a broker fact — take it from the
        # live thesis unless the caller explicitly supplied it.
        if days_to_earnings is None:
            days_to_earnings = t.days_to_earnings
    else:
        thesis_dir, conviction, vol_regime, iv_rank, driver = 0, 0.0, "fair", None, "no data"

    return review_position(
        pos.ticker,
        direction=pos.direction,
        is_long_premium=pos.is_long_premium,
        pnl_pct=pos.pnl_pct,
        dte=pos.dte,
        days_to_earnings=days_to_earnings,
        thesis_dir=thesis_dir,
        thesis_conviction=conviction,
        vol_regime=vol_regime,
        iv_rank=iv_rank,
        driver=driver,
    )


def _review_row(r: PositionReview, pos: PositionInput, *, scan_id: str, timestamp: str) -> dict:
    return {
        "scan_id": scan_id, "timestamp": timestamp, "ticker": r.ticker,
        "account": pos.account, "grade": r.grade, "action": r.action,
        "reason": r.reason, "score": r.score, "aligned": r.aligned,
        "direction": pos.direction, "is_long_premium": pos.is_long_premium,
        "pnl_pct": pos.pnl_pct, "dte": pos.dte,
        "days_to_earnings": pos.days_to_earnings,
    }


def _render_reviews(rows: list[tuple[PositionReview, PositionInput]]) -> str:
    if not rows:
        return "[4] POSITION REVIEW\n  (no open positions supplied)\n"
    lines = ["[4] POSITION REVIEW  (grade + action; recommend-only)"]
    # CLOSE first, then TRIM/ROLL, then HOLD/WATCH — most-urgent on top.
    order = {"CLOSE": 0, "ROLL": 1, "TRIM": 2, "HOLD": 3, "WATCH": 4}
    for r, pos in sorted(rows, key=lambda x: order.get(x[0].action, 9)):
        acct = f" [{pos.account}]" if pos.account else ""
        pnl = f"{pos.pnl_pct:+.0%}" if pos.pnl_pct is not None else "n/a"
        dte = f"{pos.dte}d" if pos.dte is not None else "n/a"
        lines.append(
            f"  {r.ticker}{acct}  {r.grade:>2} → {r.action:<5}  "
            f"(P&L {pnl} · {dte} · score {r.score})"
        )
        lines.append(f"     {r.reason}")
    return "\n".join(lines) + "\n"


class SessionRunner:
    """Orchestrates a full session on top of a :class:`Scanner`."""

    def __init__(self, scanner: Scanner) -> None:
        self.scanner = scanner

    def run(
        self,
        positions: list[PositionInput],
        *,
        context: dict[str, Any] | None = None,
        history_dir: str | None = None,
        journal_path: str | None = None,
        now: datetime | None = None,
    ) -> SessionResult:
        now = now or datetime.now(timezone.utc)
        held = [p.ticker for p in positions]

        # 1-2, 4: scan the universe PLUS every held underlying, but let the
        # session own history writing (history_dir=None here) so candidates and
        # reviews land together under one scan_id.
        scan = self.scanner.scan(
            extra_tickers=held, context=context,
            journal_path=journal_path, now=now,
        )
        by_ticker = {ec.ticker: ec for ec in scan.evaluated}

        # 3: grade each holding against its fresh thesis.
        paired = [(_review_from_scan(p, by_ticker), p) for p in positions]
        reviews = [r for r, _ in paired]

        # 5: persist candidates AND reviews under the same scan_id.
        history_rows = 0
        if history_dir:
            review_rows = [
                _review_row(r, p, scan_id=scan.scan_id, timestamp=scan.timestamp)
                for r, p in paired
            ]
            history_rows = self.scanner._persist_history(
                scan.evaluated, scan_id=scan.scan_id, timestamp=scan.timestamp,
                regime=scan.regime, history_dir=history_dir, review_rows=review_rows,
            )

        # 6: combined readout — new entries, then the book.
        readout = scan.readout.rstrip() + "\n\n" + _render_reviews(paired)
        return SessionResult(
            scan=scan, reviews=reviews, readout=readout, history_rows=history_rows,
        )

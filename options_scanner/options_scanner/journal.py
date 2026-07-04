"""Trade journal / ledger (spec §9 — the calibration feedback loop).

Two tracks, both persisted to a JSON ledger:

* **taken** — trades you actually put on (auto-reconciled from Robinhood fills,
  annotatable), so realized PnL and slippage feed calibration.
* **shadow** — high-conviction setups you did *not* take: every GO plus any
  candidate that scored GO-worthy (composite ≥ GO, EV > 0) and was blocked only
  by the risk caps (G6/G7). These measure the model's *power* independent of
  budget/execution.

Open entries are later **resolved** by re-pricing the exact legs against the
live chain (`resolution_method="chain_reprice"`), producing paper/real PnL and a
win/loss/scratch outcome. `calibration.py` then turns resolved entries into a
Brier score, composite-bucket attribution, and a regime/structure audit.

The module is pure data + logic: it never calls MCP/HTTP itself. Callers pass a
``chain_provider`` (built from the UW client) for resolution and a list of
broker positions for reconciliation.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .config import Config
from .models import EvaluatedCandidate

# Calendar days after entry at which a shadow setup is resolved (or its expiry,
# whichever is sooner).
_HORIZON_DAYS = {"intraday": 1, "swing": 10, "position": 35, "leaps": 180}

# ChainProvider(ticker, expiry) -> {(option_type, strike): mid_price}
ChainProvider = Callable[[str, str], dict[tuple[str, float], float]]


@dataclass
class LedgerLeg:
    action: str
    option_type: str
    strike: float
    expiry: str
    entry_mid: float | None = None
    qty: int = 1


@dataclass
class LedgerEntry:
    setup_key: str
    kind: str            # "taken" | "shadow"
    status: str          # "open" | "closed"
    scan_id: str
    opened_at: str
    resolve_by: str
    ticker: str
    structure: str
    expiry: str | None
    legs: list[LedgerLeg]
    decision: str
    composite: float
    pop_predicted: float
    vol_regime: str
    direction: str
    catalyst: str
    max_profit: float | None
    max_loss: float | None
    size_tier: str
    blocked_by: list[str] = field(default_factory=list)
    # taken-only
    entry_fill: float | None = None      # real net premium filled (per contract $)
    size: float | None = None            # $ risk actually deployed
    slippage: float | None = None        # fill vs entry mid
    notes: str = ""
    # resolution
    resolved_at: str | None = None
    exit_value: float | None = None
    pnl: float | None = None
    pnl_pct: float | None = None
    outcome: str = "open"                # win | loss | scratch | open
    resolution_method: str | None = None


# --- identity -----------------------------------------------------------------
def setup_key(ec: EvaluatedCandidate) -> str:
    legs = sorted(
        f"{l.action[0]}{l.option_type[0]}{l.strike:g}" for l in ec.structure.legs
    )
    exp = ec.structure.expiry or "?"
    return f"{ec.ticker}:{ec.structure.structure_type.value}:{exp}:{'|'.join(legs)}"


def is_shadow_candidate(ec: EvaluatedCandidate, config: Config) -> bool:
    """GO, or GO-worthy but blocked ONLY by the risk caps G6/G7 (budget-blocked)."""
    from .models import Decision

    if ec.decision == Decision.GO:
        return True
    if ec.score.composite >= config.go_threshold and ec.score.expected_value > 0:
        fails = {f.gate_id for f in ec.gates.failures}
        if fails and fails <= {"G6", "G7"}:
            return True
    return False


# --- ledger store -------------------------------------------------------------
class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.entries: dict[str, LedgerEntry] = {}

    @classmethod
    def load(cls, path: str | Path) -> "Ledger":
        ledger = cls(path)
        if ledger.path.exists():
            raw = json.loads(ledger.path.read_text() or "{}")
            for key, data in raw.items():
                legs = [LedgerLeg(**l) for l in data.pop("legs", [])]
                ledger.entries[key] = LedgerEntry(legs=legs, **data)
        return ledger

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        out = {k: asdict(v) for k, v in self.entries.items()}
        self.path.write_text(json.dumps(out, indent=2))

    def has_open(self, key: str) -> bool:
        e = self.entries.get(key)
        return e is not None and e.status == "open"

    def open_entries(self) -> list[LedgerEntry]:
        return [e for e in self.entries.values() if e.status == "open"]

    def resolved(self) -> list[LedgerEntry]:
        return [e for e in self.entries.values() if e.status == "closed"]


# --- recording ----------------------------------------------------------------
def _resolve_by(horizon: str, opened: datetime, expiry: str | None) -> str:
    days = _HORIZON_DAYS.get(horizon, 10)
    target = opened + timedelta(days=days)
    if expiry:
        try:
            exp = datetime.strptime(expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            target = min(target, exp)
        except ValueError:
            pass
    return target.date().isoformat()


def record_shadows(
    ledger: Ledger,
    evaluated: list[EvaluatedCandidate],
    *,
    scan_id: str,
    config: Config,
    now: datetime,
) -> int:
    """Open a shadow entry for each GO / budget-blocked setup not already open."""
    opened = 0
    for ec in evaluated:
        if not is_shadow_candidate(ec, config):
            continue
        key = setup_key(ec)
        if ledger.has_open(key):
            continue
        ledger.entries[key] = _entry_from_candidate(ec, key, "shadow", scan_id, now, config)
        opened += 1
    return opened


def _entry_from_candidate(
    ec: EvaluatedCandidate, key: str, kind: str, scan_id: str,
    now: datetime, config: Config,
) -> LedgerEntry:
    legs = [
        LedgerLeg(l.action, l.option_type, l.strike, l.expiry, entry_mid=l.mid)
        for l in ec.structure.legs
    ]
    blocked = [f.gate_id for f in ec.gates.failures]
    return LedgerEntry(
        setup_key=key, kind=kind, status="open", scan_id=scan_id,
        opened_at=now.isoformat(),
        resolve_by=_resolve_by(ec.thesis.horizon.value, now, ec.structure.expiry),
        ticker=ec.ticker, structure=ec.structure.structure_type.value,
        expiry=ec.structure.expiry, legs=legs,
        decision=ec.decision.value, composite=ec.score.composite,
        pop_predicted=ec.score.pop, vol_regime=ec.thesis.vol_regime.value,
        direction=ec.thesis.direction.value, catalyst=ec.thesis.catalyst.value,
        max_profit=ec.structure.max_profit, max_loss=ec.structure.max_loss,
        size_tier=ec.size_tier, blocked_by=blocked,
    )


# --- resolution ---------------------------------------------------------------
def resolve_open(
    ledger: Ledger,
    provider: ChainProvider,
    *,
    now: datetime,
    force: bool = False,
    scratch_band: float = 0.05,
) -> int:
    """Re-price the exact legs of each open entry due for resolution.

    An entry resolves when ``now >= resolve_by`` (or ``force``). PnL is summed
    per leg from entry mid → current mid; outcome is win/loss/scratch with a
    ±``scratch_band``·max_loss dead zone. Returns the count resolved.
    """
    today = now.date().isoformat()
    resolved = 0
    for e in ledger.open_entries():
        if not force and today < e.resolve_by:
            continue
        if not e.expiry:
            continue
        mids = provider(e.ticker, e.expiry)
        pnl = 0.0
        complete = True
        for leg in e.legs:
            now_mid = mids.get((leg.option_type, leg.strike))
            if now_mid is None or leg.entry_mid is None:
                complete = False
                break
            sign = 1.0 if leg.action == "buy" else -1.0
            pnl += sign * (now_mid - leg.entry_mid) * 100 * leg.qty
        if not complete:
            continue  # leave open; try again next resolution pass
        e.pnl = round(pnl, 2)
        risk = e.max_loss or 0.0
        e.pnl_pct = round(pnl / risk, 3) if risk else None
        band = scratch_band * (risk or 1.0)
        e.outcome = "win" if pnl > band else "loss" if pnl < -band else "scratch"
        e.status = "closed"
        e.resolved_at = now.isoformat()
        e.resolution_method = "chain_reprice"
        resolved += 1
    return resolved


def uw_chain_provider(uw) -> ChainProvider:
    """A ChainProvider backed by the UW option-contracts endpoint."""
    from .pipeline.chain import parse_occ

    def provider(ticker: str, expiry: str) -> dict[tuple[str, float], float]:
        out: dict[tuple[str, float], float] = {}
        for row in uw.option_contracts(ticker, expiry=expiry):
            parsed = parse_occ(str(row.get("option_symbol", "")))
            if not parsed:
                continue
            opt_type, exp, strike = parsed
            if exp != expiry:
                continue
            try:
                bid = float(row.get("nbbo_bid"))
                ask = float(row.get("nbbo_ask"))
            except (TypeError, ValueError):
                continue
            if ask > 0:
                out[(opt_type, strike)] = round((bid + ask) / 2, 4)
        return out

    return provider


# --- taken-trade reconciliation ----------------------------------------------
def reconcile_taken(
    ledger: Ledger, positions: list[dict[str, Any]], *, now: datetime
) -> dict[str, int]:
    """Match broker option positions to tracked setups and mark them taken.

    ``positions`` is a normalized list of legs:
    ``{ticker, option_type, strike, expiry, action, quantity, entry_price}``.
    Positions are grouped by (ticker, expiry) into leg-sets and matched against
    each open entry's legs. A match promotes a shadow → taken (recording the
    real fill); an unmatched position with model context can be added as a
    standalone taken entry by the caller. Returns counts.
    """
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for p in positions:
        grouped.setdefault((p["ticker"], p["expiry"]), []).append(p)

    promoted = 0
    for e in ledger.entries.values():
        if e.kind == "taken" or not e.expiry:
            continue
        group = grouped.get((e.ticker, e.expiry))
        if not group:
            continue
        want = {(l.action, l.option_type, l.strike) for l in e.legs}
        have = {(p["action"], p["option_type"], p["strike"]) for p in group}
        if want <= have:
            e.kind = "taken"
            fills = [p.get("entry_price") for p in group if p.get("entry_price") is not None]
            e.entry_fill = round(sum(fills), 2) if fills else None
            if e.entry_fill is not None and e.max_loss:
                # slippage proxy: real fill net vs modeled entry (debit ≈ max_loss)
                e.slippage = round(e.entry_fill - e.max_loss, 2)
            promoted += 1
    return {"promoted": promoted}


def annotate(ledger: Ledger, setup_key: str, note: str) -> bool:
    e = ledger.entries.get(setup_key)
    if not e:
        return False
    e.notes = (e.notes + " | " + note).strip(" |") if e.notes else note
    return True

"""Stages 7-8 — Logging & calibration substrate (spec §9).

Every candidate on every scan is logged (not just taken trades) — that record
is where the calibration loop later re-derives weights, thresholds and POP
buckets. Rows are appended as JSON lines so they are trivially replayable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import EvaluatedCandidate

# §9a log schema (candidate row). Taken-trade fields are appended at fill time.
LOG_FIELDS = [
    "scan_id", "timestamp", "ticker", "cap_tier", "tier", "structure", "legs",
    "thesis_tag", "direction", "vol_regime", "catalyst_type", "days_to_catalyst",
    "iv_rank", "implied_move", "expected_move",
    "P1", "P2", "P3", "P4", "P5", "P6", "composite",
    "effective_composite", "regime_adj", "from_chain",
    "POP_predicted", "max_profit", "max_loss", "decision", "gate_flags",
]


def candidate_to_row(
    ec: EvaluatedCandidate, *, scan_id: str, timestamp: str
) -> dict[str, Any]:
    s = ec.score
    t = ec.thesis
    return {
        "scan_id": scan_id,
        "timestamp": timestamp,
        "ticker": ec.ticker,
        "cap_tier": ec.candidate.cap_tier.value if ec.candidate.cap_tier else None,
        "tier": ec.candidate.tier.value,
        "structure": ec.structure.structure_type.value,
        "legs": ec.structure.legs_str(),
        "thesis_tag": t.catalyst.value,
        "direction": t.direction.value,
        "vol_regime": t.vol_regime.value,
        "catalyst_type": t.catalyst.value,
        "days_to_catalyst": t.days_to_catalyst,
        "iv_rank": t.iv_rank,
        "implied_move": t.implied_move,
        "expected_move": t.expected_move,
        "P1": s.p1, "P2": s.p2, "P3": s.p3,
        "P4": s.p4, "P5": s.p5, "P6": s.p6,
        "composite": s.composite,
        # Decision basis: composite after the regime nudge, the nudge itself, and
        # whether the structure was priced off a *real* chain (vs a placeholder).
        # from_chain is the field that makes a phantom (rate-limited) GO auditable.
        "effective_composite": ec.effective_composite,
        "regime_adj": ec.regime_adj,
        "from_chain": ec.structure.from_chain,
        "POP_predicted": s.pop,
        "max_profit": ec.structure.max_profit,
        "max_loss": ec.structure.max_loss,
        "decision": ec.decision.value,
        "gate_flags": ec.gates.flags(),
    }


def append_scan(
    evaluated: list[EvaluatedCandidate],
    *,
    scan_id: str,
    timestamp: str,
    log_path: str | Path,
) -> int:
    """Append one JSON line per candidate. Returns the number of rows written."""
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        candidate_to_row(ec, scan_id=scan_id, timestamp=timestamp)
        for ec in evaluated
    ]
    with open(path, "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return len(rows)

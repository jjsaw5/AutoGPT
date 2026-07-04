"""Calibration reporting (spec §9b).

Turns resolved ledger entries into the feedback the model needs to earn trust in
its weights: POP calibration (Brier score), score attribution by composite
bucket, and a regime/structure win-rate audit. These are descriptive today; once
enough outcomes accrue (§9b step 3, ≥100), the pillar weights can be re-fit from
this same data.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from .journal import Ledger, LedgerEntry

_COMPOSITE_BUCKETS = [
    ("PASS <58", 0, 58),
    ("WATCH 58-71", 58, 72),
    ("GO 72-84", 72, 85),
    ("GO+ 85-100", 85, 101),
]


def _is_win(e: LedgerEntry) -> bool:
    return e.outcome == "win"


def _scored(entries: list[LedgerEntry]) -> list[LedgerEntry]:
    return [e for e in entries if e.outcome in ("win", "loss", "scratch")]


def brier_score(entries: list[LedgerEntry]) -> float | None:
    """Mean squared error of predicted POP vs realized win (0/1). Lower = better.

    Scratches are excluded (no clean win/loss label)."""
    scored = [e for e in entries if e.outcome in ("win", "loss")]
    if not scored:
        return None
    return round(mean((e.pop_predicted - (1.0 if _is_win(e) else 0.0)) ** 2 for e in scored), 4)


def composite_attribution(entries: list[LedgerEntry]) -> list[dict[str, Any]]:
    """Win rate + avg PnL% by composite bucket — the core §9b step 2 check."""
    rows = []
    scored = _scored(entries)
    for label, lo, hi in _COMPOSITE_BUCKETS:
        bucket = [e for e in scored if lo <= e.composite < hi]
        if not bucket:
            rows.append({"bucket": label, "n": 0, "win_rate": None, "avg_pnl_pct": None})
            continue
        wins = sum(1 for e in bucket if _is_win(e))
        pnls = [e.pnl_pct for e in bucket if e.pnl_pct is not None]
        rows.append({
            "bucket": label,
            "n": len(bucket),
            "win_rate": round(wins / len(bucket), 2),
            "avg_pnl_pct": round(mean(pnls), 3) if pnls else None,
        })
    return rows


def regime_structure_audit(entries: list[LedgerEntry]) -> list[dict[str, Any]]:
    """Win rate by vol regime × structure — down-weight what loses (§9b step 4)."""
    groups: dict[tuple[str, str], list[LedgerEntry]] = defaultdict(list)
    for e in _scored(entries):
        groups[(e.vol_regime, e.structure)].append(e)
    rows = []
    for (regime, structure), bucket in sorted(groups.items()):
        wins = sum(1 for e in bucket if _is_win(e))
        rows.append({
            "vol_regime": regime, "structure": structure, "n": len(bucket),
            "win_rate": round(wins / len(bucket), 2),
        })
    return rows


def slippage_summary(entries: list[LedgerEntry]) -> dict[str, Any]:
    """Fill-vs-mid slippage on taken trades (feeds P3/EV, §9b step 5)."""
    slips = [e.slippage for e in entries if e.kind == "taken" and e.slippage is not None]
    if not slips:
        return {"n": 0, "avg_slippage": None}
    return {"n": len(slips), "avg_slippage": round(mean(slips), 2)}


def report(ledger: Ledger) -> str:
    entries = list(ledger.entries.values())
    scored = _scored(entries)
    taken = [e for e in entries if e.kind == "taken"]
    shadow = [e for e in entries if e.kind == "shadow"]
    open_n = len(ledger.open_entries())

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("CALIBRATION REPORT (§9b)   — model is a hypothesis until this converges")
    lines.append("=" * 70)
    lines.append(
        f"Ledger: {len(entries)} entries "
        f"({len(taken)} taken, {len(shadow)} shadow) | "
        f"{len(scored)} resolved, {open_n} open"
    )

    brier = brier_score(entries)
    lines.append(f"\nPOP calibration — Brier score: {brier if brier is not None else '— (need resolved wins/losses)'}")
    if brier is not None:
        lines.append("  (0 = perfect, 0.25 = coin-flip baseline; lower is better)")

    lines.append("\nScore attribution by composite bucket:")
    lines.append(f"  {'bucket':14}{'n':>4}{'win_rate':>10}{'avg_pnl%':>10}")
    for r in composite_attribution(entries):
        wr = f"{r['win_rate']:.0%}" if r["win_rate"] is not None else "—"
        ap = f"{r['avg_pnl_pct']:+.1%}" if r["avg_pnl_pct"] is not None else "—"
        lines.append(f"  {r['bucket']:14}{r['n']:>4}{wr:>10}{ap:>10}")
    lines.append("  ↳ if WATCH wins as often as GO, recalibrate thresholds/weights.")

    audit = regime_structure_audit(entries)
    if audit:
        lines.append("\nRegime × structure win rate:")
        for r in audit:
            lines.append(
                f"  {r['vol_regime']:6} {r['structure']:20} n={r['n']:<3} win={r['win_rate']:.0%}"
            )

    slip = slippage_summary(entries)
    if slip["n"]:
        lines.append(f"\nExecution: avg slippage over {slip['n']} taken = ${slip['avg_slippage']}")

    if len(scored) < 100:
        lines.append(
            f"\n⚠ {len(scored)}/100 resolved outcomes — below the threshold to re-fit "
            "pillar weights by logistic regression (§9b step 3). Keep logging."
        )
    return "\n".join(lines)

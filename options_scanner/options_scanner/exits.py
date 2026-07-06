"""Exit engine — a predefined exit plan for every trade, before entry.

"No exit plan, no trade." A scanner that finds entries but never defines exits
loses money on inconsistent management. This builds a concrete plan per structure
family — profit target, stop, time stop, short-delta stop, pre-earnings exit, and
an invalidation level — attached to every candidate and surfaced with every GO.
Gate G11 blocks any tradeable structure that lacks a complete plan.

Targets/stops are placeholders (priors) like the rest of the model — but they are
*explicit and consistent*, which is the point, and they feed the journal so the
calibration loop can tune them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import Structure, StructureType, Thesis

_BUY_FAMILY = {
    StructureType.LONG_CALL, StructureType.LONG_PUT, StructureType.LEAPS,
    StructureType.LONG_STRADDLE, StructureType.DEBIT_VERTICAL,
}
_SELL_FAMILY = {StructureType.CREDIT_VERTICAL, StructureType.IRON_CONDOR}


@dataclass
class ExitPlan:
    profit_target_pct: Optional[float] = None   # % of max profit (or % gain on debit)
    profit_target_value: Optional[float] = None  # $ P&L at which to take profit
    stop_loss_pct: Optional[float] = None        # % of risk
    stop_loss_value: Optional[float] = None      # $ P&L at which to cut
    time_stop_days: Optional[int] = None         # exit if not working by then
    short_delta_stop: Optional[float] = None     # roll/close if |short Δ| exceeds
    pre_earnings_exit: bool = False              # close before an earnings print
    invalidation: str = ""                       # thesis-invalidation trigger
    notes: list[str] = field(default_factory=list)

    def is_complete(self) -> bool:
        """A usable plan needs a profit target, a stop, and an invalidation."""
        has_target = self.profit_target_value is not None
        has_stop = self.stop_loss_value is not None
        return has_target and has_stop and bool(self.invalidation)

    def summary(self) -> str:
        parts = []
        if self.profit_target_value is not None:
            parts.append(f"take +${self.profit_target_value:.0f} ({self.profit_target_pct:.0%})")
        if self.stop_loss_value is not None:
            parts.append(f"stop −${self.stop_loss_value:.0f}")
        if self.time_stop_days is not None:
            parts.append(f"time {self.time_stop_days}d")
        if self.short_delta_stop is not None:
            parts.append(f"roll if short Δ>{self.short_delta_stop:.2f}")
        if self.pre_earnings_exit:
            parts.append("exit before earnings")
        return " · ".join(parts) + (f" · invalidate: {self.invalidation}" if self.invalidation else "")


def build_exit_plan(structure: Structure, thesis: Thesis) -> ExitPlan | None:
    st = structure.structure_type
    # No plan for a no-trade or degenerate (zero/none risk) structure — G11 then
    # blocks it, which is the right outcome for a malformed structure.
    if st == StructureType.NONE or not structure.max_loss or structure.max_loss <= 0:
        return None

    risk = structure.max_loss
    profit = structure.max_profit or risk
    be = structure.breakevens[0] if structure.breakevens else None
    # Earnings falls inside the hold and this isn't an earnings play → exit before it.
    pre_earn = (
        not thesis.is_earnings_play
        and thesis.days_to_earnings is not None
        and 0 <= thesis.days_to_earnings <= _hold_days(thesis)
    )

    if st == StructureType.ZERO_DTE_SPREAD:
        return ExitPlan(
            profit_target_pct=0.50, profit_target_value=round(0.50 * profit, 2),
            stop_loss_pct=0.50, stop_loss_value=round(0.50 * risk, 2),
            time_stop_days=0, short_delta_stop=0.45,
            invalidation="short strike breached or hard time-stop; no averaging, no re-entry",
            notes=["0DTE: hard stop + time stop; one attempt"],
        )

    if st in _SELL_FAMILY:
        # Take profit early; cut before max loss; manage the short leg by delta.
        stop_val = min(2.0 * profit, risk)  # ~2x credit, capped at defined max loss
        return ExitPlan(
            profit_target_pct=0.50, profit_target_value=round(0.50 * profit, 2),
            stop_loss_pct=round(stop_val / risk, 2), stop_loss_value=round(stop_val, 2),
            short_delta_stop=0.35, pre_earnings_exit=pre_earn,
            invalidation=(f"short strike delta > 0.35 or price through short strike"
                          + (f" (~{be:g})" if be else "")),
            notes=["credit: close by 50% of credit; don't hold to expiration"],
        )

    # Long / debit family.
    target_pct = 0.60 if st == StructureType.DEBIT_VERTICAL else 0.50
    return ExitPlan(
        profit_target_pct=target_pct, profit_target_value=round(target_pct * (structure.max_profit or risk), 2),
        stop_loss_pct=0.40, stop_loss_value=round(0.40 * risk, 2),
        time_stop_days=max(1, _hold_days(thesis) // 2),
        pre_earnings_exit=pre_earn,
        invalidation=(f"underlying through breakeven" + (f" (~{be:g})" if be else "")
                      + " or long delta collapses below 0.20"),
        notes=["long premium: take profit into strength; theta/time stop if it stalls"],
    )


def _hold_days(thesis: Thesis) -> int:
    from .models import Horizon
    return {Horizon.INTRADAY: 1, Horizon.SWING: 10, Horizon.POSITION: 40,
            Horizon.LEAPS: 120}.get(thesis.horizon, 10)

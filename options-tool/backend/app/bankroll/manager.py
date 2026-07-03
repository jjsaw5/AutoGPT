"""Shared bankroll model.

Rules (non-negotiable per the phase-5 spec):
- Each strategist has its own Kelly fraction and hard per-trade cap.
- Total deployed capital (sum of open capital_at_risk across all strategists)
  never exceeds ``Account.max_total_deployed_pct``.
- Every strategist also gets an allocation ceiling so no one module can
  monopolise the account. The defaults split cash roughly as: Sosnoff 30%,
  Saliba 25%, Thorp 20%, HighVolume 15%, ZeroDTE 10%.

The service is pure: hand it a journal and an account, get back a status
object the UI can render. Enforcement lives in the strategists' own ``size()``
methods — this service is about visibility.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.core.models import CONTRACT_MULTIPLIER, Account, JournalEntry, JournalOutcome


@dataclass(frozen=True)
class StrategistBudget:
    name: str
    allocation_pct: float  # max % of account.cash this strategist can deploy
    kelly_fraction: float  # multiplier on full Kelly the strategist should use
    max_pct_per_trade: float  # per-ticket cap, same semantics as Account


def default_budgets() -> list[StrategistBudget]:
    """Production defaults. Tuned by the phase-5 spec, not empirical data."""
    return [
        StrategistBudget("sosnoff", 0.30, 0.25, 0.05),
        StrategistBudget("saliba", 0.25, 0.25, 0.05),
        StrategistBudget("thorp", 0.20, 0.25, 0.05),
        StrategistBudget("high_volume", 0.15, 0.50, 0.05),
        StrategistBudget("zero_dte", 0.10, 0.10, 0.005),
    ]


@dataclass
class StrategistAllocation:
    budget: StrategistBudget
    deployed: float
    open_positions: int

    @property
    def allocation_cash(self) -> float:
        return self._allocation_cash

    def set_account_cash(self, cash: float) -> None:
        self._allocation_cash = cash * self.budget.allocation_pct

    @property
    def utilization(self) -> float:
        cap = self._allocation_cash
        return self.deployed / cap if cap > 0 else 0.0

    @property
    def over_limit(self) -> bool:
        return self.deployed > self._allocation_cash + 1e-6


@dataclass
class BankrollStatus:
    cash: float
    total_deployed: float
    total_cap: float
    total_utilization: float
    over_total_cap: bool
    allocations: list[StrategistAllocation] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "cash": self.cash,
            "total_deployed": self.total_deployed,
            "total_cap": self.total_cap,
            "total_utilization": self.total_utilization,
            "over_total_cap": self.over_total_cap,
            "allocations": [
                {
                    "name": a.budget.name,
                    "allocation_pct": a.budget.allocation_pct,
                    "allocation_cash": a.allocation_cash,
                    "kelly_fraction": a.budget.kelly_fraction,
                    "max_pct_per_trade": a.budget.max_pct_per_trade,
                    "deployed": a.deployed,
                    "open_positions": a.open_positions,
                    "utilization": a.utilization,
                    "over_limit": a.over_limit,
                }
                for a in self.allocations
            ],
        }


def compute_bankroll(
    *,
    account: Account,
    entries: Iterable[JournalEntry],
    budgets: list[StrategistBudget] | None = None,
) -> BankrollStatus:
    budgets = budgets or default_budgets()
    opens = [e for e in entries if e.outcome is JournalOutcome.OPEN]

    deployed_per_strategist: dict[str, float] = {}
    opens_per_strategist: dict[str, int] = {}
    for entry in opens:
        dollars = entry.max_loss * entry.contracts * CONTRACT_MULTIPLIER
        deployed_per_strategist[entry.strategist] = (
            deployed_per_strategist.get(entry.strategist, 0.0) + dollars
        )
        opens_per_strategist[entry.strategist] = (
            opens_per_strategist.get(entry.strategist, 0) + 1
        )

    total_deployed = sum(deployed_per_strategist.values())
    total_cap = account.cash * account.max_total_deployed_pct
    utilisation = total_deployed / total_cap if total_cap > 0 else 0.0

    allocations: list[StrategistAllocation] = []
    for b in budgets:
        a = StrategistAllocation(
            budget=b,
            deployed=deployed_per_strategist.get(b.name, 0.0),
            open_positions=opens_per_strategist.get(b.name, 0),
        )
        a.set_account_cash(account.cash)
        allocations.append(a)

    return BankrollStatus(
        cash=account.cash,
        total_deployed=total_deployed,
        total_cap=total_cap,
        total_utilization=utilisation,
        over_total_cap=total_deployed > total_cap + 1e-6,
        allocations=allocations,
    )

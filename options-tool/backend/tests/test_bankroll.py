"""Bankroll manager tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.bankroll.manager import (
    StrategistBudget,
    compute_bankroll,
    default_budgets,
)
from app.core.models import Account, JournalEntry, JournalOutcome


def _entry(
    *,
    strategist: str = "sosnoff",
    contracts: int = 5,
    max_loss: float = 10.0,
    outcome: JournalOutcome = JournalOutcome.OPEN,
) -> JournalEntry:
    return JournalEntry(
        ticker="SPY",
        strategy="short_put",
        strategist=strategist,
        thesis="test",
        opened_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
        contracts=contracts,
        entry_credit=1.0,
        max_loss=max_loss,
        outcome=outcome,
    )


def test_bankroll_empty_journal_zero_deployed() -> None:
    status = compute_bankroll(account=Account(cash=100_000), entries=[])
    assert status.total_deployed == 0.0
    assert status.over_total_cap is False
    assert len(status.allocations) == len(default_budgets())


def test_bankroll_per_strategist_caps_from_defaults() -> None:
    status = compute_bankroll(account=Account(cash=100_000), entries=[])
    by_name = {a.budget.name: a for a in status.allocations}
    # Defaults should sum to 1.0 and include every phase-1..3 strategist.
    assert sum(b.allocation_pct for b in default_budgets()) == pytest.approx(1.0)
    assert {"sosnoff", "saliba", "thorp", "high_volume", "zero_dte"} <= by_name.keys()
    # Sosnoff default is 30% -> $30k allocation on $100k cash.
    assert by_name["sosnoff"].allocation_cash == pytest.approx(30_000)


def test_bankroll_sums_deployed_per_strategist() -> None:
    entries = [
        _entry(strategist="sosnoff", contracts=2, max_loss=5.0),  # 2 * 5 * 100 = $1,000
        _entry(strategist="saliba", contracts=3, max_loss=8.0),  # 3 * 8 * 100 = $2,400
    ]
    status = compute_bankroll(account=Account(cash=100_000), entries=entries)
    deployed_by = {a.budget.name: a.deployed for a in status.allocations}
    assert deployed_by["sosnoff"] == pytest.approx(1_000)
    assert deployed_by["saliba"] == pytest.approx(2_400)
    assert status.total_deployed == pytest.approx(3_400)


def test_bankroll_flags_over_limit_per_strategist() -> None:
    # 100 contracts × $10 × 100 = $100k deployed under 'zero_dte' — far over its 10% default cap.
    entries = [_entry(strategist="zero_dte", contracts=100, max_loss=10.0)]
    status = compute_bankroll(
        account=Account(cash=100_000, max_total_deployed_pct=1.0), entries=entries
    )
    zero_dte = next(a for a in status.allocations if a.budget.name == "zero_dte")
    assert zero_dte.over_limit is True


def test_bankroll_flags_over_total_cap() -> None:
    entries = [_entry(strategist="sosnoff", contracts=100, max_loss=10.0)]  # $100k
    status = compute_bankroll(
        account=Account(cash=100_000, max_total_deployed_pct=0.5), entries=entries
    )
    # $100k deployed > 50% cap of $50k -> over cap.
    assert status.over_total_cap is True


def test_bankroll_custom_budgets_honoured() -> None:
    budgets = [
        StrategistBudget("custom_a", 0.6, 0.25, 0.05),
        StrategistBudget("custom_b", 0.4, 0.25, 0.05),
    ]
    status = compute_bankroll(
        account=Account(cash=50_000), entries=[], budgets=budgets
    )
    names = [a.budget.name for a in status.allocations]
    assert names == ["custom_a", "custom_b"]
    assert status.allocations[0].allocation_cash == pytest.approx(30_000)


def test_bankroll_ignores_closed_entries() -> None:
    entries = [
        _entry(outcome=JournalOutcome.WIN, contracts=10, max_loss=10.0),
        _entry(outcome=JournalOutcome.LOSS, contracts=10, max_loss=10.0),
    ]
    status = compute_bankroll(account=Account(cash=100_000), entries=entries)
    assert status.total_deployed == 0.0

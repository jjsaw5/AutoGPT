"""Risk dashboard tests — verify Greeks aggregation + concentration warnings."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.core.models import (
    Account,
    JournalEntry,
    JournalOutcome,
    OptionContract,
    OptionRight,
    TradeLeg,
    TradeSetup,
)
from app.risk.dashboard import DashboardConfig, compute_dashboard


def _contract(**overrides: object) -> OptionContract:
    defaults: dict[str, object] = dict(
        symbol="SPY260522P00400000",
        underlying="SPY",
        expiry=date(2026, 5, 22),
        strike=400.0,
        right=OptionRight.PUT,
        bid=2.0,
        ask=2.2,
        last=2.1,
        delta=-0.25,
        gamma=0.02,
        theta=-0.05,
        vega=0.3,
        implied_vol=0.25,
        as_of=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return OptionContract(**defaults)  # type: ignore[arg-type]


def _setup(**overrides: object) -> TradeSetup:
    contract = overrides.pop("contract", None) or _contract()
    assert isinstance(contract, OptionContract)
    quantity = int(overrides.pop("quantity", -1))  # type: ignore[arg-type]
    defaults: dict[str, object] = dict(
        ticker="SPY",
        strategy="short_put",
        thesis="test",
        legs=[TradeLeg(contract=contract, quantity=quantity)],
        net_credit=2.1,
        max_profit=2.1,
        max_loss=10.0,
        max_theoretical_loss=397.9,
        breakevens=[397.9],
        pop=0.75,
        dte=30,
    )
    defaults.update(overrides)
    return TradeSetup(**defaults)  # type: ignore[arg-type]


def _entry(
    *,
    ticker: str = "SPY",
    strategist: str = "sosnoff",
    contracts: int = 5,
    max_loss: float = 10.0,
    outcome: JournalOutcome = JournalOutcome.OPEN,
    setup: TradeSetup | None = None,
) -> JournalEntry:
    return JournalEntry(
        ticker=ticker,
        strategy="short_put",
        strategist=strategist,
        thesis="test",
        opened_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
        contracts=contracts,
        entry_credit=2.1,
        max_loss=max_loss,
        outcome=outcome,
        setup_snapshot=setup,
    )


def test_dashboard_empty_on_no_open_positions() -> None:
    d = compute_dashboard(
        entries=[], account=Account(cash=100_000), config=DashboardConfig()
    )
    assert d.open_positions == 0
    assert d.greeks.delta == 0.0
    assert d.by_ticker == []
    assert d.warnings == []


def test_dashboard_aggregates_greeks_from_snapshots() -> None:
    # Short put: quantity=-1, delta=-0.25 -> position delta = +0.25 per spread.
    # Aggregate over 5 contracts × 100 multiplier = +125.
    entry = _entry(setup=_setup(quantity=-1))
    d = compute_dashboard(entries=[entry], account=Account(cash=100_000))
    assert d.open_positions == 1
    assert d.greeks.delta == pytest.approx(125.0)
    # Short put gamma = -1 × +0.02 × 5 × 100 = -10
    assert d.greeks.gamma == pytest.approx(-10.0)
    # Short put theta = -1 × -0.05 × 5 × 100 = +25 (collecting time)
    assert d.greeks.theta == pytest.approx(25.0)
    # Short put vega = -1 × +0.3 × 5 × 100 = -150 (short vol)
    assert d.greeks.vega == pytest.approx(-150.0)


def test_dashboard_skips_entries_without_snapshot_but_still_bookkeeps() -> None:
    """Pre-Phase-5 entries have no snapshot — exposure still counts, Greeks don't."""
    entry = _entry(setup=None)
    d = compute_dashboard(entries=[entry], account=Account(cash=100_000))
    assert d.open_positions == 1
    assert d.total_contracts == 5
    # No snapshot -> Greeks aggregation sees no position.
    assert d.greeks.delta == 0.0
    # Exposure bookkeeping still fires.
    assert d.total_capital_at_risk == pytest.approx(10.0 * 5 * 100)


def test_dashboard_warns_on_ticker_concentration() -> None:
    # Two opens on SPY totalling 30k vs 100k cash -> 30% > 25% cap.
    entries = [
        _entry(ticker="SPY", contracts=10, max_loss=20.0, setup=_setup()),
        _entry(ticker="SPY", contracts=5, max_loss=20.0, setup=_setup()),
    ]
    d = compute_dashboard(entries=entries, account=Account(cash=100_000))
    codes = [w.code for w in d.warnings]
    assert "ticker_concentration" in codes


def test_dashboard_warns_on_strategist_concentration() -> None:
    entries = [
        _entry(strategist="high_volume", contracts=25, max_loss=20.0, setup=_setup()),
    ]
    d = compute_dashboard(entries=entries, account=Account(cash=100_000))
    codes = [w.code for w in d.warnings]
    assert "strategist_concentration" in codes


def test_dashboard_critical_warning_on_aggregate_mtl() -> None:
    # One short put with MTL ≈ 397.9 × 5 × 100 = $198,950 → 199% of $100k.
    entries = [_entry(setup=_setup())]
    d = compute_dashboard(entries=entries, account=Account(cash=100_000))
    crit = [w for w in d.warnings if w.severity == "critical"]
    assert crit, "Expected a critical max-theoretical-loss warning."


def test_dashboard_ignores_closed_entries() -> None:
    entries = [
        _entry(outcome=JournalOutcome.WIN, setup=_setup()),
        _entry(outcome=JournalOutcome.LOSS, setup=_setup()),
    ]
    d = compute_dashboard(entries=entries, account=Account(cash=100_000))
    assert d.open_positions == 0

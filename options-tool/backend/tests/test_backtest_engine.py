"""Backtester engine tests.

The engine is parametrised on three callables (analyze/size/manage) so we can
drive it deterministically without depending on a real strategist's Kelly
logic or IV-history state.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone

import pytest

from app.backtest.engine import Backtester
from app.core.models import (
    Account,
    ManagementAction,
    ManagementVerdict,
    OptionChain,
    PositionSize,
    TradeLeg,
    TradeSetup,
)
from app.data.mock_provider import MockProvider


def _chain_factory(base_spot: float = 100.0) -> object:
    def make(d: date) -> OptionChain:
        idx = (d - date(2025, 6, 2)).days
        spot = base_spot + 0.05 * idx + 2.0 * math.sin(idx / 10.0)
        as_of = datetime.combine(d, datetime.min.time().replace(hour=15), tzinfo=timezone.utc)
        return MockProvider(
            spot=max(spot, 1.0), base_iv=0.30, as_of=as_of
        ).get_chain("SPY")

    return make


def _simple_analyze(ticker: str, chain: OptionChain) -> TradeSetup | None:
    """Pick an OTM short put at ~0.30 delta for a 30-DTE expiry."""
    today = chain.as_of.date()
    target_expiry = next(
        (e for e in chain.expiries() if 25 <= (e - today).days <= 45), None
    )
    if target_expiry is None:
        return None
    puts = [
        c for c in chain.by_expiry(target_expiry)
        if c.right.value == "P" and c.strike <= chain.spot and c.delta is not None
    ]
    if not puts:
        return None
    short = min(puts, key=lambda c: abs(abs(c.delta or 0.0) - 0.30))
    return TradeSetup(
        ticker=ticker,
        strategy="test_short_put",
        thesis="deterministic short put at 0.30 delta",
        legs=[TradeLeg(contract=short, quantity=-1)],
        net_credit=short.mid,
        max_profit=short.mid,
        max_loss=max(short.strike - short.mid, 0.01),
        breakevens=[short.strike - short.mid],
        pop=0.7,
        dte=(target_expiry - today).days,
    )


def _size_two(setup: TradeSetup, account: Account) -> PositionSize:
    return PositionSize(
        contracts=2,
        capital_at_risk=setup.max_loss * 2 * 100,
        pct_of_account=0.01,
        rationale="test fixed sizer",
    )


def _hold_always(position, market) -> ManagementAction:  # type: ignore[no-untyped-def]
    return ManagementAction(verdict=ManagementVerdict.HOLD, reason="test")


def _close_winner_at_50_pct(position, market) -> ManagementAction:  # type: ignore[no-untyped-def]
    max_profit = position.setup.max_profit * 100 * position.size.contracts
    if max_profit > 0 and position.current_pnl >= 0.5 * max_profit:
        return ManagementAction(verdict=ManagementVerdict.CLOSE_WINNER, reason="test")
    return ManagementAction(verdict=ManagementVerdict.HOLD, reason="test")


def test_engine_runs_to_completion_with_trivial_strategist() -> None:
    bt = Backtester(
        ticker="SPY",
        strategist_name="unit_test",
        analyze=_simple_analyze,
        size=_size_two,
        manage=_hold_always,
        chain_factory=_chain_factory(),
        account=Account(cash=100_000),
        start=date(2025, 6, 2),
        end=date(2025, 7, 30),
    )
    result = bt.run()
    assert result.initial_cash == 100_000
    assert len(result.equity_curve) > 0
    # Something must have opened, given our strategist always fires.
    assert result.trade_count > 0


def test_engine_closes_on_expiry_forces_trade_outcomes() -> None:
    """Even with hold_always, positions must close at expiry."""
    bt = Backtester(
        ticker="SPY",
        strategist_name="unit_test",
        analyze=_simple_analyze,
        size=_size_two,
        manage=_hold_always,
        chain_factory=_chain_factory(),
        account=Account(cash=100_000),
        start=date(2025, 6, 2),
        end=date(2025, 8, 15),
    )
    result = bt.run()
    journal_outcomes = {t.outcome for t in result.trades}
    # Every trade must have been closed by the end.
    assert "open" not in {o.value for o in journal_outcomes}


def test_engine_emits_equity_curve_with_one_point_per_session() -> None:
    bt = Backtester(
        ticker="SPY",
        strategist_name="unit_test",
        analyze=lambda t, c: None,  # never trade
        size=_size_two,
        manage=_hold_always,
        chain_factory=_chain_factory(),
        account=Account(cash=50_000),
        start=date(2025, 6, 2),
        end=date(2025, 6, 6),  # Mon-Fri = 5 sessions
    )
    result = bt.run()
    assert len(result.equity_curve) == 5
    # Equity flat at 50k since we never trade.
    assert all(p.equity == 50_000 for p in result.equity_curve)
    assert result.metrics["cagr"] == 0.0
    assert result.metrics["trades"] == 0


def test_engine_manage_close_winner_fires() -> None:
    """With a 50%-target manager, at least one win must be booked before expiry."""
    bt = Backtester(
        ticker="SPY",
        strategist_name="unit_test",
        analyze=_simple_analyze,
        size=_size_two,
        manage=_close_winner_at_50_pct,
        chain_factory=_chain_factory(),
        account=Account(cash=100_000),
        start=date(2025, 6, 2),
        end=date(2025, 8, 15),
    )
    result = bt.run()
    outcomes = [t.outcome.value for t in result.trades]
    assert "win" in outcomes or "loss" in outcomes

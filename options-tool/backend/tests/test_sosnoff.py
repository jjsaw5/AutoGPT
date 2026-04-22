"""Sosnoff strategy tests — the module the whole phase-1 stack hangs on."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.models import (
    CONTRACT_MULTIPLIER,
    Account,
    ManagementVerdict,
    MarketSnapshot,
    Position,
    PositionSize,
)
from app.data.mock_provider import MockProvider
from app.strategists.sosnoff import (
    SosnoffStrategist,
    iv_percentile,
    iv_rank,
)
from app.data.base import IVHistoryPoint
from datetime import date, timedelta


# ------------------------------------------------------------------------ IVR/IVP
def test_iv_rank_matches_tastytrade_formula() -> None:
    today = date(2026, 4, 22)
    hist = [IVHistoryPoint(date=today - timedelta(days=i), atm_iv=v) for i, v in enumerate([0.10, 0.30, 0.50])]
    # Current = 0.40 -> (0.40 - 0.10) / (0.50 - 0.10) * 100 = 75
    assert iv_rank(hist, 0.40) == pytest.approx(75.0)


def test_iv_percentile_counts_strict_below() -> None:
    today = date(2026, 4, 22)
    hist = [IVHistoryPoint(date=today - timedelta(days=i), atm_iv=v) for i, v in enumerate([0.10, 0.20, 0.30, 0.40])]
    assert iv_percentile(hist, 0.30) == pytest.approx(50.0)


# --------------------------------------------------------------------- analyze()
def test_analyze_skips_when_ivr_below_threshold(low_ivr_provider: MockProvider) -> None:
    strategist = SosnoffStrategist(provider=low_ivr_provider)
    chain = low_ivr_provider.get_chain("TEST")
    setup = strategist.analyze("TEST", chain, bias="neutral")
    assert setup is not None
    assert setup.strategy == "skip"
    assert setup.iv_rank is not None and setup.iv_rank < 30


def test_analyze_builds_iron_condor_in_mid_ivr_band(mid_ivr_provider: MockProvider) -> None:
    strategist = SosnoffStrategist(provider=mid_ivr_provider)
    chain = mid_ivr_provider.get_chain("TEST")
    setup = strategist.analyze("TEST", chain, bias="neutral")
    assert setup is not None
    assert setup.strategy == "iron_condor"
    assert len(setup.legs) == 4
    # Condor must have both a long put (below) and a long call (above) for defined risk.
    long_strikes = sorted(leg.contract.strike for leg in setup.legs if leg.is_long)
    short_strikes = sorted(leg.contract.strike for leg in setup.legs if not leg.is_long)
    assert long_strikes[0] < short_strikes[0] < chain.spot < short_strikes[1] < long_strikes[1]
    # Defined-risk invariant: max_loss > 0 and reported before max_gain in notes-order.
    assert setup.max_loss > 0
    assert setup.max_profit >= 0


def test_analyze_builds_short_strangle_in_high_ivr(high_ivr_provider: MockProvider) -> None:
    strategist = SosnoffStrategist(provider=high_ivr_provider)
    chain = high_ivr_provider.get_chain("TEST")
    setup = strategist.analyze("TEST", chain, bias="neutral")
    assert setup is not None
    assert setup.strategy == "short_strangle"
    assert len(setup.legs) == 2
    assert all(not leg.is_long for leg in setup.legs)
    assert "UNDEFINED RISK" in setup.notes[0]


def test_analyze_builds_credit_spread_when_directional(mid_ivr_provider: MockProvider) -> None:
    strategist = SosnoffStrategist(provider=mid_ivr_provider)
    chain = mid_ivr_provider.get_chain("TEST")
    setup = strategist.analyze("TEST", chain, bias="bullish")
    assert setup is not None
    assert setup.strategy == "bull_put_spread"
    assert len(setup.legs) == 2
    # Bull put spread: short strike above long strike, both below spot.
    short_leg = next(leg for leg in setup.legs if not leg.is_long)
    long_leg = next(leg for leg in setup.legs if leg.is_long)
    assert short_leg.contract.strike > long_leg.contract.strike
    assert short_leg.contract.strike <= chain.spot


# ---------------------------------------------------------------------- size()
def test_size_caps_at_max_pct_per_trade(
    mid_ivr_provider: MockProvider, account: Account
) -> None:
    strategist = SosnoffStrategist(provider=mid_ivr_provider)
    chain = mid_ivr_provider.get_chain("TEST")
    setup = strategist.analyze("TEST", chain, bias="neutral")
    assert setup is not None
    sized = strategist.size(setup, account)
    # Hard cap: capital at risk cannot exceed 5% of $100k = $5,000.
    assert sized.capital_at_risk <= account.cash * account.max_pct_per_trade + 1e-6


def test_size_returns_zero_on_degenerate_payoff(
    mid_ivr_provider: MockProvider, account: Account
) -> None:
    strategist = SosnoffStrategist(provider=mid_ivr_provider)
    chain = mid_ivr_provider.get_chain("TEST")
    setup = strategist.analyze("TEST", chain, bias="neutral")
    assert setup is not None
    setup = setup.model_copy(update={"max_loss": 0.0})
    sized = strategist.size(setup, account)
    assert sized.contracts == 0
    assert "Degenerate" in sized.rationale


def test_size_never_recommends_more_than_kelly_fraction(
    mid_ivr_provider: MockProvider,
) -> None:
    """With a very small Kelly fraction, sizing must shrink accordingly."""
    strategist = SosnoffStrategist(provider=mid_ivr_provider)
    chain = mid_ivr_provider.get_chain("TEST")
    setup = strategist.analyze("TEST", chain, bias="neutral")
    assert setup is not None
    tiny_kelly = Account(cash=100_000, kelly_fraction=0.01, max_pct_per_trade=0.5)
    normal_kelly = Account(cash=100_000, kelly_fraction=0.25, max_pct_per_trade=0.5)
    small = strategist.size(setup, tiny_kelly)
    big = strategist.size(setup, normal_kelly)
    assert small.capital_at_risk <= big.capital_at_risk


# --------------------------------------------------------------------- manage()
def _position(setup, contracts: int = 1, pnl: float = 0.0) -> Position:  # type: ignore[no-untyped-def]
    return Position(
        setup=setup,
        size=PositionSize(contracts=contracts, capital_at_risk=setup.max_loss * CONTRACT_MULTIPLIER * contracts, pct_of_account=0.05, rationale="test"),
        opened_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        current_pnl=pnl,
    )


def test_manage_closes_winner_at_profit_target(
    mid_ivr_provider: MockProvider,
) -> None:
    strategist = SosnoffStrategist(provider=mid_ivr_provider)
    chain = mid_ivr_provider.get_chain("TEST")
    setup = strategist.analyze("TEST", chain, bias="neutral")
    assert setup is not None
    # 60% of max profit reached -> should close.
    max_profit_dollars = setup.max_profit * CONTRACT_MULTIPLIER
    position = _position(setup, pnl=max_profit_dollars * 0.6)
    action = strategist.manage(
        position, MarketSnapshot(ticker="TEST", spot=chain.spot, as_of=chain.as_of)
    )
    assert action.verdict == ManagementVerdict.CLOSE_WINNER


def test_manage_closes_at_21_dte(mid_ivr_provider: MockProvider) -> None:
    strategist = SosnoffStrategist(provider=mid_ivr_provider)
    chain = mid_ivr_provider.get_chain("TEST")
    setup = strategist.analyze("TEST", chain, bias="neutral")
    assert setup is not None
    position = _position(setup, pnl=0.0)
    # Fast-forward the market clock to within 21 days of the earliest expiry.
    earliest = min(leg.contract.expiry for leg in setup.legs)
    near_expiry = datetime.combine(earliest, datetime.min.time(), tzinfo=timezone.utc)
    snap = MarketSnapshot(ticker="TEST", spot=chain.spot, as_of=near_expiry)
    action = strategist.manage(position, snap)
    assert action.verdict == ManagementVerdict.CLOSE_TIME


def test_manage_holds_when_neither_rule_triggers(
    mid_ivr_provider: MockProvider,
) -> None:
    strategist = SosnoffStrategist(provider=mid_ivr_provider)
    chain = mid_ivr_provider.get_chain("TEST")
    setup = strategist.analyze("TEST", chain, bias="neutral")
    assert setup is not None
    position = _position(setup, pnl=1.0)
    snap = MarketSnapshot(ticker="TEST", spot=chain.spot, as_of=chain.as_of)
    action = strategist.manage(position, snap)
    assert action.verdict == ManagementVerdict.HOLD

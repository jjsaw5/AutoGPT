"""Performance-metric sanity checks."""
from __future__ import annotations

import math

import pytest

from app.backtest.metrics import (
    cagr,
    compute_metrics,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    win_rate,
)


def test_cagr_on_doubling_over_one_year() -> None:
    # Equity doubles over 365 days -> CAGR = 100%.
    assert cagr([100.0, 200.0], days=365) == pytest.approx(1.0, abs=1e-6)


def test_cagr_zero_equity_is_safe() -> None:
    assert cagr([], days=100) == 0.0
    assert cagr([0.0, 100.0], days=100) == 0.0
    assert cagr([100.0, 100.0], days=0) == 0.0


def test_max_drawdown_detects_worst_peak_to_trough() -> None:
    # Peak at 120, trough at 80 -> 33.3% drawdown.
    assert max_drawdown([100.0, 120.0, 80.0, 110.0]) == pytest.approx((120 - 80) / 120)


def test_max_drawdown_is_zero_on_monotone_curve() -> None:
    assert max_drawdown([100.0, 101.0, 102.0, 103.0]) == 0.0


def test_sharpe_requires_two_returns() -> None:
    assert sharpe_ratio([100.0]) == 0.0


def test_sharpe_positive_on_steady_growth() -> None:
    equity = [100.0 * (1.001**i) for i in range(252)]  # daily 10 bps, ~28% annual
    sr = sharpe_ratio(equity)
    # Steady growth with ~0 variance -> Sharpe is 0 by our guard, which is the
    # "degenerate variance" protection. Inject small noise to exercise the math.
    import random

    random.seed(42)
    noisy = [e * random.uniform(0.999, 1.001) for e in equity]
    assert sharpe_ratio(noisy) > 0


def test_sortino_finite_and_positive_with_downside() -> None:
    # Alternating up/down days, net drift up -> Sortino > 0, finite.
    equity = [100.0]
    for i in range(60):
        equity.append(equity[-1] * (1.005 if i % 3 != 0 else 0.995))
    s = sortino_ratio(equity)
    assert math.isfinite(s)
    assert s > 0


def test_win_rate_and_profit_factor() -> None:
    pnls = [100.0, -50.0, 200.0, -75.0]
    assert win_rate(pnls) == 0.5
    assert profit_factor(pnls) == pytest.approx(300 / 125)


def test_profit_factor_infinite_when_no_losers() -> None:
    assert profit_factor([100.0, 200.0]) == float("inf")


def test_profit_factor_zero_when_no_trades() -> None:
    assert profit_factor([]) == 0.0


def test_compute_metrics_aggregates_all_fields() -> None:
    equity = [100.0, 110.0, 105.0, 120.0]
    pnls = [10.0, -5.0, 15.0]
    m = compute_metrics(equity, pnls, days=30)
    d = m.to_dict()
    # All required fields present.
    for key in {"cagr", "max_drawdown", "sharpe", "sortino", "win_rate", "profit_factor", "trades"}:
        assert key in d
    assert d["trades"] == 3

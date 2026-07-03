"""Performance metrics for the backtest harness.

Kept as pure functions so they are trivially unit-testable and reusable in
ad-hoc notebooks. All inputs are plain floats / lists of floats — no pandas
dependency — which also keeps ``mypy --strict`` happy.

Conventions:
- ``equity`` is a time-ordered list of account values (including the starting
  cash as the first point).
- ``daily_returns`` are simple returns R_t = (E_t − E_{t−1}) / E_{t−1}.
- Annualisation factor defaults to 252 trading days.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

TRADING_DAYS_PER_YEAR = 252


def _to_returns(equity: list[float]) -> list[float]:
    returns: list[float] = []
    for prev, cur in zip(equity, equity[1:]):
        if prev <= 0:
            returns.append(0.0)
        else:
            returns.append((cur - prev) / prev)
    return returns


def cagr(equity: list[float], days: int) -> float:
    """Compound annual growth rate implied by an equity curve and a duration."""
    if not equity or equity[0] <= 0 or days <= 0:
        return 0.0
    years = days / 365.0
    if years <= 0:
        return 0.0
    return float((equity[-1] / equity[0]) ** (1.0 / years) - 1.0)


def max_drawdown(equity: list[float]) -> float:
    """Worst peak-to-trough decline, expressed as a positive fraction."""
    if not equity:
        return 0.0
    peak = equity[0]
    worst = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > worst:
                worst = dd
    return worst


def sharpe_ratio(
    equity: list[float], risk_free: float = 0.0, periods_per_year: int = TRADING_DAYS_PER_YEAR
) -> float:
    """Annualised Sharpe ratio. Returns 0 when variance is degenerate."""
    rets = _to_returns(equity)
    if len(rets) < 2:
        return 0.0
    daily_rf = risk_free / periods_per_year
    excess = [r - daily_rf for r in rets]
    mean = sum(excess) / len(excess)
    var = sum((r - mean) ** 2 for r in excess) / (len(excess) - 1)
    if var <= 0:
        return 0.0
    return mean / math.sqrt(var) * math.sqrt(periods_per_year)


def sortino_ratio(
    equity: list[float], risk_free: float = 0.0, periods_per_year: int = TRADING_DAYS_PER_YEAR
) -> float:
    """Annualised Sortino — penalises only downside deviation."""
    rets = _to_returns(equity)
    if len(rets) < 2:
        return 0.0
    daily_rf = risk_free / periods_per_year
    excess = [r - daily_rf for r in rets]
    mean = sum(excess) / len(excess)
    downside = [min(r, 0.0) for r in excess]
    downside_var = sum(d * d for d in downside) / len(downside)
    if downside_var <= 0:
        return 0.0
    return mean / math.sqrt(downside_var) * math.sqrt(periods_per_year)


def win_rate(trade_pnls: Iterable[float]) -> float:
    """Fraction of closed trades with strictly positive P/L."""
    items = list(trade_pnls)
    if not items:
        return 0.0
    return sum(1 for p in items if p > 0) / len(items)


def profit_factor(trade_pnls: Iterable[float]) -> float:
    """Gross wins divided by gross losses; ``inf`` if no losers."""
    won = sum(p for p in trade_pnls if p > 0)
    lost = sum(-p for p in trade_pnls if p < 0)
    if lost <= 0:
        return float("inf") if won > 0 else 0.0
    return won / lost


@dataclass
class PerformanceMetrics:
    cagr: float
    max_drawdown: float
    sharpe: float
    sortino: float
    win_rate: float
    profit_factor: float
    trades: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "cagr": self.cagr,
            "max_drawdown": self.max_drawdown,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "trades": self.trades,
        }


def compute_metrics(
    equity: list[float], trade_pnls: list[float], days: int
) -> PerformanceMetrics:
    return PerformanceMetrics(
        cagr=cagr(equity, days),
        max_drawdown=max_drawdown(equity),
        sharpe=sharpe_ratio(equity),
        sortino=sortino_ratio(equity),
        win_rate=win_rate(trade_pnls),
        profit_factor=profit_factor(trade_pnls),
        trades=len(trade_pnls),
    )

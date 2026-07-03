"""Trade-journal analytics.

Computed metrics match the "Elite Options Trader" inspiration but are framed
defensively: every output that can mislead carries context. The Kelly-implied
vs. actual-size comparison is the anchor — if a module is repeatedly trading
bigger than its own edge warrants, that shows up here directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Iterable

from app.core.models import JournalEntry, JournalOutcome


@dataclass
class JournalAnalytics:
    trades: int = 0
    closed_trades: int = 0
    open_trades: int = 0
    wins: int = 0
    losses: int = 0
    scratches: int = 0
    win_rate: float = 0.0
    average_winner: float = 0.0
    average_loser: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    r_multiples: list[float] = field(default_factory=list)
    average_r: float = 0.0
    median_r: float = 0.0
    kelly_implied_vs_actual: list[dict[str, float | int | str]] = field(default_factory=list)
    by_strategist: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "trades": self.trades,
            "closed_trades": self.closed_trades,
            "open_trades": self.open_trades,
            "wins": self.wins,
            "losses": self.losses,
            "scratches": self.scratches,
            "win_rate": self.win_rate,
            "average_winner": self.average_winner,
            "average_loser": self.average_loser,
            "profit_factor": self.profit_factor,
            "expectancy": self.expectancy,
            "r_multiples": self.r_multiples,
            "average_r": self.average_r,
            "median_r": self.median_r,
            "kelly_implied_vs_actual": self.kelly_implied_vs_actual,
            "by_strategist": self.by_strategist,
        }


def compute_analytics(entries: Iterable[JournalEntry]) -> JournalAnalytics:
    items = list(entries)
    out = JournalAnalytics()
    out.trades = len(items)
    closed = [e for e in items if e.outcome is not JournalOutcome.OPEN]
    out.open_trades = out.trades - len(closed)
    out.closed_trades = len(closed)

    if not closed:
        return out

    winners = [e for e in closed if e.outcome is JournalOutcome.WIN]
    losers = [e for e in closed if e.outcome is JournalOutcome.LOSS]
    scratches = [e for e in closed if e.outcome is JournalOutcome.SCRATCH]
    out.wins, out.losses, out.scratches = len(winners), len(losers), len(scratches)
    out.win_rate = len(winners) / len(closed) if closed else 0.0
    out.average_winner = mean(e.realized_pnl for e in winners) if winners else 0.0
    out.average_loser = mean(e.realized_pnl for e in losers) if losers else 0.0

    total_won = sum(e.realized_pnl for e in winners)
    total_lost = sum(-e.realized_pnl for e in losers)
    out.profit_factor = (total_won / total_lost) if total_lost > 0 else float("inf")
    out.expectancy = mean(e.realized_pnl for e in closed) if closed else 0.0

    r_multiples = [r for e in closed if (r := e.r_multiple) is not None]
    out.r_multiples = sorted(r_multiples)
    out.average_r = mean(out.r_multiples) if out.r_multiples else 0.0
    out.median_r = out.r_multiples[len(out.r_multiples) // 2] if out.r_multiples else 0.0

    # Kelly-implied vs actual — surfaces systematic oversizing.
    for e in closed:
        if e.planned_size_contracts is None:
            continue
        out.kelly_implied_vs_actual.append(
            {
                "id": e.id or 0,
                "ticker": e.ticker,
                "strategist": e.strategist,
                "planned": e.planned_size_contracts,
                "actual": e.contracts,
                "drift_pct": (
                    (e.contracts - e.planned_size_contracts) / e.planned_size_contracts
                    if e.planned_size_contracts > 0
                    else 0.0
                ),
            }
        )

    # Per-strategist slice
    strategists = sorted({e.strategist for e in closed})
    for s in strategists:
        subset = [e for e in closed if e.strategist == s]
        sub_wins = [e for e in subset if e.outcome is JournalOutcome.WIN]
        sub_losses = [e for e in subset if e.outcome is JournalOutcome.LOSS]
        wr = len(sub_wins) / len(subset) if subset else 0.0
        exp = mean(e.realized_pnl for e in subset) if subset else 0.0
        avg_w = mean(e.realized_pnl for e in sub_wins) if sub_wins else 0.0
        avg_l = mean(e.realized_pnl for e in sub_losses) if sub_losses else 0.0
        out.by_strategist[s] = {
            "trades": float(len(subset)),
            "win_rate": wr,
            "expectancy": exp,
            "average_winner": avg_w,
            "average_loser": avg_l,
        }

    return out

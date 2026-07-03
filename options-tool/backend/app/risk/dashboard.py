"""Risk dashboard service.

Aggregates open positions (sourced from ``TradeJournal`` entries in state
``OPEN`` with a populated ``setup_snapshot``) into:

- **Portfolio Greeks** — delta, gamma, theta, vega, notional (leverages
  ``app.portfolio.aggregate``).
- **Exposure breakdown** — capital-at-risk and max-theoretical-loss grouped by
  both ticker and strategist.
- **Concentration warnings** — surfaced when a single ticker, strategist, or
  aggregate max theoretical loss exceeds a configurable share of account cash.

Warnings are intentionally conservative — the same "risk before reward"
principle that drives the trade card also drives the dashboard.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.core.models import (
    CONTRACT_MULTIPLIER,
    Account,
    JournalEntry,
    JournalOutcome,
    Position,
    PositionSize,
)
from app.portfolio import PortfolioGreeks, aggregate


@dataclass(frozen=True)
class DashboardConfig:
    concentration_ticker_pct: float = 0.25  # warn above 25% of cash in one ticker
    concentration_strategist_pct: float = 0.40  # warn above 40% in one strategist
    max_theoretical_loss_pct: float = 0.50  # warn if total mtl exceeds 50% of cash


@dataclass
class ExposureRow:
    key: str
    contracts: int
    capital_at_risk: float
    max_theoretical_loss: float
    positions: int


@dataclass
class DashboardWarning:
    severity: str  # "warn" | "critical"
    code: str
    message: str


@dataclass
class RiskDashboard:
    open_positions: int
    total_contracts: int
    total_capital_at_risk: float
    total_max_theoretical_loss: float
    greeks: PortfolioGreeks
    by_ticker: list[ExposureRow] = field(default_factory=list)
    by_strategist: list[ExposureRow] = field(default_factory=list)
    warnings: list[DashboardWarning] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "open_positions": self.open_positions,
            "total_contracts": self.total_contracts,
            "total_capital_at_risk": self.total_capital_at_risk,
            "total_max_theoretical_loss": self.total_max_theoretical_loss,
            "greeks": self.greeks.as_dict(),
            "by_ticker": [_row_to_dict(r) for r in self.by_ticker],
            "by_strategist": [_row_to_dict(r) for r in self.by_strategist],
            "warnings": [
                {"severity": w.severity, "code": w.code, "message": w.message}
                for w in self.warnings
            ],
        }


def _row_to_dict(row: ExposureRow) -> dict[str, object]:
    return {
        "key": row.key,
        "contracts": row.contracts,
        "capital_at_risk": row.capital_at_risk,
        "max_theoretical_loss": row.max_theoretical_loss,
        "positions": row.positions,
    }


def _entry_to_position(entry: JournalEntry) -> Position | None:
    """Build a ``Position`` for the Greeks aggregator. Returns None if the entry
    doesn't carry a snapshot (journal rows recorded before Phase 5)."""
    if entry.setup_snapshot is None:
        return None
    per_spread_risk = entry.max_loss * CONTRACT_MULTIPLIER
    size = PositionSize(
        contracts=entry.contracts,
        capital_at_risk=per_spread_risk * entry.contracts,
        pct_of_account=0.0,
        rationale="reconstructed-from-journal",
    )
    return Position(
        setup=entry.setup_snapshot, size=size, opened_at=entry.opened_at, current_pnl=0.0
    )


def compute_dashboard(
    *,
    entries: Iterable[JournalEntry],
    account: Account,
    config: DashboardConfig | None = None,
) -> RiskDashboard:
    cfg = config or DashboardConfig()
    opens = [e for e in entries if e.outcome is JournalOutcome.OPEN]
    positions: list[Position] = []
    tickers: dict[str, ExposureRow] = {}
    strategists: dict[str, ExposureRow] = {}
    total_contracts = 0
    total_risk = 0.0
    total_mtl = 0.0

    for entry in opens:
        position = _entry_to_position(entry)
        if position is not None:
            positions.append(position)
        contracts = entry.contracts
        per_spread_risk = entry.max_loss * CONTRACT_MULTIPLIER
        risk_dollars = per_spread_risk * contracts
        mtl_per_spread = (
            entry.setup_snapshot.max_theoretical_loss
            if entry.setup_snapshot is not None and entry.setup_snapshot.max_theoretical_loss is not None
            else entry.max_loss
        )
        mtl_dollars = mtl_per_spread * CONTRACT_MULTIPLIER * contracts

        total_contracts += contracts
        total_risk += risk_dollars
        total_mtl += mtl_dollars

        _bump(tickers, entry.ticker.upper(), contracts, risk_dollars, mtl_dollars)
        _bump(strategists, entry.strategist, contracts, risk_dollars, mtl_dollars)

    greeks = aggregate(positions)

    warnings: list[DashboardWarning] = []
    cash = max(account.cash, 1.0)
    for row in tickers.values():
        if row.capital_at_risk / cash > cfg.concentration_ticker_pct:
            warnings.append(
                DashboardWarning(
                    severity="warn",
                    code="ticker_concentration",
                    message=(
                        f"{row.key}: {row.capital_at_risk / cash:.0%} of cash deployed "
                        f"(> {cfg.concentration_ticker_pct:.0%} threshold)."
                    ),
                )
            )
    for row in strategists.values():
        if row.capital_at_risk / cash > cfg.concentration_strategist_pct:
            warnings.append(
                DashboardWarning(
                    severity="warn",
                    code="strategist_concentration",
                    message=(
                        f"{row.key}: {row.capital_at_risk / cash:.0%} of cash deployed "
                        f"(> {cfg.concentration_strategist_pct:.0%} threshold)."
                    ),
                )
            )
    if total_mtl / cash > cfg.max_theoretical_loss_pct:
        warnings.append(
            DashboardWarning(
                severity="critical",
                code="max_theoretical_loss",
                message=(
                    f"Aggregate max theoretical loss ${total_mtl:,.0f} is "
                    f"{total_mtl / cash:.0%} of cash (> {cfg.max_theoretical_loss_pct:.0%})."
                ),
            )
        )

    return RiskDashboard(
        open_positions=len(opens),
        total_contracts=total_contracts,
        total_capital_at_risk=total_risk,
        total_max_theoretical_loss=total_mtl,
        greeks=greeks,
        by_ticker=sorted(tickers.values(), key=lambda r: r.capital_at_risk, reverse=True),
        by_strategist=sorted(strategists.values(), key=lambda r: r.capital_at_risk, reverse=True),
        warnings=warnings,
    )


def _bump(
    bucket: dict[str, ExposureRow],
    key: str,
    contracts: int,
    risk_dollars: float,
    mtl_dollars: float,
) -> None:
    row = bucket.get(key)
    if row is None:
        bucket[key] = ExposureRow(
            key=key,
            contracts=contracts,
            capital_at_risk=risk_dollars,
            max_theoretical_loss=mtl_dollars,
            positions=1,
        )
        return
    bucket[key] = ExposureRow(
        key=key,
        contracts=row.contracts + contracts,
        capital_at_risk=row.capital_at_risk + risk_dollars,
        max_theoretical_loss=row.max_theoretical_loss + mtl_dollars,
        positions=row.positions + 1,
    )

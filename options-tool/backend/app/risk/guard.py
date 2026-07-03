"""Risk-limit enforcement.

The high-volume module (Phase 3) *permits* scale-in on losing positions — a
practice many educational channels advocate — but only inside hard caps:

- Per-ticker contract cap (how many open contracts on one underlying)
- Daily realized-loss cap (P/L booked today)
- Weekly realized-loss cap (P/L booked in the trailing 7 calendar days)

The 0DTE module adds a **session circuit breaker** on top: halt new entries
after N consecutive losses OR once the session drawdown exceeds X% of cash.
Both rules are expressed here so every strategist enforces them the same way.

The guard is intentionally *pure*: it reads a list of ``JournalEntry`` records
and returns a verdict. Persistence belongs to ``app.journal``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Iterable

from app.core.models import Account, JournalEntry, JournalOutcome


class RiskVerdict(str, Enum):
    ALLOW = "allow"
    BLOCK_TICKER_CAP = "block_ticker_cap"
    BLOCK_DAILY_LOSS = "block_daily_loss"
    BLOCK_WEEKLY_LOSS = "block_weekly_loss"
    BLOCK_SESSION_DRAWDOWN = "block_session_drawdown"
    BLOCK_CONSECUTIVE_LOSSES = "block_consecutive_losses"


@dataclass(frozen=True)
class RiskCaps:
    """Hard caps checked on every entry attempt.

    Defaults are conservative — callers opt into higher ceilings explicitly.
    The daily/weekly caps are **dollar losses**; the session caps apply only
    when ``as_of`` falls inside the session being tracked.
    """

    max_contracts_per_ticker: int = 20
    max_daily_loss: float = 1_500.0
    max_weekly_loss: float = 4_000.0
    session_max_consecutive_losses: int | None = 3
    session_max_drawdown_pct: float | None = 0.02  # 2% of account cash


@dataclass
class RiskDecision:
    verdict: RiskVerdict
    reason: str
    caps: RiskCaps
    daily_loss: float = 0.0
    weekly_loss: float = 0.0
    open_contracts_on_ticker: int = 0
    session_consecutive_losses: int = 0
    session_drawdown: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.verdict is RiskVerdict.ALLOW


class RiskGuard:
    """Stateless-ish checker — all state comes from the entries list."""

    def __init__(self, caps: RiskCaps | None = None):
        self._caps = caps or RiskCaps()

    @property
    def caps(self) -> RiskCaps:
        return self._caps

    # ------------------------------------------------------------------ public
    def check_entry(
        self,
        *,
        ticker: str,
        proposed_contracts: int,
        account: Account,
        journal: Iterable[JournalEntry],
        as_of: datetime,
        session_only: bool = False,
    ) -> RiskDecision:
        """Decide whether a proposed entry is permitted.

        ``session_only`` flips on the 0DTE circuit breaker: failures on the
        intraday session-loss counter take precedence over the daily cap so the
        module halts immediately rather than after the day's book is closed.
        """
        entries = list(journal)
        today = _local_date(as_of)

        daily_loss = _realized_loss(entries, since=_start_of_day(as_of), until=as_of)
        weekly_loss = _realized_loss(entries, since=_start_of_week(as_of), until=as_of)
        open_contracts = sum(
            e.contracts for e in entries
            if e.ticker.upper() == ticker.upper() and e.outcome is JournalOutcome.OPEN
        )
        session_entries = [e for e in entries if _local_date(e.opened_at) == today]
        consecutive_losses = _trailing_consecutive_losses(session_entries)
        session_dd = _session_drawdown(session_entries, account)

        notes = [
            f"Daily realized loss: ${daily_loss:,.0f} (cap ${self._caps.max_daily_loss:,.0f})",
            f"Weekly realized loss: ${weekly_loss:,.0f} (cap ${self._caps.max_weekly_loss:,.0f})",
            f"Open contracts on {ticker.upper()}: {open_contracts} (cap {self._caps.max_contracts_per_ticker})",
        ]

        # Session-scoped rules fire first when requested, so 0DTE halts cleanly.
        if session_only:
            if (
                self._caps.session_max_consecutive_losses is not None
                and consecutive_losses >= self._caps.session_max_consecutive_losses
            ):
                return RiskDecision(
                    verdict=RiskVerdict.BLOCK_CONSECUTIVE_LOSSES,
                    reason=(
                        f"{consecutive_losses} consecutive session losses "
                        f">= cap {self._caps.session_max_consecutive_losses}."
                    ),
                    caps=self._caps,
                    daily_loss=daily_loss,
                    weekly_loss=weekly_loss,
                    open_contracts_on_ticker=open_contracts,
                    session_consecutive_losses=consecutive_losses,
                    session_drawdown=session_dd,
                    notes=notes,
                )
            if (
                self._caps.session_max_drawdown_pct is not None
                and account.cash > 0
                and session_dd >= self._caps.session_max_drawdown_pct * account.cash
            ):
                return RiskDecision(
                    verdict=RiskVerdict.BLOCK_SESSION_DRAWDOWN,
                    reason=(
                        f"Session drawdown ${session_dd:,.0f} >= "
                        f"{self._caps.session_max_drawdown_pct:.1%} of cash."
                    ),
                    caps=self._caps,
                    daily_loss=daily_loss,
                    weekly_loss=weekly_loss,
                    open_contracts_on_ticker=open_contracts,
                    session_consecutive_losses=consecutive_losses,
                    session_drawdown=session_dd,
                    notes=notes,
                )

        if open_contracts + proposed_contracts > self._caps.max_contracts_per_ticker:
            return RiskDecision(
                verdict=RiskVerdict.BLOCK_TICKER_CAP,
                reason=(
                    f"{open_contracts} open + {proposed_contracts} proposed > "
                    f"per-ticker cap of {self._caps.max_contracts_per_ticker}."
                ),
                caps=self._caps,
                daily_loss=daily_loss,
                weekly_loss=weekly_loss,
                open_contracts_on_ticker=open_contracts,
                session_consecutive_losses=consecutive_losses,
                session_drawdown=session_dd,
                notes=notes,
            )
        if daily_loss >= self._caps.max_daily_loss:
            return RiskDecision(
                verdict=RiskVerdict.BLOCK_DAILY_LOSS,
                reason=f"Daily loss ${daily_loss:,.0f} at or over cap.",
                caps=self._caps,
                daily_loss=daily_loss,
                weekly_loss=weekly_loss,
                open_contracts_on_ticker=open_contracts,
                session_consecutive_losses=consecutive_losses,
                session_drawdown=session_dd,
                notes=notes,
            )
        if weekly_loss >= self._caps.max_weekly_loss:
            return RiskDecision(
                verdict=RiskVerdict.BLOCK_WEEKLY_LOSS,
                reason=f"Weekly loss ${weekly_loss:,.0f} at or over cap.",
                caps=self._caps,
                daily_loss=daily_loss,
                weekly_loss=weekly_loss,
                open_contracts_on_ticker=open_contracts,
                session_consecutive_losses=consecutive_losses,
                session_drawdown=session_dd,
                notes=notes,
            )

        return RiskDecision(
            verdict=RiskVerdict.ALLOW,
            reason="Within all configured caps.",
            caps=self._caps,
            daily_loss=daily_loss,
            weekly_loss=weekly_loss,
            open_contracts_on_ticker=open_contracts,
            session_consecutive_losses=consecutive_losses,
            session_drawdown=session_dd,
            notes=notes,
        )


# ---------------------------------------------------------------------- helpers
def _local_date(dt: datetime) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date()


def _start_of_day(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_week(dt: datetime) -> datetime:
    return _start_of_day(dt) - timedelta(days=7)


def _realized_loss(
    entries: Iterable[JournalEntry], *, since: datetime, until: datetime
) -> float:
    """Sum of *negative* realized P/L for entries closed in [since, until]."""
    total = 0.0
    for e in entries:
        if e.closed_at is None or e.realized_pnl >= 0:
            continue
        closed_at = e.closed_at if e.closed_at.tzinfo else e.closed_at.replace(tzinfo=timezone.utc)
        if since <= closed_at <= until:
            total += -e.realized_pnl
    return total


def _trailing_consecutive_losses(session_entries: list[JournalEntry]) -> int:
    """Count losses in a row at the *end* of the session (most recent first)."""
    closed = [
        e for e in session_entries if e.outcome in {JournalOutcome.WIN, JournalOutcome.LOSS}
    ]
    closed.sort(key=lambda e: e.closed_at or e.opened_at)
    count = 0
    for entry in reversed(closed):
        if entry.outcome is JournalOutcome.LOSS:
            count += 1
        else:
            break
    return count


def _session_drawdown(session_entries: list[JournalEntry], account: Account) -> float:
    """Sum of negative realized P/L booked in the current session."""
    total = 0.0
    for e in session_entries:
        if e.realized_pnl < 0:
            total += -e.realized_pnl
    return total

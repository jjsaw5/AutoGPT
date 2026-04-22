"""Historical-replay backtest engine.

Feeds dated ``OptionChain`` snapshots to a strategist, marks open positions to
market each session using BSM against that day's spot + ATM IV, and records
P/L in a ``TradeJournal``. Output is an equity curve plus the Phase-4 metric
bundle (CAGR / max DD / Sharpe / Sortino / win rate / profit factor).

Mark-to-market deliberately re-prices each leg with BSM rather than trying to
match exact contract symbols across snapshots — the mock provider generates
chains on a 2-point strike grid and the same leg may not be listed on every
date. For real providers, a future refinement is to look the exact symbol up
and fall back to BSM only when it's missing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable, Protocol

from pydantic import BaseModel

from app.backtest.metrics import PerformanceMetrics, compute_metrics
from app.core.bsm import price as bsm_price
from app.core.models import (
    CONTRACT_MULTIPLIER,
    Account,
    JournalEntry,
    JournalOutcome,
    ManagementVerdict,
    MarketSnapshot,
    OptionChain,
    OptionContract,
    Position,
    PositionSize,
    TradeLeg,
    TradeSetup,
)
from app.journal.store import TradeJournal

ChainFactory = Callable[[date], OptionChain]


class _Sizer(Protocol):
    def __call__(self, setup: TradeSetup, account: Account) -> PositionSize: ...


class _Analyzer(Protocol):
    def __call__(self, ticker: str, chain: OptionChain) -> TradeSetup | None: ...


class _Manager(Protocol):
    def __call__(self, position: Position, market: MarketSnapshot) -> object: ...


class EquityPoint(BaseModel):
    date: date
    equity: float
    open_positions: int


class BacktestResult(BaseModel):
    ticker: str
    strategist: str
    start: date
    end: date
    initial_cash: float
    final_cash: float
    trade_count: int
    metrics: dict[str, float | int]
    equity_curve: list[EquityPoint]
    trades: list[JournalEntry]


@dataclass
class _OpenPosition:
    position: Position
    entry_total_cost: float  # dollars at entry (signed: + debit, − credit received)
    entry_mids: dict[str, float] = field(default_factory=dict)  # by "R{strike}" key

    def leg_key(self, leg: TradeLeg) -> str:
        return f"{leg.contract.right.value}{leg.contract.strike:.4f}{leg.contract.expiry}"


class Backtester:
    """Replay a single ticker against a single strategist.

    The strategist is interacted with via three callables pulled from it —
    ``analyze``, ``size``, ``manage`` — so a test can inject custom logic without
    constructing a full :class:`Strategist` implementation.
    """

    def __init__(
        self,
        *,
        ticker: str,
        strategist_name: str,
        analyze: _Analyzer,
        size: _Sizer,
        manage: _Manager,
        chain_factory: ChainFactory,
        account: Account,
        start: date,
        end: date,
        risk_free_rate: float = 0.045,
        journal: TradeJournal | None = None,
    ):
        self._ticker = ticker.upper()
        self._strategist_name = strategist_name
        self._analyze = analyze
        self._size = size
        self._manage = manage
        self._chain_factory = chain_factory
        self._account = account
        self._start = start
        self._end = end
        self._risk_free = risk_free_rate
        self._journal = journal or TradeJournal(":memory:")

    # =============================================================== public API
    def run(self) -> BacktestResult:
        cash = self._account.cash
        open_positions: list[_OpenPosition] = []
        equity_curve: list[EquityPoint] = []
        trade_pnls: list[float] = []

        for day in _session_days(self._start, self._end):
            chain = self._chain_factory(day)
            # 1) mark open positions, decide if any should close, settle expired.
            still_open: list[_OpenPosition] = []
            for op in open_positions:
                mark_value = self._mark_to_market_value(op, chain)
                current_pnl = mark_value - op.entry_total_cost
                snapshot = MarketSnapshot(
                    ticker=self._ticker,
                    spot=chain.spot,
                    as_of=chain.as_of,
                    chain=chain,
                )
                op.position = op.position.model_copy(update={"current_pnl": current_pnl})
                action = self._manage(op.position, snapshot)
                verdict = getattr(action, "verdict", None)
                forced_expiry = self._position_expired(op.position, day)
                if forced_expiry or verdict in {
                    ManagementVerdict.CLOSE_WINNER,
                    ManagementVerdict.CLOSE_TIME,
                }:
                    realised = self._close_position(op, chain, day, forced=forced_expiry)
                    cash += realised
                    trade_pnls.append(realised)
                else:
                    still_open.append(op)
            open_positions = still_open

            # 2) look for a new entry if we have room.
            setup = self._analyze(self._ticker, chain)
            if setup is not None and setup.strategy != "skip" and setup.legs:
                sized = self._size(setup, Account(**{**self._account.model_dump(), "cash": cash}))
                if sized.contracts > 0:
                    entry_cost = self._spread_mid_sum(setup.legs) * CONTRACT_MULTIPLIER * sized.contracts
                    cash -= entry_cost
                    position = Position(
                        setup=setup, size=sized, opened_at=chain.as_of, current_pnl=0.0
                    )
                    open_positions.append(
                        _OpenPosition(
                            position=position,
                            entry_total_cost=entry_cost,
                            entry_mids={
                                _leg_key(leg): leg.contract.mid for leg in setup.legs
                            },
                        )
                    )
                    self._journal.record(
                        JournalEntry(
                            ticker=self._ticker,
                            strategy=setup.strategy,
                            strategist=self._strategist_name,
                            thesis=setup.thesis,
                            opened_at=chain.as_of,
                            contracts=sized.contracts,
                            entry_credit=setup.net_credit,
                            max_loss=setup.max_loss,
                            planned_size_contracts=sized.contracts,
                            outcome=JournalOutcome.OPEN,
                            setup_snapshot=setup,
                        )
                    )

            # 3) record equity = cash + marked value of open positions.
            open_value = sum(self._mark_to_market_value(op, chain) for op in open_positions)
            equity_curve.append(
                EquityPoint(
                    date=day, equity=round(cash + open_value, 2), open_positions=len(open_positions)
                )
            )

        # 4) force-close anything still open at the final bar.
        final_chain = self._chain_factory(self._end)
        for op in open_positions:
            realised = self._close_position(op, final_chain, self._end, forced=True)
            cash += realised
            trade_pnls.append(realised)
        if open_positions:
            equity_curve.append(
                EquityPoint(
                    date=self._end, equity=round(cash, 2), open_positions=0,
                )
            )

        equity_values = [self._account.cash, *[p.equity for p in equity_curve]]
        metrics: PerformanceMetrics = compute_metrics(
            equity=equity_values,
            trade_pnls=trade_pnls,
            days=max((self._end - self._start).days, 1),
        )
        trades = self._journal.list(limit=10_000)
        return BacktestResult(
            ticker=self._ticker,
            strategist=self._strategist_name,
            start=self._start,
            end=self._end,
            initial_cash=self._account.cash,
            final_cash=round(cash, 2),
            trade_count=len(trade_pnls),
            metrics=metrics.to_dict(),
            equity_curve=equity_curve,
            trades=trades,
        )

    # ================================================================= internals
    def _mark_to_market_value(self, op: _OpenPosition, chain: OptionChain) -> float:
        """Current value of an open spread, in dollars. Positive = long asset."""
        pos = op.position
        per_spread = 0.0
        for leg in pos.setup.legs:
            per_spread += leg.quantity * self._reprice_leg(leg.contract, chain)
        return per_spread * CONTRACT_MULTIPLIER * pos.size.contracts

    def _reprice_leg(self, contract: OptionContract, chain: OptionChain) -> float:
        dte_days = (contract.expiry - chain.as_of.date()).days
        t = max(dte_days, 0) / 365.0
        # Use the chain's ATM IV for the nearest listed expiry; fall back to
        # the original contract's IV so we don't end up with sigma=0 mid-trade.
        atm_iv = _atm_iv(chain) or contract.implied_vol or 0.30
        return bsm_price(chain.spot, contract.strike, t, self._risk_free, atm_iv, contract.right)

    def _close_position(
        self, op: _OpenPosition, chain: OptionChain, today: date, *, forced: bool
    ) -> float:
        """Close the spread at current marks and record the journal entry."""
        current_value = self._mark_to_market_value(op, chain)
        realised = current_value - op.entry_total_cost
        # Reopen the journal row and stamp outcome.
        outcome = _outcome(realised, forced)
        entries = self._journal.list(ticker=self._ticker)
        target = next(
            (e for e in entries if e.outcome is JournalOutcome.OPEN
             and e.opened_at == op.position.opened_at),
            None,
        )
        if target is not None and target.id is not None:
            exit_credit = (
                self._spread_mid_sum(op.position.setup.legs, mark_chain=chain)
            )
            self._journal.close(
                target.id,
                exit_credit=-exit_credit,  # credit if value is negative at exit
                realized_pnl=realised,
                closed_at=chain.as_of,
                outcome=outcome,
                notes="forced close at final bar" if forced else "managed close",
            )
        return realised

    def _spread_mid_sum(
        self, legs: Iterable[TradeLeg], mark_chain: OptionChain | None = None
    ) -> float:
        """Sum ``qty × mid`` across legs. Uses chain repricing if given."""
        total = 0.0
        for leg in legs:
            mid = (
                self._reprice_leg(leg.contract, mark_chain)
                if mark_chain is not None
                else leg.contract.mid
            )
            total += leg.quantity * mid
        return total

    @staticmethod
    def _position_expired(pos: Position, today: date) -> bool:
        if not pos.setup.legs:
            return False
        return min(leg.contract.expiry for leg in pos.setup.legs) <= today


# --------------------------------------------------------------------- helpers
def _leg_key(leg: TradeLeg) -> str:
    return f"{leg.contract.right.value}{leg.contract.strike:.4f}{leg.contract.expiry}"


def _atm_iv(chain: OptionChain) -> float | None:
    candidates = [c for c in chain.contracts if c.implied_vol]
    if not candidates:
        return None
    atm = min(candidates, key=lambda c: abs(c.strike - chain.spot))
    return atm.implied_vol


def _outcome(realised: float, forced: bool) -> JournalOutcome:
    if realised > 0:
        return JournalOutcome.WIN
    if realised < 0:
        return JournalOutcome.LOSS
    return JournalOutcome.SCRATCH


def _session_days(start: date, end: date) -> list[date]:
    """Mon–Fri only — the mock provider doesn't know about exchange holidays,
    but skipping weekends keeps the day count roughly honest for CAGR."""
    out: list[date] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out

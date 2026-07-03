"""FastAPI routes.

Phase 1:
- ``GET /api/chain/{ticker}`` — raw chain payload (debugging / UI)
- ``POST /api/analyze`` — one ticker + bias → one Sosnoff TradeSetup
- ``POST /api/size`` — size a supplied setup against a supplied account

Phase 2:
- ``POST /api/unified-analyze`` — run Sosnoff, Thorp, and Saliba side-by-side

Phase 3:
- unified-analyze extended to include HighVolume and 0DTE
- ``POST /api/journal/entries`` — record a paper fill
- ``POST /api/journal/close/{entry_id}`` — close a fill
- ``GET  /api/journal/entries`` — list recorded fills
- ``GET  /api/journal/analytics`` — win rate, R-multiples, Kelly drift
- ``POST /api/risk/check`` — ask the RiskGuard if a proposed entry is allowed
- ``GET  /api/zero-dte/signals/{ticker}`` — signal log for today's 0DTE session

Phase 4:
- ``POST /api/backtest/run`` — replay a strategist over a synthetic date range

Phase 5:
- ``POST /api/risk/dashboard`` — aggregated Greeks + exposure + warnings on
  open journal entries (requires the entries to carry a setup snapshot)
- ``POST /api/bankroll/status`` — deployed vs. per-strategist caps
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_journal, get_provider
from app.backtest.engine import Backtester, BacktestResult
from app.bankroll.manager import BankrollStatus, compute_bankroll, default_budgets
from app.core.models import (
    Account,
    JournalEntry,
    JournalOutcome,
    OptionChain,
    PositionSize,
    TradeSetup,
)
from app.data.base import DataProvider
from app.data.mock_provider import MockProvider
from app.journal.analytics import compute_analytics
from app.journal.store import TradeJournal
from app.risk.dashboard import DashboardConfig, compute_dashboard
from app.risk.guard import RiskCaps, RiskGuard
from app.strategists.high_volume import HighVolumeStrategist
from app.strategists.saliba import SalibaStrategist
from app.strategists.sosnoff import Bias, SosnoffStrategist, iv_percentile, iv_rank
from app.strategists.thorp import ThorpStrategist
from app.strategists.zero_dte import ZeroDTEStrategist

router = APIRouter(prefix="/api")


class AnalyzeRequest(BaseModel):
    ticker: str
    bias: Literal["neutral", "bullish", "bearish"] = "neutral"


class AnalyzeResponse(BaseModel):
    ticker: str
    bias: Bias
    spot: float
    iv_rank: float
    iv_percentile: float
    setup: TradeSetup | None
    banner: str = Field(
        default="Educational tool. Not financial advice. Paper trading only in v1.",
        description="The guardrail banner — always surface this in the UI.",
    )


class SizeRequest(BaseModel):
    setup: TradeSetup
    account: Account


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/chain/{ticker}", response_model=OptionChain)
def get_chain(ticker: str, provider: DataProvider = Depends(get_provider)) -> OptionChain:
    try:
        return provider.get_chain(ticker)
    except Exception as exc:  # pragma: no cover - provider-specific failures
        raise HTTPException(status_code=502, detail=f"Provider error: {exc}") from exc


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest, provider: DataProvider = Depends(get_provider)) -> AnalyzeResponse:
    chain = provider.get_chain(req.ticker)
    strategist = SosnoffStrategist(provider=provider)
    setup = strategist.analyze(req.ticker, chain, bias=req.bias)
    history = provider.get_iv_history(req.ticker)
    current_iv = history[-1].atm_iv if history else 0.0
    return AnalyzeResponse(
        ticker=req.ticker.upper(),
        bias=req.bias,
        spot=chain.spot,
        iv_rank=iv_rank(history, current_iv),
        iv_percentile=iv_percentile(history, current_iv),
        setup=setup,
    )


@router.post("/size", response_model=PositionSize)
def size(req: SizeRequest, provider: DataProvider = Depends(get_provider)) -> PositionSize:
    strategist = SosnoffStrategist(provider=provider)
    return strategist.size(req.setup, req.account)


class StrategistResult(BaseModel):
    """One strategist's verdict on a ticker, shaped for the unified card."""

    name: str
    verdict: Literal["trade", "skip", "error"]
    setup: TradeSetup | None
    headline: str = Field(description="One-line summary for the UI.")
    error: str | None = None


class UnifiedResponse(BaseModel):
    ticker: str
    bias: Bias
    spot: float
    iv_rank: float
    iv_percentile: float
    results: list[StrategistResult]
    banner: str = Field(
        default="Educational tool. Not financial advice. Paper trading only in v1."
    )


def _headline(setup: TradeSetup | None) -> str:
    if setup is None:
        return "No data."
    if setup.strategy == "skip":
        return setup.thesis
    if setup.pop is not None and setup.max_loss > 0:
        return (
            f"{setup.strategy.replace('_', ' ')} · R:R {setup.reward_risk:.2f} · "
            f"POP {setup.pop * 100:.0f}% · max loss ${setup.max_loss * 100:.0f}"
        )
    return (
        f"{setup.strategy.replace('_', ' ')} · "
        f"EV ${(setup.expected_value or 0) * 100:.0f} · max loss ${setup.max_loss * 100:.0f}"
    )


@router.post("/unified-analyze", response_model=UnifiedResponse)
def unified_analyze(
    req: AnalyzeRequest, provider: DataProvider = Depends(get_provider)
) -> UnifiedResponse:
    """Evaluate one ticker with every wired strategist.

    Each strategist runs in isolation — if one errors, the others still return.
    The UI renders them side-by-side so the comparison is obvious.
    """
    chain = provider.get_chain(req.ticker)
    history = provider.get_iv_history(req.ticker)
    current_iv = history[-1].atm_iv if history else 0.0

    results: list[StrategistResult] = []

    def _run(name: str, setup_fn):  # type: ignore[no-untyped-def]
        try:
            setup = setup_fn()
            verdict: Literal["trade", "skip", "error"]
            if setup is None:
                verdict = "skip"
            elif setup.strategy == "skip":
                verdict = "skip"
            else:
                verdict = "trade"
            results.append(
                StrategistResult(
                    name=name,
                    verdict=verdict,
                    setup=setup,
                    headline=_headline(setup),
                )
            )
        except Exception as exc:  # pragma: no cover - defensive
            results.append(
                StrategistResult(name=name, verdict="error", setup=None, headline="Error", error=str(exc))
            )

    journal_entries = list(get_journal().list(limit=5_000))

    sosnoff = SosnoffStrategist(provider=provider)
    thorp = ThorpStrategist(provider=provider)
    saliba = SalibaStrategist(provider=provider)
    high_volume = HighVolumeStrategist(provider=provider, journal=journal_entries)
    zero_dte = ZeroDTEStrategist(provider=provider, journal=journal_entries)

    _run("sosnoff", lambda: sosnoff.analyze(req.ticker, chain, bias=req.bias))
    _run("thorp", lambda: thorp.analyze(req.ticker, chain))
    _run("saliba", lambda: saliba.analyze(req.ticker, chain))
    _run("high_volume", lambda: high_volume.analyze(req.ticker, chain))
    _run("zero_dte", lambda: zero_dte.analyze(req.ticker, chain))

    return UnifiedResponse(
        ticker=req.ticker.upper(),
        bias=req.bias,
        spot=chain.spot,
        iv_rank=iv_rank(history, current_iv),
        iv_percentile=iv_percentile(history, current_iv),
        results=results,
    )


# -------------------------------------------------------------------- Journal
class RecordEntryRequest(BaseModel):
    ticker: str
    strategy: str
    strategist: str
    thesis: str
    contracts: int = Field(ge=1)
    entry_credit: float
    max_loss: float = Field(ge=0)
    planned_size_contracts: int | None = None
    notes: str = ""
    opened_at: datetime | None = None


class CloseEntryRequest(BaseModel):
    exit_credit: float
    realized_pnl: float
    outcome: JournalOutcome
    closed_at: datetime | None = None
    notes: str | None = None


@router.post("/journal/entries", response_model=JournalEntry)
def record_entry(
    req: RecordEntryRequest, journal: TradeJournal = Depends(get_journal)
) -> JournalEntry:
    entry = JournalEntry(
        ticker=req.ticker,
        strategy=req.strategy,
        strategist=req.strategist,
        thesis=req.thesis,
        opened_at=req.opened_at or datetime.now(tz=timezone.utc),
        contracts=req.contracts,
        entry_credit=req.entry_credit,
        max_loss=req.max_loss,
        planned_size_contracts=req.planned_size_contracts,
        notes=req.notes,
    )
    return journal.record(entry)


@router.post("/journal/close/{entry_id}", response_model=JournalEntry)
def close_entry(
    entry_id: int,
    req: CloseEntryRequest,
    journal: TradeJournal = Depends(get_journal),
) -> JournalEntry:
    updated = journal.close(
        entry_id,
        exit_credit=req.exit_credit,
        realized_pnl=req.realized_pnl,
        closed_at=req.closed_at or datetime.now(tz=timezone.utc),
        outcome=req.outcome,
        notes=req.notes,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Journal entry {entry_id} not found")
    return updated


@router.get("/journal/entries", response_model=list[JournalEntry])
def list_entries(
    ticker: str | None = None,
    strategist: str | None = None,
    limit: int = 200,
    journal: TradeJournal = Depends(get_journal),
) -> list[JournalEntry]:
    return journal.list(ticker=ticker, strategist=strategist, limit=limit)


class AnalyticsResponse(BaseModel):
    trades: int
    closed_trades: int
    open_trades: int
    wins: int
    losses: int
    scratches: int
    win_rate: float
    average_winner: float
    average_loser: float
    profit_factor: float
    expectancy: float
    r_multiples: list[float]
    average_r: float
    median_r: float
    kelly_implied_vs_actual: list[dict[str, float | int | str]]
    by_strategist: dict[str, dict[str, float]]


@router.get("/journal/analytics", response_model=AnalyticsResponse)
def journal_analytics(
    journal: TradeJournal = Depends(get_journal),
) -> AnalyticsResponse:
    analytics = compute_analytics(journal.list(limit=10_000))
    return AnalyticsResponse(**analytics.to_dict())


# ----------------------------------------------------------------------- Risk
class RiskCheckRequest(BaseModel):
    ticker: str
    proposed_contracts: int = Field(ge=0)
    account: Account
    session_only: bool = False


class RiskCheckResponse(BaseModel):
    verdict: str
    allowed: bool
    reason: str
    daily_loss: float
    weekly_loss: float
    open_contracts_on_ticker: int
    session_consecutive_losses: int
    session_drawdown: float
    notes: list[str]


@router.post("/risk/check", response_model=RiskCheckResponse)
def risk_check(
    req: RiskCheckRequest,
    journal: TradeJournal = Depends(get_journal),
) -> RiskCheckResponse:
    guard = RiskGuard(caps=RiskCaps())
    decision = guard.check_entry(
        ticker=req.ticker,
        proposed_contracts=req.proposed_contracts,
        account=req.account,
        journal=journal.list(limit=5_000),
        as_of=datetime.now(tz=timezone.utc),
        session_only=req.session_only,
    )
    return RiskCheckResponse(
        verdict=decision.verdict.value,
        allowed=decision.allowed,
        reason=decision.reason,
        daily_loss=decision.daily_loss,
        weekly_loss=decision.weekly_loss,
        open_contracts_on_ticker=decision.open_contracts_on_ticker,
        session_consecutive_losses=decision.session_consecutive_losses,
        session_drawdown=decision.session_drawdown,
        notes=decision.notes,
    )


# --------------------------------------------------------------------- 0DTE
class ZeroDTESignal(BaseModel):
    ticker: str
    session_date: date
    last_close: float
    vwap: float
    opening_range_high: float
    opening_range_low: float
    gex_proxy: float
    direction: Literal["long", "short"]
    orb_vote: bool
    vwap_vote: bool
    gex_vote: bool
    score: int
    would_trade: bool
    notes: list[str]


# ----------------------------------------------------------------- Backtest
BacktestStrategist = Literal["sosnoff", "saliba", "thorp", "high_volume"]


class BacktestRequest(BaseModel):
    ticker: str = "SPY"
    strategist: BacktestStrategist = "saliba"
    start: date
    end: date
    account: Account = Account(cash=100_000)
    # Synthetic market path — keeps Phase 4 self-contained without paid data.
    base_spot: float = 100.0
    spot_drift_per_day: float = 0.05
    spot_wobble_amplitude: float = 3.0
    spot_wobble_period_days: float = 15.0
    base_iv: float = 0.35
    iv_amplitude: float = 0.05
    iv_period_days: float = 20.0
    risk_free_rate: float = 0.045
    fixed_contracts: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Override the strategist's Kelly sizer to use N contracts per entry. "
            "Useful for demos — synthetic data often gives negative-EV setups that "
            "Kelly correctly refuses, leaving the engine unexercised."
        ),
    )


def _synthetic_chain_factory(req: BacktestRequest) -> tuple[object, object]:
    def make(d: date) -> OptionChain:
        idx = (d - req.start).days
        spot = (
            req.base_spot
            + req.spot_drift_per_day * idx
            + req.spot_wobble_amplitude * math.sin(idx / req.spot_wobble_period_days)
        )
        iv = req.base_iv + req.iv_amplitude * math.cos(idx / req.iv_period_days)
        as_of = datetime.combine(d, datetime.min.time().replace(hour=15), tzinfo=timezone.utc)
        return MockProvider(spot=max(spot, 1.0), base_iv=max(iv, 0.05), as_of=as_of).get_chain(
            req.ticker
        )

    return None, make


def _strategist_for_backtest(
    name: BacktestStrategist, provider: DataProvider
) -> tuple[object, object, object, str]:
    """Return (analyze, size, manage, display_name)."""
    if name == "sosnoff":
        s = SosnoffStrategist(provider=provider)
        return (lambda t, c: s.analyze(t, c, bias="neutral"), s.size, s.manage, "sosnoff")
    if name == "saliba":
        s2 = SalibaStrategist(provider=provider)
        return (s2.analyze, s2.size, s2.manage, "saliba")
    if name == "thorp":
        s3 = ThorpStrategist(provider=provider)
        return (s3.analyze, s3.size, s3.manage, "thorp")
    if name == "high_volume":
        s4 = HighVolumeStrategist(provider=provider)
        return (s4.analyze, s4.size, s4.manage, "high_volume")
    raise HTTPException(status_code=400, detail=f"Unknown strategist {name!r}")


@router.post("/backtest/run", response_model=BacktestResult)
def backtest_run(
    req: BacktestRequest, provider: DataProvider = Depends(get_provider)
) -> BacktestResult:
    if req.end < req.start:
        raise HTTPException(status_code=400, detail="end must be on or after start")
    analyze, size_fn, manage, label = _strategist_for_backtest(req.strategist, provider)
    _, chain_factory = _synthetic_chain_factory(req)
    if req.fixed_contracts is not None:
        fixed_n = req.fixed_contracts

        def _fixed_sizer(setup: TradeSetup, account: Account) -> PositionSize:
            per_spread_risk = max(setup.max_loss, 0.01) * 100
            return PositionSize(
                contracts=fixed_n,
                capital_at_risk=fixed_n * per_spread_risk,
                pct_of_account=(fixed_n * per_spread_risk) / account.cash if account.cash > 0 else 0.0,
                rationale=f"fixed_contracts override ({fixed_n}/trade); Kelly bypassed.",
            )

        size_fn = _fixed_sizer

    bt = Backtester(
        ticker=req.ticker,
        strategist_name=label,
        analyze=analyze,  # type: ignore[arg-type]
        size=size_fn,  # type: ignore[arg-type]
        manage=manage,  # type: ignore[arg-type]
        chain_factory=chain_factory,  # type: ignore[arg-type]
        account=req.account,
        start=req.start,
        end=req.end,
        risk_free_rate=req.risk_free_rate,
    )
    return bt.run()


@router.get("/zero-dte/signals/{ticker}", response_model=ZeroDTESignal)
def zero_dte_signals(
    ticker: str, provider: DataProvider = Depends(get_provider)
) -> ZeroDTESignal:
    today = provider.now().date()
    bars = provider.get_intraday_bars(ticker, today)
    if not bars:
        raise HTTPException(status_code=404, detail=f"No intraday bars for {ticker}")
    chain = provider.get_chain(ticker)
    z = ZeroDTEStrategist(provider=provider)
    signal = z._evaluate_signals(bars)  # noqa: SLF001 - test seam, keeps router thin
    or_high = max(b.high for b in bars[:30])
    or_low = min(b.low for b in bars[:30])
    setup = z.analyze(ticker, chain)
    would_trade = setup is not None and setup.strategy != "skip"
    notes = setup.notes if setup else []
    return ZeroDTESignal(
        ticker=ticker.upper(),
        session_date=today,
        last_close=bars[-1].close,
        vwap=z._vwap(bars),  # noqa: SLF001
        opening_range_high=or_high,
        opening_range_low=or_low,
        gex_proxy=z._gex_proxy(bars),  # noqa: SLF001
        direction=signal.direction,
        orb_vote=signal.orb_vote,
        vwap_vote=signal.vwap_vote,
        gex_vote=signal.gex_vote,
        score=signal.score,
        would_trade=would_trade,
        notes=notes,
    )


# ------------------------------------------------------------ Risk Dashboard
class DashboardRequest(BaseModel):
    account: Account
    ticker_concentration_pct: float = Field(default=0.25, ge=0, le=1)
    strategist_concentration_pct: float = Field(default=0.40, ge=0, le=1)
    max_theoretical_loss_pct: float = Field(default=0.50, ge=0, le=1)


class DashboardResponse(BaseModel):
    open_positions: int
    total_contracts: int
    total_capital_at_risk: float
    total_max_theoretical_loss: float
    greeks: dict[str, float | int]
    by_ticker: list[dict[str, object]]
    by_strategist: list[dict[str, object]]
    warnings: list[dict[str, str]]


@router.post("/risk/dashboard", response_model=DashboardResponse)
def risk_dashboard(
    req: DashboardRequest,
    journal: TradeJournal = Depends(get_journal),
) -> DashboardResponse:
    cfg = DashboardConfig(
        concentration_ticker_pct=req.ticker_concentration_pct,
        concentration_strategist_pct=req.strategist_concentration_pct,
        max_theoretical_loss_pct=req.max_theoretical_loss_pct,
    )
    dashboard = compute_dashboard(
        entries=journal.list(limit=10_000, outcomes=[JournalOutcome.OPEN]),
        account=req.account,
        config=cfg,
    )
    payload = dashboard.to_dict()
    return DashboardResponse(**payload)


# ----------------------------------------------------------------- Bankroll
class BankrollRequest(BaseModel):
    account: Account


class BankrollAllocation(BaseModel):
    name: str
    allocation_pct: float
    allocation_cash: float
    kelly_fraction: float
    max_pct_per_trade: float
    deployed: float
    open_positions: int
    utilization: float
    over_limit: bool


class BankrollResponse(BaseModel):
    cash: float
    total_deployed: float
    total_cap: float
    total_utilization: float
    over_total_cap: bool
    allocations: list[BankrollAllocation]


@router.post("/bankroll/status", response_model=BankrollResponse)
def bankroll_status(
    req: BankrollRequest,
    journal: TradeJournal = Depends(get_journal),
) -> BankrollResponse:
    status: BankrollStatus = compute_bankroll(
        account=req.account,
        entries=journal.list(limit=10_000),
        budgets=default_budgets(),
    )
    payload = status.to_dict()
    return BankrollResponse(**payload)

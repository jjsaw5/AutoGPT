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
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_journal, get_provider
from app.core.models import (
    Account,
    JournalEntry,
    JournalOutcome,
    OptionChain,
    PositionSize,
    TradeSetup,
)
from app.data.base import DataProvider
from app.journal.analytics import compute_analytics
from app.journal.store import TradeJournal
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

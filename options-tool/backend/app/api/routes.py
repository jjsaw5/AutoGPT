"""FastAPI routes.

Phase 1:
- ``GET /api/chain/{ticker}`` — raw chain payload (debugging / UI)
- ``POST /api/analyze`` — one ticker + bias → one Sosnoff TradeSetup
- ``POST /api/size`` — size a supplied setup against a supplied account

Phase 2:
- ``POST /api/unified-analyze`` — run Sosnoff, Thorp, and Saliba side-by-side
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_provider
from app.core.models import Account, OptionChain, PositionSize, TradeSetup
from app.data.base import DataProvider
from app.strategists.saliba import SalibaStrategist
from app.strategists.sosnoff import Bias, SosnoffStrategist, iv_percentile, iv_rank
from app.strategists.thorp import ThorpStrategist

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

    sosnoff = SosnoffStrategist(provider=provider)
    thorp = ThorpStrategist(provider=provider)
    saliba = SalibaStrategist(provider=provider)

    _run("sosnoff", lambda: sosnoff.analyze(req.ticker, chain, bias=req.bias))
    _run("thorp", lambda: thorp.analyze(req.ticker, chain))
    _run("saliba", lambda: saliba.analyze(req.ticker, chain))

    return UnifiedResponse(
        ticker=req.ticker.upper(),
        bias=req.bias,
        spot=chain.spot,
        iv_rank=iv_rank(history, current_iv),
        iv_percentile=iv_percentile(history, current_iv),
        results=results,
    )

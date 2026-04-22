"""FastAPI routes for Phase 1.

Surface area is intentionally small:
- ``GET /api/chain/{ticker}`` — raw chain payload (for debugging / the UI)
- ``POST /api/analyze`` — one ticker, one bias, one Sosnoff TradeSetup
- ``POST /api/size`` — size a supplied setup against a supplied account
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_provider
from app.core.models import Account, OptionChain, PositionSize, TradeSetup
from app.data.base import DataProvider
from app.strategists.sosnoff import Bias, SosnoffStrategist, iv_percentile, iv_rank

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

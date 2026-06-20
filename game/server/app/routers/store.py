"""Microtransaction store endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..models import Grant, StoreListing
from ..services import commerce
from .deps import StateDep, get_player

router = APIRouter(prefix="/store", tags=["store"])


class PurchaseRequest(BaseModel):
    player_id: str
    # Required only for real-money listings; supplied by the billing SDK client.
    payment_token: str | None = None


class PurchaseResponse(BaseModel):
    listing_id: str
    paid_currency: str | None
    paid_amount: int
    price_usd: float | None
    granted: list[Grant]


@router.get("", response_model=list[StoreListing])
def list_listings(state: StateDep) -> list[StoreListing]:
    return list(state.store.values())


@router.post("/{listing_id}/purchase", response_model=PurchaseResponse)
def purchase(listing_id: str, body: PurchaseRequest, state: StateDep) -> PurchaseResponse:
    player = get_player(state, body.player_id)
    try:
        receipt = commerce.purchase(state, player, listing_id, body.payment_token)
    except commerce.CommerceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PurchaseResponse(
        listing_id=receipt.listing_id,
        paid_currency=receipt.paid_currency,
        paid_amount=receipt.paid_amount,
        price_usd=receipt.price_usd,
        granted=receipt.granted,
    )

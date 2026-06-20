"""Microtransaction store: purchasing listings with currency or real money."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Player, StoreListing
from ..state import GameState
from . import economy


class CommerceError(Exception):
    pass


@dataclass
class PurchaseReceipt:
    listing_id: str
    paid_currency: str | None
    paid_amount: int
    price_usd: float | None
    granted: list  # list[Grant]


def purchase(
    state: GameState,
    player: Player,
    listing_id: str,
    payment_token: str | None = None,
) -> PurchaseReceipt:
    """Buy a store listing.

    Real-money listings (``price_usd`` set) require a ``payment_token`` that a
    real client would obtain from the platform billing SDK (App Store / Play).
    Here we treat any non-empty token as a validated purchase. Currency listings
    debit the player's wallet instead.
    """
    listing = state.store.get(listing_id)
    if listing is None:
        raise CommerceError(f"unknown listing '{listing_id}'")

    if listing.price_usd is not None:
        _verify_iap(listing, payment_token)
        paid_currency, paid_amount = None, 0
    else:
        if listing.cost_currency is None:
            raise CommerceError("listing has no price configured")
        try:
            economy.debit(player, listing.cost_currency, listing.cost_amount)
        except economy.EconomyError as exc:
            raise CommerceError(str(exc)) from exc
        paid_currency = listing.cost_currency.value
        paid_amount = listing.cost_amount

    economy.apply_grants(player, listing.grants)
    return PurchaseReceipt(
        listing_id=listing.id,
        paid_currency=paid_currency,
        paid_amount=paid_amount,
        price_usd=listing.price_usd,
        granted=listing.grants,
    )


def _verify_iap(listing: StoreListing, payment_token: str | None) -> None:
    # Placeholder for real receipt validation against the app store backend.
    if not payment_token:
        raise CommerceError(
            "real-money purchase requires a payment_token from the billing SDK"
        )

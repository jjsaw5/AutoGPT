"""Wallet, inventory and reward-granting helpers."""

from __future__ import annotations

from ..models import CurrencyCode, Grant, GrantKind, Player


class EconomyError(Exception):
    """Raised on invalid economy operations (e.g. insufficient funds)."""


def balance(player: Player, currency: CurrencyCode) -> int:
    return player.wallet.get(currency, 0)


def credit(player: Player, currency: CurrencyCode, amount: int) -> None:
    if amount < 0:
        raise EconomyError("credit amount must be non-negative")
    player.wallet[currency] = balance(player, currency) + amount


def debit(player: Player, currency: CurrencyCode, amount: int) -> None:
    if amount < 0:
        raise EconomyError("debit amount must be non-negative")
    if balance(player, currency) < amount:
        raise EconomyError(
            f"insufficient {currency.value}: have {balance(player, currency)}, "
            f"need {amount}"
        )
    player.wallet[currency] -= amount


def add_item(player: Player, item_id: str, qty: int = 1) -> None:
    if qty <= 0:
        raise EconomyError("item qty must be positive")
    player.inventory[item_id] = player.inventory.get(item_id, 0) + qty


def remove_item(player: Player, item_id: str, qty: int = 1) -> None:
    owned = player.inventory.get(item_id, 0)
    if owned < qty:
        raise EconomyError(f"player does not own {qty}x {item_id}")
    remaining = owned - qty
    if remaining:
        player.inventory[item_id] = remaining
    else:
        del player.inventory[item_id]


def apply_grant(player: Player, grant: Grant) -> None:
    """Apply a single reward to a player (item into inventory or currency)."""
    if grant.kind == GrantKind.CURRENCY:
        credit(player, CurrencyCode(grant.ref), grant.amount)
    else:
        add_item(player, grant.ref, grant.amount)


def apply_grants(player: Player, grants: list[Grant]) -> None:
    for grant in grants:
        apply_grant(player, grant)

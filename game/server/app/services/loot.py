"""Loot generation and world chests."""

from __future__ import annotations

import random

from ..models import Character, Grant, GrantKind, LootTable, Player
from ..state import GameState
from . import economy


class LootError(Exception):
    pass


def roll_table(table: LootTable, rng: random.Random | None = None) -> list[Grant]:
    """Roll a loot table `rolls` times, returning the granted items.

    A seedable `rng` is accepted so loot is deterministic in tests.
    """
    rng = rng or random.Random()
    if not table.entries:
        return []

    weights = [max(0.0, e.weight) for e in table.entries]
    grants: list[Grant] = []
    for _ in range(table.rolls):
        entry = rng.choices(table.entries, weights=weights, k=1)[0]
        qty = rng.randint(entry.min_qty, entry.max_qty)
        grants.append(Grant(kind=GrantKind.ITEM, ref=entry.item_id, amount=qty))
    return grants


def open_chest(
    state: GameState,
    player: Player,
    character: Character,
    chest_id: str,
    rng: random.Random | None = None,
) -> list[Grant]:
    """Open a world chest once, grant its loot to the player, and record it."""
    chest = state.chests.get(chest_id)
    if chest is None:
        raise LootError(f"unknown chest '{chest_id}'")
    if chest_id in character.opened_chests:
        raise LootError("chest already opened by this character")

    table = state.loot_tables.get(chest.loot_table_id)
    if table is None:
        raise LootError(f"chest references missing loot table '{chest.loot_table_id}'")

    grants = roll_table(table, rng)
    economy.apply_grants(player, grants)
    character.opened_chests.append(chest_id)
    return grants

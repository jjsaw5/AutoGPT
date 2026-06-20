"""In-memory game state + content indexes.

This is the simplest possible persistence layer so the prototype runs with no
database. Everything is keyed by id in plain dicts. The service functions only
touch state through this object, so swapping in a real database later (Postgres,
Redis, etc.) means reimplementing this class — not rewriting game logic.
"""

from __future__ import annotations

from . import content
from .models import (
    ChestDef,
    Character,
    ItemDef,
    LootTable,
    Player,
    QuestDef,
    SkillNode,
    StoreListing,
)


class GameState:
    def __init__(self) -> None:
        # Static content, indexed for fast lookup.
        self.items: dict[str, ItemDef] = {i.id: i for i in content.ITEMS}
        self.loot_tables: dict[str, LootTable] = {
            t.id: t for t in content.LOOT_TABLES
        }
        self.chests: dict[str, ChestDef] = {c.id: c for c in content.CHESTS}
        self.quests: dict[str, QuestDef] = {q.id: q for q in content.QUESTS}
        self.skill_nodes: dict[str, SkillNode] = {
            n.id: n for n in content.SKILL_NODES
        }
        self.store: dict[str, StoreListing] = {
            s.id: s for s in content.STORE_LISTINGS
        }

        # Mutable player data.
        self.players: dict[str, Player] = {}
        self.characters: dict[str, Character] = {}
        self._seq = 0

    def next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}_{self._seq:06d}"


# A single process-wide instance. Injected into routers via a dependency so
# tests can swap in a fresh state.
_state = GameState()


def get_state() -> GameState:
    return _state


def reset_state() -> GameState:
    """Replace the global state with a fresh one (used by tests)."""
    global _state
    _state = GameState()
    return _state

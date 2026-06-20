"""Core domain models for the game backend.

These are engine-agnostic: the same definitions drive the FastAPI server here
and can be mirrored by any client (Godot, Unity, Unreal). Nothing in this module
depends on FastAPI, so the game logic stays portable and easy to unit-test.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums                                                                        #
# --------------------------------------------------------------------------- #
class Rarity(str, Enum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"
    MYTHIC = "mythic"


class ItemType(str, Enum):
    WEAPON = "weapon"
    ARMOR = "armor"
    COSMETIC = "cosmetic"
    CONSUMABLE = "consumable"
    MATERIAL = "material"


class EquipSlot(str, Enum):
    """Loadout slots a character can equip into."""

    PRIMARY = "primary"        # main weapon
    SECONDARY = "secondary"    # sidearm
    HEAD = "head"              # armor
    CHEST = "chest"            # armor
    LEGS = "legs"              # armor
    SKIN = "skin"              # cosmetic character skin
    BACK_BLING = "back_bling"  # cosmetic back accessory
    EMOTE = "emote"            # cosmetic emote


class CurrencyCode(str, Enum):
    COINS = "coins"  # soft currency, earned in-game
    GEMS = "gems"    # premium currency, bought via microtransactions


class GrantKind(str, Enum):
    ITEM = "item"
    CURRENCY = "currency"


# --------------------------------------------------------------------------- #
# Content definitions (static, authored game data)                            #
# --------------------------------------------------------------------------- #
class ItemDef(BaseModel):
    id: str
    name: str
    type: ItemType
    rarity: Rarity = Rarity.COMMON
    slot: Optional[EquipSlot] = None
    stats: dict[str, float] = Field(default_factory=dict)
    description: str = ""
    stackable: bool = False
    max_stack: int = 1


class Grant(BaseModel):
    """A reward payload: either an item (with qty) or an amount of currency."""

    kind: GrantKind
    ref: str          # item id, or CurrencyCode value
    amount: int = 1


class StoreListing(BaseModel):
    """A purchasable entry in the microtransaction store."""

    id: str
    name: str
    description: str = ""
    grants: list[Grant] = Field(default_factory=list)
    # Either an in-game currency cost...
    cost_currency: Optional[CurrencyCode] = None
    cost_amount: int = 0
    # ...or a real-money price (an IAP product, e.g. a gem pack).
    price_usd: Optional[float] = None
    featured: bool = False


class LootEntry(BaseModel):
    item_id: str
    weight: float = 1.0
    min_qty: int = 1
    max_qty: int = 1


class LootTable(BaseModel):
    id: str
    rolls: int = 1
    entries: list[LootEntry] = Field(default_factory=list)


class ChestDef(BaseModel):
    """A chest hidden in the world that grants a loadout when opened."""

    id: str
    name: str
    rarity: Rarity = Rarity.RARE
    position: dict[str, float] = Field(default_factory=dict)  # {x, y, z}
    loot_table_id: str


class SkillNode(BaseModel):
    """A node in a skill tree (Arc Raiders style)."""

    id: str
    name: str
    tree: str
    description: str = ""
    cost: int = 1                                    # skill points per rank
    max_rank: int = 1
    requires: list[str] = Field(default_factory=list)  # prerequisite node ids
    bonuses: dict[str, float] = Field(default_factory=dict)  # per-rank bonuses


class SkillTree(BaseModel):
    id: str
    name: str
    description: str = ""


class AttributeDef(BaseModel):
    code: str
    name: str
    description: str = ""


class QuestObjective(BaseModel):
    id: str
    description: str
    event: str          # event type that progresses this objective
    target: Optional[str] = None  # optional event payload filter (e.g. "chest")
    count: int = 1


class QuestDef(BaseModel):
    id: str
    name: str
    description: str = ""
    required_level: int = 1
    objectives: list[QuestObjective] = Field(default_factory=list)
    rewards: list[Grant] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Player state (mutable, per-account)                                          #
# --------------------------------------------------------------------------- #
class Player(BaseModel):
    id: str
    name: str
    wallet: dict[CurrencyCode, int] = Field(
        default_factory=lambda: {CurrencyCode.COINS: 0, CurrencyCode.GEMS: 0}
    )
    inventory: dict[str, int] = Field(default_factory=dict)  # item_id -> qty


class QuestStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CLAIMED = "claimed"


class PlayerQuest(BaseModel):
    quest_id: str
    status: QuestStatus = QuestStatus.ACTIVE
    progress: dict[str, int] = Field(default_factory=dict)  # objective_id -> count


class Character(BaseModel):
    id: str
    player_id: str
    name: str
    # Character creation choices (engine renders these; backend just stores them).
    appearance: dict[str, str] = Field(default_factory=dict)
    level: int = 1
    xp: int = 0
    attribute_points: int = 0
    skill_points: int = 0
    attributes: dict[str, int] = Field(default_factory=dict)       # code -> value
    unlocked_skills: dict[str, int] = Field(default_factory=dict)  # node_id -> rank
    loadout: dict[EquipSlot, str] = Field(default_factory=dict)    # slot -> item_id
    opened_chests: list[str] = Field(default_factory=list)
    quests: dict[str, PlayerQuest] = Field(default_factory=dict)

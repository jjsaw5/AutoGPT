"""Authored game content (seed data).

In a production game this would live in a database or designer-editable data
files. Keeping it here as plain Python makes the prototype runnable with zero
setup and gives a single place to balance the economy and progression.
"""

from __future__ import annotations

from .models import (
    AttributeDef,
    ChestDef,
    CurrencyCode,
    EquipSlot,
    Grant,
    GrantKind,
    ItemDef,
    ItemType,
    LootEntry,
    LootTable,
    QuestDef,
    QuestObjective,
    Rarity,
    SkillNode,
    SkillTree,
    StoreListing,
)

# --------------------------------------------------------------------------- #
# Attributes (points spent here come from leveling up)                        #
# --------------------------------------------------------------------------- #
ATTRIBUTES: list[AttributeDef] = [
    AttributeDef(code="might", name="Might", description="Increases weapon damage."),
    AttributeDef(code="agility", name="Agility", description="Move and reload speed."),
    AttributeDef(code="vitality", name="Vitality", description="Max health and shields."),
    AttributeDef(code="tech", name="Tech", description="Gadget cooldown and loot luck."),
]

# --------------------------------------------------------------------------- #
# Items                                                                       #
# --------------------------------------------------------------------------- #
ITEMS: list[ItemDef] = [
    # Weapons
    ItemDef(id="wpn_ar_standard", name="Recruit Rifle", type=ItemType.WEAPON,
            rarity=Rarity.COMMON, slot=EquipSlot.PRIMARY,
            stats={"damage": 24, "fire_rate": 6.0, "range": 50}),
    ItemDef(id="wpn_ar_tactical", name="Tactical AR", type=ItemType.WEAPON,
            rarity=Rarity.RARE, slot=EquipSlot.PRIMARY,
            stats={"damage": 33, "fire_rate": 7.0, "range": 55}),
    ItemDef(id="wpn_sniper_phantom", name="Phantom Sniper", type=ItemType.WEAPON,
            rarity=Rarity.LEGENDARY, slot=EquipSlot.PRIMARY,
            stats={"damage": 120, "fire_rate": 0.8, "range": 120}),
    ItemDef(id="wpn_pistol_sidekick", name="Sidekick Pistol", type=ItemType.WEAPON,
            rarity=Rarity.COMMON, slot=EquipSlot.SECONDARY,
            stats={"damage": 18, "fire_rate": 4.0, "range": 30}),
    ItemDef(id="wpn_smg_hailstorm", name="Hailstorm SMG", type=ItemType.WEAPON,
            rarity=Rarity.EPIC, slot=EquipSlot.SECONDARY,
            stats={"damage": 16, "fire_rate": 12.0, "range": 28}),
    # Armor / gear
    ItemDef(id="gear_helm_scout", name="Scout Helm", type=ItemType.ARMOR,
            rarity=Rarity.UNCOMMON, slot=EquipSlot.HEAD, stats={"armor": 10}),
    ItemDef(id="gear_vest_assault", name="Assault Vest", type=ItemType.ARMOR,
            rarity=Rarity.RARE, slot=EquipSlot.CHEST, stats={"armor": 25}),
    ItemDef(id="gear_greaves_runner", name="Runner Greaves", type=ItemType.ARMOR,
            rarity=Rarity.UNCOMMON, slot=EquipSlot.LEGS,
            stats={"armor": 12, "move_speed": 0.05}),
    # Cosmetics
    ItemDef(id="cos_skin_default", name="Recruit Skin", type=ItemType.COSMETIC,
            rarity=Rarity.COMMON, slot=EquipSlot.SKIN),
    ItemDef(id="cos_skin_neon", name="Neon Striker Skin", type=ItemType.COSMETIC,
            rarity=Rarity.EPIC, slot=EquipSlot.SKIN),
    ItemDef(id="cos_back_jetwing", name="Jetwing Back Bling", type=ItemType.COSMETIC,
            rarity=Rarity.RARE, slot=EquipSlot.BACK_BLING),
    ItemDef(id="cos_emote_floss", name="Victory Floss", type=ItemType.COSMETIC,
            rarity=Rarity.RARE, slot=EquipSlot.EMOTE),
    # Consumables / materials
    ItemDef(id="con_shield_potion", name="Shield Potion", type=ItemType.CONSUMABLE,
            rarity=Rarity.UNCOMMON, stackable=True, max_stack=10,
            stats={"shield": 50}),
    ItemDef(id="mat_scrap", name="Scrap", type=ItemType.MATERIAL,
            rarity=Rarity.COMMON, stackable=True, max_stack=999),
]

# --------------------------------------------------------------------------- #
# Skill trees (Arc Raiders style: spend skill points earned by leveling)      #
# --------------------------------------------------------------------------- #
SKILL_TREES: list[SkillTree] = [
    SkillTree(id="combat", name="Combat", description="Offensive specializations."),
    SkillTree(id="survival", name="Survival", description="Defense and sustain."),
    SkillTree(id="mobility", name="Mobility", description="Speed and traversal."),
]

SKILL_NODES: list[SkillNode] = [
    # Combat
    SkillNode(id="cmb_sharpshooter", name="Sharpshooter", tree="combat",
              description="+5% weapon damage per rank.", max_rank=3,
              bonuses={"weapon_damage_pct": 5}),
    SkillNode(id="cmb_quickhands", name="Quick Hands", tree="combat",
              description="+10% reload speed.", requires=["cmb_sharpshooter"],
              bonuses={"reload_speed_pct": 10}),
    SkillNode(id="cmb_executioner", name="Executioner", tree="combat",
              description="+15% damage to low-health enemies.",
              requires=["cmb_quickhands"], cost=2,
              bonuses={"execute_damage_pct": 15}),
    # Survival
    SkillNode(id="sur_toughness", name="Toughness", tree="survival",
              description="+20 max health per rank.", max_rank=3,
              bonuses={"max_health": 20}),
    SkillNode(id="sur_regen", name="Regeneration", tree="survival",
              description="Regenerate 2 hp/s out of combat.",
              requires=["sur_toughness"], bonuses={"health_regen": 2}),
    # Mobility
    SkillNode(id="mob_sprinter", name="Sprinter", tree="mobility",
              description="+8% sprint speed per rank.", max_rank=2,
              bonuses={"sprint_speed_pct": 8}),
    SkillNode(id="mob_doublejump", name="Double Jump", tree="mobility",
              description="Unlock a second jump.", requires=["mob_sprinter"],
              cost=2, bonuses={"extra_jumps": 1}),
]

# --------------------------------------------------------------------------- #
# Loot tables + world chests                                                  #
# --------------------------------------------------------------------------- #
LOOT_TABLES: list[LootTable] = [
    LootTable(id="lt_common_chest", rolls=2, entries=[
        LootEntry(item_id="wpn_ar_standard", weight=20),
        LootEntry(item_id="wpn_pistol_sidekick", weight=20),
        LootEntry(item_id="gear_helm_scout", weight=15),
        LootEntry(item_id="con_shield_potion", weight=25, min_qty=1, max_qty=3),
        LootEntry(item_id="mat_scrap", weight=20, min_qty=10, max_qty=40),
    ]),
    LootTable(id="lt_rare_chest", rolls=3, entries=[
        LootEntry(item_id="wpn_ar_tactical", weight=15),
        LootEntry(item_id="wpn_smg_hailstorm", weight=8),
        LootEntry(item_id="gear_vest_assault", weight=15),
        LootEntry(item_id="gear_greaves_runner", weight=15),
        LootEntry(item_id="cos_back_jetwing", weight=5),
        LootEntry(item_id="con_shield_potion", weight=22, min_qty=2, max_qty=4),
        LootEntry(item_id="mat_scrap", weight=20, min_qty=30, max_qty=80),
    ]),
    LootTable(id="lt_legendary_vault", rolls=4, entries=[
        LootEntry(item_id="wpn_sniper_phantom", weight=6),
        LootEntry(item_id="wpn_smg_hailstorm", weight=12),
        LootEntry(item_id="cos_skin_neon", weight=4),
        LootEntry(item_id="cos_emote_floss", weight=8),
        LootEntry(item_id="gear_vest_assault", weight=18),
        LootEntry(item_id="con_shield_potion", weight=22, min_qty=3, max_qty=6),
        LootEntry(item_id="mat_scrap", weight=30, min_qty=60, max_qty=150),
    ]),
]

CHESTS: list[ChestDef] = [
    ChestDef(id="chest_riverbed", name="Riverbed Cache", rarity=Rarity.COMMON,
             position={"x": 120.0, "y": 0.0, "z": -40.0},
             loot_table_id="lt_common_chest"),
    ChestDef(id="chest_ruins", name="Hidden Ruins Chest", rarity=Rarity.RARE,
             position={"x": -88.0, "y": 12.0, "z": 210.0},
             loot_table_id="lt_rare_chest"),
    ChestDef(id="chest_summit_vault", name="Summit Vault", rarity=Rarity.LEGENDARY,
             position={"x": 305.0, "y": 64.0, "z": 5.0},
             loot_table_id="lt_legendary_vault"),
]

# --------------------------------------------------------------------------- #
# Quests                                                                      #
# --------------------------------------------------------------------------- #
QUESTS: list[QuestDef] = [
    QuestDef(id="q_first_blood", name="First Blood",
             description="Eliminate 3 enemies.", required_level=1,
             objectives=[QuestObjective(id="kills", description="Eliminate enemies",
                                        event="enemy_killed", count=3)],
             rewards=[Grant(kind=GrantKind.CURRENCY, ref=CurrencyCode.COINS.value,
                            amount=250),
                      Grant(kind=GrantKind.ITEM, ref="con_shield_potion", amount=2)]),
    QuestDef(id="q_treasure_hunter", name="Treasure Hunter",
             description="Open 2 world chests.", required_level=2,
             objectives=[QuestObjective(id="chests", description="Open chests",
                                        event="chest_opened", count=2)],
             rewards=[Grant(kind=GrantKind.ITEM, ref="wpn_ar_tactical", amount=1),
                      Grant(kind=GrantKind.CURRENCY, ref=CurrencyCode.GEMS.value,
                            amount=50)]),
    QuestDef(id="q_legend", name="Legend in the Making",
             description="Reach level 5.", required_level=1,
             objectives=[QuestObjective(id="level", description="Reach level 5",
                                        event="level_reached", target="5", count=1)],
             rewards=[Grant(kind=GrantKind.ITEM, ref="cos_skin_neon", amount=1)]),
]

# --------------------------------------------------------------------------- #
# Microtransaction store                                                      #
# --------------------------------------------------------------------------- #
STORE_LISTINGS: list[StoreListing] = [
    # Real-money gem packs (IAP products).
    StoreListing(id="iap_gems_small", name="Pouch of Gems",
                 description="500 gems.", price_usd=4.99,
                 grants=[Grant(kind=GrantKind.CURRENCY,
                               ref=CurrencyCode.GEMS.value, amount=500)]),
    StoreListing(id="iap_gems_large", name="Chest of Gems",
                 description="2,800 gems (best value).", price_usd=19.99,
                 featured=True,
                 grants=[Grant(kind=GrantKind.CURRENCY,
                               ref=CurrencyCode.GEMS.value, amount=2800)]),
    # Premium cosmetics (bought with gems).
    StoreListing(id="store_skin_neon", name="Neon Striker Skin",
                 description="Epic character skin.",
                 cost_currency=CurrencyCode.GEMS, cost_amount=1200, featured=True,
                 grants=[Grant(kind=GrantKind.ITEM, ref="cos_skin_neon")]),
    StoreListing(id="store_jetwing", name="Jetwing Back Bling",
                 cost_currency=CurrencyCode.GEMS, cost_amount=800,
                 grants=[Grant(kind=GrantKind.ITEM, ref="cos_back_jetwing")]),
    # Coin sinks (bought with earned soft currency).
    StoreListing(id="store_shield_bundle", name="Shield Potion x5",
                 cost_currency=CurrencyCode.COINS, cost_amount=300,
                 grants=[Grant(kind=GrantKind.ITEM, ref="con_shield_potion",
                               amount=5)]),
]

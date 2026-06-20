from __future__ import annotations

import random

import pytest

from app.models import Character, CurrencyCode, Player
from app.services import commerce, economy, loot, quests
from app.state import GameState


def fresh():
    state = GameState()
    player = Player(id="p1", name="Tester",
                    wallet={CurrencyCode.COINS: 1000, CurrencyCode.GEMS: 2000})
    char = Character(id="c1", player_id="p1", name="Hero", level=5)
    state.players[player.id] = player
    state.characters[char.id] = char
    return state, player, char


# --- economy ---------------------------------------------------------------
def test_debit_insufficient_funds():
    _, player, _ = fresh()
    with pytest.raises(economy.EconomyError):
        economy.debit(player, CurrencyCode.GEMS, 999_999)


def test_remove_item_clears_zero_stacks():
    _, player, _ = fresh()
    economy.add_item(player, "mat_scrap", 5)
    economy.remove_item(player, "mat_scrap", 5)
    assert "mat_scrap" not in player.inventory


# --- loot ------------------------------------------------------------------
def test_roll_table_is_deterministic_with_seed():
    state, _, _ = fresh()
    table = state.loot_tables["lt_rare_chest"]
    a = loot.roll_table(table, random.Random(42))
    b = loot.roll_table(table, random.Random(42))
    assert [g.ref for g in a] == [g.ref for g in b]
    assert len(a) == table.rolls


def test_open_chest_grants_and_blocks_reopen():
    state, player, char = fresh()
    grants = loot.open_chest(state, player, char, "chest_riverbed",
                             random.Random(1))
    assert grants
    assert "chest_riverbed" in char.opened_chests
    for g in grants:
        assert player.inventory.get(g.ref, 0) >= g.amount
    with pytest.raises(loot.LootError):
        loot.open_chest(state, player, char, "chest_riverbed")


# --- commerce --------------------------------------------------------------
def test_purchase_with_currency_debits_wallet():
    state, player, _ = fresh()
    before = player.wallet[CurrencyCode.GEMS]
    receipt = commerce.purchase(state, player, "store_jetwing")
    assert player.wallet[CurrencyCode.GEMS] == before - 800
    assert player.inventory.get("cos_back_jetwing") == 1
    assert receipt.paid_amount == 800


def test_iap_requires_payment_token():
    state, player, _ = fresh()
    with pytest.raises(commerce.CommerceError):
        commerce.purchase(state, player, "iap_gems_small")
    receipt = commerce.purchase(state, player, "iap_gems_small",
                                payment_token="tok_123")
    assert receipt.price_usd == 4.99
    assert player.wallet[CurrencyCode.GEMS] >= 500


def test_purchase_unaffordable_raises():
    state, player, _ = fresh()
    player.wallet[CurrencyCode.GEMS] = 0
    with pytest.raises(commerce.CommerceError):
        commerce.purchase(state, player, "store_jetwing")


# --- quests ----------------------------------------------------------------
def test_quest_lifecycle():
    state, player, char = fresh()
    quests.accept_quest(state, char, "q_first_blood")

    completed = quests.track_event(state, char, "enemy_killed", amount=2)
    assert completed == []  # needs 3
    completed = quests.track_event(state, char, "enemy_killed", amount=1)
    assert "q_first_blood" in completed

    coins_before = player.wallet[CurrencyCode.COINS]
    quests.claim_rewards(state, player, char, "q_first_blood")
    assert player.wallet[CurrencyCode.COINS] == coins_before + 250
    assert player.inventory.get("con_shield_potion") == 2

    # Cannot double-claim.
    with pytest.raises(quests.QuestError):
        quests.claim_rewards(state, player, char, "q_first_blood")


def test_quest_level_requirement():
    state, _, char = fresh()
    char.level = 1
    with pytest.raises(quests.QuestError):
        quests.accept_quest(state, char, "q_treasure_hunter")  # needs level 2


def test_quest_targeted_objective():
    state, _, char = fresh()
    quests.accept_quest(state, char, "q_legend")  # reach level 5
    # Wrong target does nothing.
    assert quests.track_event(state, char, "level_reached", target="3") == []
    completed = quests.track_event(state, char, "level_reached", target="5")
    assert "q_legend" in completed

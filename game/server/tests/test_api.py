"""End-to-end API tests covering a full player journey."""

from __future__ import annotations


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_full_player_journey(client):
    # 1. Create a player (gets starting currency).
    r = client.post("/players", json={"name": "Ace"})
    assert r.status_code == 201
    player = r.json()
    pid = player["id"]
    assert player["wallet"]["gems"] == 100

    # 2. Create a character with appearance choices.
    r = client.post("/characters", json={
        "player_id": pid, "name": "Nova",
        "appearance": {"body": "type_b", "hair": "mohawk", "color": "#ff0066"},
    })
    assert r.status_code == 201
    char = r.json()
    cid = char["id"]
    assert char["loadout"]["skin"] == "cos_skin_default"

    # 3. Earn XP and level up.
    r = client.post(f"/characters/{cid}/xp", json={"amount": 5000})
    assert r.status_code == 200
    char = r.json()
    assert char["level"] > 1
    assert char["skill_points"] >= 1

    # 4. Spend a skill point.
    r = client.post(f"/characters/{cid}/skills/cmb_sharpshooter")
    assert r.status_code == 200
    assert r.json()["unlocked_skills"]["cmb_sharpshooter"] == 1

    # 5. Allocate an attribute point.
    r = client.post(f"/characters/{cid}/attributes",
                    json={"code": "might", "points": 1})
    assert r.status_code == 200
    assert r.json()["attributes"]["might"] == 1

    # 6. Open a world chest and receive loot.
    r = client.post("/chests/chest_riverbed/open", json={"character_id": cid})
    assert r.status_code == 200
    assert r.json()["granted"]

    # 7. Top up gems via a real-money pack (billing token), then buy a
    #    cosmetic with gems and equip it.
    r = client.post("/store/iap_gems_large/purchase",
                    json={"player_id": pid, "payment_token": "tok_test"})
    assert r.status_code == 200
    r = client.post("/store/store_jetwing/purchase", json={"player_id": pid})
    assert r.status_code == 200
    r = client.put(f"/characters/{cid}/loadout/back_bling",
                   json={"item_id": "cos_back_jetwing"})
    assert r.status_code == 200
    assert r.json()["loadout"]["back_bling"] == "cos_back_jetwing"


def test_cannot_equip_unowned_item(client):
    pid = client.post("/players", json={"name": "A"}).json()["id"]
    cid = client.post("/characters",
                      json={"player_id": pid, "name": "B"}).json()["id"]
    r = client.put(f"/characters/{cid}/loadout/primary",
                   json={"item_id": "wpn_sniper_phantom"})
    assert r.status_code == 400


def test_cannot_equip_into_wrong_slot(client):
    pid = client.post("/players", json={"name": "A"}).json()["id"]
    cid = client.post("/characters",
                      json={"player_id": pid, "name": "B"}).json()["id"]
    # Grant a weapon by opening a chest until owned... simpler: buy shield bundle
    client.post("/store/store_shield_bundle/purchase", json={"player_id": pid})
    # Shield potion is a consumable with no slot; equipping into primary fails.
    r = client.put(f"/characters/{cid}/loadout/primary",
                   json={"item_id": "con_shield_potion"})
    assert r.status_code == 400


def test_quest_flow_via_api(client):
    pid = client.post("/players", json={"name": "Q"}).json()["id"]
    cid = client.post("/characters",
                      json={"player_id": pid, "name": "Quester"}).json()["id"]

    r = client.post("/quests/q_first_blood/accept", json={"character_id": cid})
    assert r.status_code == 200

    r = client.post("/quests/events", json={
        "character_id": cid, "event": "enemy_killed", "amount": 3,
    })
    assert "q_first_blood" in r.json()

    coins_before = client.get(f"/players/{pid}").json()["wallet"]["coins"]
    r = client.post("/quests/q_first_blood/claim", json={"character_id": cid})
    assert r.status_code == 200
    coins_after = client.get(f"/players/{pid}").json()["wallet"]["coins"]
    assert coins_after == coins_before + 250


def test_store_listing_and_catalog(client):
    assert len(client.get("/store").json()) > 0
    assert len(client.get("/catalog/items").json()) > 0
    assert len(client.get("/catalog/skill-nodes").json()) > 0
    assert len(client.get("/chests").json()) == 3

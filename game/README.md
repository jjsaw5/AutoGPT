# Mobile Game (working title)

A third-person shooter prototype with Fortnite-style movement, character
progression and skill trees (Arc Raiders style), a microtransaction store,
world chests, and quests.

This folder is the start of the project. It is **separate** from the rest of
the repository.

## What's here

```
game/
├── server/   # Python + FastAPI backend (engine-agnostic game systems)
└── client/   # Godot 4 third-person prototype you can walk around in
```

### Why it's split this way

A live game like this has two very different halves:

| Half | Needs | Status |
|------|-------|--------|
| **Backend / "meta" systems** — store, inventory, progression, skill trees, quests, loot | Pure logic + data. No art, no physics. | ✅ Built & tested here (`server/`) |
| **Gameplay / rendering** — 3D world, third-person physics, shooting, animation | A game engine + 3D art + animation. | 🟡 Playable combat prototype in Godot (`client/`): move/shoot/enemies/HUD; needs art + polish |

The honest scope note: a full Fortnite-quality shooter is a large, multi-person,
multi-year effort. What we've done is build the **foundation that's actually
buildable as code today** and a **runnable engine scaffold** so you can see a
character move. Everything in `server/` is engine-agnostic, so it works whether
you finish the game in Godot, Unity, or Unreal.

## How the features map

| Your feature | Where it lives |
|--------------|----------------|
| 1. Microtransaction store | `server` → `/store` (gem packs via IAP + cosmetics) |
| 2. Hidden chests with loadouts | `server` → `/chests` + `client` chest pickups |
| 3. Character creation + equip gear/cosmetics | `server` → `/characters` loadout slots |
| 4. Fortnite-like physics | `client` → `scripts/Player.gd` (run/sprint/jump) |
| 5. Skill trees + attribute points | `server` → `/characters/.../skills`, `.../attributes` |
| 6. Third-person shooter | `client` → camera rig + hitscan combat, enemies, HUD |
| 7. Quests → XP / weapons / skins | `server` → `/quests` |

## Quick start

**Backend:**
```bash
cd game/server
./run.sh                      # installs deps + starts the API
# open http://localhost:8000/docs to try every endpoint
```
Run the tests: `cd game/server && python3 -m pytest`

**Client:** install [Godot 4.2+](https://godotengine.org), open the
`game/client` folder, press Play, and walk around with WASD + mouse. See
`client/README.md`.

## Suggested next steps

1. **Persistence** — swap the in-memory `GameState` for a database (Postgres).
2. **Accounts/auth** — add real login so wallets and inventories are secure.
3. **Server-authoritative gameplay** — never trust the client for XP, loot, or
   purchases (the structure already keeps that logic on the server).
4. **Art & animation** — replace the Godot capsule with a rigged character.
5. **Shooting & combat** — add weapons, hitscan/projectiles, health/shields.
6. **Networking** — multiplayer is its own large milestone; plan it early.

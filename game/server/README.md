# Game Backend (FastAPI)

Engine-agnostic backend for the game's "meta" systems. No game engine, art, or
physics here — just the logic and data that any client (Godot/Unity/Unreal)
talks to over HTTP.

## Run

```bash
cd game/server
./run.sh
# or manually:
python3 -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open **http://localhost:8000/docs** for interactive Swagger docs where you can
exercise every endpoint.

## Test

```bash
python3 -m pytest
```

## Layout

```
app/
├── models.py        # domain models (items, character, quests, ...)
├── content.py       # authored game data (items, skill trees, quests, store)
├── state.py         # in-memory store (swap for a DB later)
├── services/        # pure game logic (unit-tested, no FastAPI)
│   ├── economy.py       # wallet + inventory + grants
│   ├── progression.py   # XP, leveling, attributes, skill trees
│   ├── loot.py          # loot tables + world chests
│   ├── quests.py        # quest acceptance/progress/rewards
│   └── commerce.py      # microtransaction purchases
├── routers/         # HTTP endpoints (thin wrappers over services)
└── main.py          # FastAPI app
tests/               # unit + end-to-end API tests
```

## API tour

| Area | Endpoints |
|------|-----------|
| Players | `POST /players`, `GET /players/{id}` |
| Characters | `POST /characters`, `POST /characters/{id}/xp`, `POST /characters/{id}/attributes`, `POST /characters/{id}/skills/{node}`, `PUT /characters/{id}/loadout/{slot}` |
| Store | `GET /store`, `POST /store/{listing}/purchase` |
| Chests | `GET /chests`, `POST /chests/{id}/open` |
| Quests | `GET /quests`, `POST /quests/{id}/accept`, `POST /quests/events`, `POST /quests/{id}/claim` |
| Catalog | `GET /catalog/items`, `GET /catalog/skill-nodes`, `GET /catalog/attributes` |

## Design notes

- **Server-authoritative by design.** XP gain, loot rolls, purchases and
  rewards are all computed server-side. A real game must never trust the client
  for these.
- **In-memory state is a placeholder.** `state.py` is the single seam to replace
  with a real database; game logic in `services/` won't change.
- **Real-money purchases** (`price_usd` listings) require a `payment_token`,
  standing in for App Store / Google Play receipt validation.
- **Balance lives in `content.py`** — tweak items, drop rates, XP curve, prices,
  skill bonuses and quests there.

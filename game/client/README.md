# Game Client (Godot 4 prototype)

A minimal third-person scaffold so you can *see and feel* the character move.
It is intentionally placeholder art (a capsule + boxes) — the point is a working
camera/movement rig and backend hookup you can build a real game on top of.

## Run it

1. Install [Godot **4.2+**](https://godotengine.org/download) (the standard
   build; no C# needed).
2. Open Godot → **Import** → select this `game/client` folder.
3. Press **Play** (F5).

## Controls

| Action | Input |
|--------|-------|
| Move | `W A S D` |
| Look | Mouse |
| Sprint | `Shift` |
| Jump | `Space` (double-jump unlocks via the Mobility skill — raise `max_jumps`) |
| Open chest | Walk into a box, press `E` |
| Free the mouse | `Esc` |

## What's in here

```
scenes/
├── World.tscn   # ground, light, the player, three chests
├── Player.tscn  # CharacterBody3D + third-person SpringArm camera
└── Chest.tscn   # walk-in trigger that "opens"
scripts/
├── Player.gd    # run / sprint / jump / mouse-look controller
├── Chest.gd     # chest interaction (+ optional backend call)
└── ApiClient.gd # HTTP client for the FastAPI backend
```

## Connecting to the backend

1. Start the backend (`cd ../server && ./run.sh`).
2. In Godot: **Project → Project Settings → Autoload**, add
   `res://scripts/ApiClient.gd` with the name **`Api`**.
3. Now any script can call e.g.
   `Api.open_chest(character_id, "chest_riverbed", func(r): print(r.data))`.

> Note: the camera transform and look sensitivity are rough defaults — tweak
> `mouse_sensitivity` in `Player.gd` (and flip its sign if pitch feels
> inverted). This is a starting point, not a finished feel.

## Honest status

This is a **prototype scaffold**, not a game. Missing (and each is real work):
shooting/weapons, health & combat, enemies/AI, animation, real 3D models,
a proper level, UI/HUD, and networking for multiplayer.

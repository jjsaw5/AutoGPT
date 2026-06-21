# Game Client (Godot 4 prototype)

A third-person prototype so you can *see and feel* the game: move, shoot, take
damage, and fight enemies. It's intentionally placeholder art (capsules + boxes)
— the point is a working movement/camera/combat rig and backend hookup you can
build a real game on top of.

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
| **Fire** | **Left mouse** (hold for auto) |
| **Reload** | **`R`** |
| Open chest | Walk into a box, press `E` |
| Free / recapture mouse | `Esc` / left-click |

The three red capsules are enemies: they chase you, melee you in range, and die
when you shoot them down. Each kill bumps the on-screen counter and (when the
backend is connected) progresses the "First Blood" quest.

## What's in here

```
scenes/
├── World.tscn   # ground, light, player, chests, enemies, HUD
├── Player.tscn  # CharacterBody3D + camera + Health + Weapon
├── Enemy.tscn   # chasing melee enemy with a Health component
├── Chest.tscn   # walk-in trigger that "opens"
└── HUD.tscn     # crosshair, health/shield bars, ammo, kills
scripts/
├── Player.gd       # run / sprint / jump / look + firing
├── Weapon.gd       # hitscan shooting, ammo, reload (stats mirror the backend)
├── Health.gd       # reusable health + shield component
├── Enemy.gd        # chase + melee AI, reports kills on death
├── Chest.gd        # chest interaction
├── HUD.gd          # binds the HUD to the player's Health/Weapon
├── GameSession.gd  # autoload: session ids + forwards kills to the backend
└── ApiClient.gd    # autoload ("Api"): HTTP client for the FastAPI backend
```

### How combat fits together

- **Weapon** raycasts from the camera centre each shot; if it hits a node in the
  `enemy` group it calls `take_damage()` on that enemy's **Health** child.
- **Health** absorbs damage into shields first, then health, and emits `died`.
- **Enemy** chases the player, melees in range, and on `died` reports an
  `enemy_killed` event through **GameSession** → the backend quest system.
- **HUD** subscribes to the player's Health/Weapon signals to draw bars + ammo.
- Weapon stats (`damage`, `fire_rate`, `max_range`, `mag_size`) intentionally
  mirror the backend item stats in `game/server/app/content.py`, so a real game
  can drive the equipped weapon straight from the loadout the API returns.

## Connecting to the backend

`ApiClient` and `GameSession` are already registered as autoloads (`Api` /
`GameSession`) in `project.godot`, so no manual setup is needed. To light up the
backend-driven features:

1. Start the backend (`cd ../server && ./run.sh`).
2. Set the session ids once the player/character exist, e.g. from a menu script:
   ```gdscript
   Api.create_player("Ace", func(r):
       GameSession.player_id = r.data.id
       Api.create_character(r.data.id, "Nova", {}, func(c):
           GameSession.character_id = c.data.id))
   ```
3. Kills now POST to `/quests/events`; chests can call `Api.open_chest(...)`.

Everything degrades to a safe no-op if the backend isn't running, so the game is
fully playable offline.

> Note: camera offset and `mouse_sensitivity` (in `Player.gd`) are rough
> defaults — tweak in-editor. Flip the sensitivity sign if pitch feels inverted.

## Honest status

This is a **playable combat prototype**, not a finished game. Hitscan combat,
health/shields, basic enemy AI and a HUD work. Still real work ahead: animation
and real 3D models, weapon variety driven by the loadout, projectile/recoil
feel, enemy navigation (NavMesh) and spawning, sound, polish, and networking for
multiplayer.

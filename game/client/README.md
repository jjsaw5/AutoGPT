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

Enemies (red capsules) arrive in **escalating waves**: they spawn on a ring
around you, chase, melee in range, and die when shot down. Clear a wave and the
next — larger — one spawns after a short intermission. Each kill bumps the
counter and (when the backend is connected) progresses the "First Blood" quest.

## What's in here

```
scenes/
├── World.tscn   # ground, light, player, chests, wave spawner, HUD
├── Player.tscn  # CharacterBody3D + camera + Health + Weapon
├── Enemy.tscn   # chasing melee enemy with a Health component
├── Chest.tscn   # walk-in trigger that "opens"
└── HUD.tscn     # crosshair, bars, ammo, kills, wave + banner
scripts/
├── Player.gd       # run / sprint / jump / look + firing
├── Weapon.gd       # hitscan shooting, ammo, reload (stats mirror the backend)
├── Health.gd       # reusable health + shield component
├── Enemy.gd        # chase + melee AI, reports kills on death
├── WaveSpawner.gd  # escalating waves, intermissions, spawn placement
├── Chest.gd        # chest interaction
├── HUD.gd          # binds the HUD to Health/Weapon/WaveSpawner
├── GameSession.gd  # autoload: session ids + forwards kills to the backend
└── ApiClient.gd    # autoload ("Api"): HTTP client for the FastAPI backend
```

### Waves

`WaveSpawner.gd` (the `WaveSpawner` node in `World.tscn`) drives spawning. All
knobs are exported and editable in the Inspector:

| Property | Default | Meaning |
|----------|---------|---------|
| `base_enemies` | 3 | enemies in wave 1 |
| `enemies_per_wave` | 2 | extra enemies added each wave |
| `max_enemies_per_wave` | 20 | cap so late waves stay sane |
| `initial_delay` / `time_between_waves` | 2s / 4s | intermission timing |
| `spawn_radius_min/max` | 16–28 | ring distance from the player |
| `max_waves` | 0 | `0` = endless; set N for a fixed run |

Add `Marker3D` children to the spawner to use fixed spawn points instead of the
ring. The HUD shows the current wave, enemies remaining, and a wave banner.

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
health/shields, basic enemy AI, escalating waves and a HUD work. Still real work
ahead: animation and real 3D models, weapon variety driven by the loadout,
projectile/recoil feel, smarter enemy navigation (NavMesh), sound, polish, and
networking for multiplayer.

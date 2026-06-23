extends Node3D
class_name WaveSpawner
## Spawns enemies in escalating waves. When a wave is cleared it waits
## `time_between_waves` seconds, then spawns a larger wave. Endless by default.
##
## Spawn placement: if this node has Marker3D children they're used as spawn
## points; otherwise enemies spawn on a ring around the player.

signal wave_started(wave: int, count: int)
signal wave_cleared(wave: int)
signal enemies_remaining_changed(remaining: int)
signal all_waves_cleared

enum State { IDLE, INTERMISSION, ACTIVE }

@export var enemy_scene: PackedScene
@export var base_enemies: int = 3        ## enemies in wave 1
@export var enemies_per_wave: int = 2    ## extra enemies each subsequent wave
@export var max_enemies_per_wave: int = 20
@export var initial_delay: float = 2.0
@export var time_between_waves: float = 4.0
@export var spawn_radius_min: float = 16.0
@export var spawn_radius_max: float = 28.0
@export var max_waves: int = 0           ## 0 = endless
@export var auto_start: bool = true

var current_wave: int = 0
var _alive: int = 0
var _state: int = State.IDLE
var _intermission: float = 0.0
var _spawn_points: Array[Node3D] = []
var _player: Node3D


func _ready() -> void:
	add_to_group("wave_spawner")
	for child in get_children():
		if child is Marker3D:
			_spawn_points.append(child)
	if auto_start:
		# Deferred so the player and HUD are in the tree first.
		start.call_deferred()


func start() -> void:
	_player = get_tree().get_first_node_in_group("player") as Node3D
	current_wave = 0
	_alive = 0
	_state = State.INTERMISSION
	_intermission = initial_delay


func _process(delta: float) -> void:
	if _state != State.INTERMISSION:
		return
	_intermission -= delta
	if _intermission <= 0.0:
		_start_next_wave()


func _start_next_wave() -> void:
	current_wave += 1
	if max_waves > 0 and current_wave > max_waves:
		_state = State.IDLE
		all_waves_cleared.emit()
		return

	var count := mini(
		base_enemies + (current_wave - 1) * enemies_per_wave,
		max_enemies_per_wave
	)
	_state = State.ACTIVE
	for i in count:
		_spawn_one()
	wave_started.emit(current_wave, count)
	enemies_remaining_changed.emit(_alive)

	# Safety: if nothing actually spawned, don't stall — roll into intermission.
	if _alive == 0:
		_state = State.INTERMISSION
		_intermission = time_between_waves
		wave_cleared.emit(current_wave)


func _spawn_one() -> void:
	if enemy_scene == null:
		push_warning("WaveSpawner has no enemy_scene assigned")
		return
	var enemy := enemy_scene.instantiate()
	add_child(enemy)
	var spatial := enemy as Node3D
	if spatial:
		spatial.global_position = _pick_spawn_position()
	enemy.tree_exited.connect(_on_enemy_removed)
	_alive += 1


func _pick_spawn_position() -> Vector3:
	if not _spawn_points.is_empty():
		var marker: Node3D = _spawn_points[randi() % _spawn_points.size()]
		return marker.global_position

	var center := _player.global_position if _player else global_position
	var angle := randf() * TAU
	var dist := randf_range(spawn_radius_min, spawn_radius_max)
	return center + Vector3(cos(angle) * dist, 1.0, sin(angle) * dist)


func _on_enemy_removed() -> void:
	_alive = max(0, _alive - 1)
	enemies_remaining_changed.emit(_alive)
	if _alive == 0 and _state == State.ACTIVE:
		_state = State.INTERMISSION
		_intermission = time_between_waves
		wave_cleared.emit(current_wave)

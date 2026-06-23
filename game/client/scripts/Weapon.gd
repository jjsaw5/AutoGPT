extends Node3D
class_name Weapon
## Hitscan weapon. Stats mirror the backend item definitions
## (game/server/app/content.py) so a real game can drive these from the
## equipped loadout returned by the API.

signal ammo_changed(ammo: int, mag_size: int)
signal fired
signal reloading
signal hit(target: Node, amount: float)

@export var damage: float = 24.0
@export var fire_rate: float = 7.0      # shots per second
@export var max_range: float = 60.0
@export var mag_size: int = 30
@export var reload_time: float = 1.8
@export var auto: bool = true           # hold-to-fire

var ammo: int
var _cooldown: float = 0.0
var _reload_timer: float = 0.0
var _reloading: bool = false


func _ready() -> void:
	ammo = mag_size


func _process(delta: float) -> void:
	if _cooldown > 0.0:
		_cooldown -= delta
	if _reloading:
		_reload_timer -= delta
		if _reload_timer <= 0.0:
			_finish_reload()


func can_fire() -> bool:
	return not _reloading and _cooldown <= 0.0 and ammo > 0


## Attempt to fire toward the centre of `camera`'s view. `shooter` is excluded
## from the hitscan so a player never shoots themselves.
func try_fire(camera: Camera3D, shooter: Node3D) -> void:
	if not can_fire():
		if ammo <= 0 and not _reloading:
			start_reload()
		return

	_cooldown = 1.0 / fire_rate
	ammo -= 1
	ammo_changed.emit(ammo, mag_size)
	fired.emit()

	var space := camera.get_world_3d().direct_space_state
	var from := camera.global_position
	var to := from + (-camera.global_transform.basis.z) * max_range
	var query := PhysicsRayQueryParameters3D.create(from, to)
	query.collide_with_areas = false
	if shooter is CollisionObject3D:
		query.exclude = [shooter.get_rid()]

	var result := space.intersect_ray(query)
	if result.is_empty():
		return

	var collider := result.get("collider") as Node
	if collider and collider.is_in_group("enemy"):
		var hp := collider.get_node_or_null("Health") as Health
		if hp:
			hp.take_damage(damage)
			hit.emit(collider, damage)


func start_reload() -> void:
	if _reloading or ammo == mag_size:
		return
	_reloading = true
	_reload_timer = reload_time
	reloading.emit()


func _finish_reload() -> void:
	_reloading = false
	ammo = mag_size
	ammo_changed.emit(ammo, mag_size)

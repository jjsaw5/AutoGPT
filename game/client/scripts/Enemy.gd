extends CharacterBody3D
class_name Enemy
## Simple melee enemy: chases the player, attacks in range, dies when its
## Health hits zero. On death it reports an "enemy_killed" event so backend
## quests (e.g. "First Blood") can progress.

@export var move_speed: float = 3.5
@export var attack_range: float = 2.2
@export var attack_damage: float = 8.0
@export var attack_interval: float = 1.0

var _attack_cooldown: float = 0.0
var _gravity: float = ProjectSettings.get_setting("physics/3d/default_gravity", 9.8)

@onready var _health: Health = $Health
var _player: Node3D


func _ready() -> void:
	add_to_group("enemy")
	_health.died.connect(_on_died)
	_player = get_tree().get_first_node_in_group("player")


func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y -= _gravity * delta
	else:
		velocity.y = 0.0

	if _attack_cooldown > 0.0:
		_attack_cooldown -= delta

	if _player == null or not is_instance_valid(_player):
		_player = get_tree().get_first_node_in_group("player")

	if _player:
		var to_player := _player.global_position - global_position
		to_player.y = 0.0
		var distance := to_player.length()

		if distance > attack_range:
			var dir := to_player.normalized()
			velocity.x = dir.x * move_speed
			velocity.z = dir.z * move_speed
			_face(_player.global_position)
		else:
			velocity.x = 0.0
			velocity.z = 0.0
			_try_attack()

	move_and_slide()


func _try_attack() -> void:
	if _attack_cooldown > 0.0:
		return
	_attack_cooldown = attack_interval
	var hp := _player.get_node_or_null("Health")
	if hp:
		hp.take_damage(attack_damage)


func _face(target: Vector3) -> void:
	var flat := Vector3(target.x, global_position.y, target.z)
	if global_position.distance_to(flat) > 0.05:
		look_at(flat, Vector3.UP)


func _on_died() -> void:
	var session := get_node_or_null("/root/GameSession")
	if session and session.has_method("report_kill"):
		session.report_kill()
	queue_free()

extends Node
class_name Health
## Reusable health + shield component. Attach as a child named "Health" to any
## entity (the player, enemies). Shields absorb damage before health.

signal health_changed(health: float, max_health: float)
signal shield_changed(shield: float, max_shield: float)
signal damaged(amount: float)
signal died

@export var max_health: float = 100.0
@export var max_shield: float = 0.0

var health: float
var shield: float
var _dead: bool = false


func _ready() -> void:
	health = max_health
	shield = max_shield


func is_dead() -> bool:
	return _dead


func take_damage(amount: float) -> void:
	if _dead or amount <= 0.0:
		return

	var remaining := amount
	if shield > 0.0:
		var absorbed: float = min(shield, remaining)
		shield -= absorbed
		remaining -= absorbed
		shield_changed.emit(shield, max_shield)

	if remaining > 0.0:
		health = max(0.0, health - remaining)
		health_changed.emit(health, max_health)

	damaged.emit(amount)

	if health <= 0.0:
		_dead = true
		died.emit()


func revive() -> void:
	_dead = false
	health = max_health
	shield = max_shield
	health_changed.emit(health, max_health)
	shield_changed.emit(shield, max_shield)


func heal(amount: float) -> void:
	if _dead or amount <= 0.0:
		return
	health = min(max_health, health + amount)
	health_changed.emit(health, max_health)


func add_shield(amount: float) -> void:
	if _dead or amount <= 0.0:
		return
	shield = min(max_shield, shield + amount)
	shield_changed.emit(shield, max_shield)

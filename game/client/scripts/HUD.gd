extends CanvasLayer
## Combat HUD: health/shield bars, ammo counter, kill count. Finds the player
## by group and subscribes to its Health and Weapon components.

@onready var _health_bar: ProgressBar = $HealthBar
@onready var _shield_bar: ProgressBar = $ShieldBar
@onready var _ammo_label: Label = $AmmoLabel
@onready var _kills_label: Label = $KillsLabel


func _ready() -> void:
	var player := get_tree().get_first_node_in_group("player")
	if player:
		var hp: Health = player.get_node_or_null("Health")
		if hp:
			hp.health_changed.connect(_on_health_changed)
			hp.shield_changed.connect(_on_shield_changed)
			_on_health_changed(hp.health, hp.max_health)
			_on_shield_changed(hp.shield, hp.max_shield)

		var weapon: Weapon = player.get_node_or_null("Weapon")
		if weapon:
			weapon.ammo_changed.connect(_on_ammo_changed)
			weapon.reloading.connect(func(): _ammo_label.text = "RELOADING")
			_on_ammo_changed(weapon.ammo, weapon.mag_size)

	var session := get_node_or_null("/root/GameSession")
	if session and session.has_signal("kills_changed"):
		session.kills_changed.connect(_on_kills_changed)
		_on_kills_changed(session.kills)


func _on_health_changed(health: float, max_health: float) -> void:
	_health_bar.max_value = max_health
	_health_bar.value = health


func _on_shield_changed(shield: float, max_shield: float) -> void:
	_shield_bar.max_value = max(1.0, max_shield)
	_shield_bar.value = shield


func _on_ammo_changed(ammo: int, mag_size: int) -> void:
	_ammo_label.text = "%d / %d" % [ammo, mag_size]


func _on_kills_changed(kills: int) -> void:
	_kills_label.text = "Kills: %d" % kills

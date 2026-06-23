extends CanvasLayer
## Combat HUD: health/shield bars, ammo, kills, and wave status. Finds the
## player and wave spawner by group and subscribes to their signals.

@onready var _health_bar: ProgressBar = $HealthBar
@onready var _shield_bar: ProgressBar = $ShieldBar
@onready var _ammo_label: Label = $AmmoLabel
@onready var _kills_label: Label = $KillsLabel
@onready var _wave_label: Label = $WaveLabel
@onready var _enemies_label: Label = $EnemiesLabel
@onready var _banner: Label = $Banner


func _ready() -> void:
	_banner.visible = false

	var player := get_tree().get_first_node_in_group("player")
	if player:
		var hp := player.get_node_or_null("Health") as Health
		if hp:
			hp.health_changed.connect(_on_health_changed)
			hp.shield_changed.connect(_on_shield_changed)
			_on_health_changed(hp.health, hp.max_health)
			_on_shield_changed(hp.shield, hp.max_shield)

		var weapon := player.get_node_or_null("Weapon") as Weapon
		if weapon:
			weapon.ammo_changed.connect(_on_ammo_changed)
			weapon.reloading.connect(func(): _ammo_label.text = "RELOADING")
			_on_ammo_changed(weapon.ammo, weapon.mag_size)

	# GameSession is an autoload (always present).
	GameSession.kills_changed.connect(_on_kills_changed)
	_on_kills_changed(GameSession.kills)

	var spawner := get_tree().get_first_node_in_group("wave_spawner") as WaveSpawner
	if spawner:
		spawner.wave_started.connect(_on_wave_started)
		spawner.wave_cleared.connect(_on_wave_cleared)
		spawner.enemies_remaining_changed.connect(_on_enemies_remaining)
		spawner.all_waves_cleared.connect(_on_all_waves_cleared)


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


func _on_wave_started(wave: int, count: int) -> void:
	_wave_label.text = "Wave %d" % wave
	_enemies_label.text = "Enemies: %d" % count
	_flash_banner("WAVE %d" % wave)


func _on_wave_cleared(wave: int) -> void:
	_enemies_label.text = "Enemies: 0"
	_flash_banner("Wave %d cleared!" % wave)


func _on_enemies_remaining(remaining: int) -> void:
	_enemies_label.text = "Enemies: %d" % remaining


func _on_all_waves_cleared() -> void:
	_flash_banner("VICTORY")


func _flash_banner(text: String, seconds: float = 1.6) -> void:
	_banner.text = text
	_banner.visible = true
	await get_tree().create_timer(seconds).timeout
	# Only hide if no newer banner replaced this one.
	if _banner.text == text:
		_banner.visible = false

extends Area3D
## A world chest placeholder. Walk into it and press [E] to "open" it.
##
## When the backend is running and ApiClient is wired up, opening calls
## POST /chests/{id}/open and prints the loot. Without a backend it just
## logs locally so the scene is playable standalone.

@export var chest_id: String = "chest_riverbed"

var _player_in_range: bool = false
var _opened: bool = false


func _ready() -> void:
	body_entered.connect(func(b): if b.is_in_group("player"): _player_in_range = true)
	body_exited.connect(func(b): if b.is_in_group("player"): _player_in_range = false)


func _unhandled_input(event: InputEvent) -> void:
	if _opened or not _player_in_range:
		return
	if event is InputEventKey and event.pressed and event.keycode == KEY_E:
		_open()


func _open() -> void:
	_opened = true
	$Mesh.visible = false  # simple "opened" feedback
	print("Opened chest: ", chest_id)
	# Example backend hook (requires the "Api" autoload + a character id):
	# Api.open_chest(current_character_id, chest_id, func(r): print("Loot: ", r.data))

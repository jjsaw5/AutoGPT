extends Node
## Thin HTTP client for the FastAPI game backend (game/server).
##
## Autoload this (Project Settings > Autoload) as "Api" and call e.g.:
##     Api.open_chest(character_id, "chest_riverbed", func(result): print(result))
##
## All calls are async; pass a Callable that receives the parsed JSON.

@export var base_url: String = "http://127.0.0.1:8000"


func _request(method: int, path: String, body: Dictionary, on_done: Callable) -> void:
	var http := HTTPRequest.new()
	add_child(http)
	http.request_completed.connect(
		func(_result, code, _headers, data):
			var parsed = JSON.parse_string(data.get_string_from_utf8())
			if on_done.is_valid():
				on_done.call({"code": code, "data": parsed})
			http.queue_free()
	)
	var headers := ["Content-Type: application/json"]
	var payload := JSON.stringify(body) if not body.is_empty() else ""
	http.request(base_url + path, headers, method, payload)


func create_player(name: String, on_done: Callable) -> void:
	_request(HTTPClient.METHOD_POST, "/players", {"name": name}, on_done)


func create_character(player_id: String, name: String, appearance: Dictionary, on_done: Callable) -> void:
	_request(HTTPClient.METHOD_POST, "/characters",
		{"player_id": player_id, "name": name, "appearance": appearance}, on_done)


func list_chests(on_done: Callable) -> void:
	_request(HTTPClient.METHOD_GET, "/chests", {}, on_done)


func open_chest(character_id: String, chest_id: String, on_done: Callable) -> void:
	_request(HTTPClient.METHOD_POST, "/chests/%s/open" % chest_id,
		{"character_id": character_id}, on_done)


func add_xp(character_id: String, amount: int, on_done: Callable) -> void:
	_request(HTTPClient.METHOD_POST, "/characters/%s/xp" % character_id,
		{"amount": amount}, on_done)


func list_store(on_done: Callable) -> void:
	_request(HTTPClient.METHOD_GET, "/store", {}, on_done)

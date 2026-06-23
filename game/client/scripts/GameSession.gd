extends Node
## Autoloaded session state + optional backend bridge.
##
## Holds the ids for the current player/character and forwards gameplay events
## (like kills) to the backend quest system when available. Everything degrades
## to a safe no-op if the backend isn't running or ids aren't set, so the game
## is fully playable offline.

signal kills_changed(kills: int)

var player_id: String = ""
var character_id: String = ""
var kills: int = 0


func report_kill() -> void:
	kills += 1
	kills_changed.emit(kills)

	# Api is an autoload; only call out when we have a character to attribute to.
	if character_id != "":
		Api.report_event(character_id, "enemy_killed", func(_r): pass)

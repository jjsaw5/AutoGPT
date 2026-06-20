"""Shared router dependencies and lookup helpers."""

from __future__ import annotations

from fastapi import Depends, HTTPException
from typing import Annotated

from ..models import Character, Player
from ..state import GameState, get_state

StateDep = Annotated[GameState, Depends(get_state)]


def get_player(state: GameState, player_id: str) -> Player:
    player = state.players.get(player_id)
    if player is None:
        raise HTTPException(status_code=404, detail=f"player '{player_id}' not found")
    return player


def get_character(state: GameState, character_id: str) -> Character:
    character = state.characters.get(character_id)
    if character is None:
        raise HTTPException(
            status_code=404, detail=f"character '{character_id}' not found"
        )
    return character

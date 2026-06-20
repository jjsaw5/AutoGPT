"""World chests: discover locations and open them for loadout loot."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..models import ChestDef, Grant
from ..services import loot
from .deps import StateDep, get_character, get_player

router = APIRouter(prefix="/chests", tags=["chests"])


class OpenChestRequest(BaseModel):
    character_id: str


class OpenChestResponse(BaseModel):
    chest_id: str
    granted: list[Grant]


@router.get("", response_model=list[ChestDef])
def list_chests(state: StateDep) -> list[ChestDef]:
    """All chest spawn points in the world (client renders them on the map)."""
    return list(state.chests.values())


@router.post("/{chest_id}/open", response_model=OpenChestResponse)
def open_chest(chest_id: str, body: OpenChestRequest, state: StateDep) -> OpenChestResponse:
    character = get_character(state, body.character_id)
    player = get_player(state, character.player_id)
    try:
        grants = loot.open_chest(state, player, character, chest_id)
    except loot.LootError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Opening chests progresses "treasure hunter" style quests.
    from ..services import quests

    quests.track_event(state, character, "chest_opened")
    return OpenChestResponse(chest_id=chest_id, granted=grants)

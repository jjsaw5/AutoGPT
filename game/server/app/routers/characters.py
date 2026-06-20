"""Character creation, customization, equipping, and progression."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..models import Character, EquipSlot
from ..services import progression
from .deps import StateDep, get_character, get_player

router = APIRouter(prefix="/characters", tags=["characters"])


class CreateCharacterRequest(BaseModel):
    player_id: str
    name: str
    appearance: dict[str, str] = {}


class AddXpRequest(BaseModel):
    amount: int


class AllocateAttributeRequest(BaseModel):
    code: str
    points: int = 1


class EquipRequest(BaseModel):
    item_id: str


@router.post("", response_model=Character, status_code=201)
def create_character(body: CreateCharacterRequest, state: StateDep) -> Character:
    get_player(state, body.player_id)  # validates the player exists
    character = Character(
        id=state.next_id("char"),
        player_id=body.player_id,
        name=body.name,
        appearance=body.appearance,
        # Everyone starts with the default cosmetic skin equipped.
        loadout={EquipSlot.SKIN: "cos_skin_default"},
    )
    state.characters[character.id] = character
    return character


@router.get("/{character_id}", response_model=Character)
def get_character_route(character_id: str, state: StateDep) -> Character:
    return get_character(state, character_id)


@router.post("/{character_id}/xp", response_model=Character)
def add_xp(character_id: str, body: AddXpRequest, state: StateDep) -> Character:
    character = get_character(state, character_id)
    try:
        levels = progression.add_xp(character, body.amount)
    except progression.ProgressionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Leveling up can complete "reach level N" quests.
    from ..services import quests

    for lvl in levels:
        quests.track_event(state, character, "level_reached", target=str(lvl))
    return character


@router.post("/{character_id}/attributes", response_model=Character)
def allocate_attribute(
    character_id: str, body: AllocateAttributeRequest, state: StateDep
) -> Character:
    character = get_character(state, character_id)
    try:
        progression.allocate_attribute(character, body.code, body.points)
    except progression.ProgressionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return character


@router.post("/{character_id}/skills/{node_id}", response_model=Character)
def unlock_skill(character_id: str, node_id: str, state: StateDep) -> Character:
    character = get_character(state, character_id)
    try:
        progression.unlock_skill(state, character, node_id)
    except progression.ProgressionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return character


@router.get("/{character_id}/bonuses")
def get_bonuses(character_id: str, state: StateDep) -> dict[str, float]:
    character = get_character(state, character_id)
    return progression.effective_bonuses(state, character)


@router.put("/{character_id}/loadout/{slot}", response_model=Character)
def equip(
    character_id: str, slot: EquipSlot, body: EquipRequest, state: StateDep
) -> Character:
    character = get_character(state, character_id)
    player = get_player(state, character.player_id)

    if player.inventory.get(body.item_id, 0) < 1:
        raise HTTPException(status_code=400, detail="player does not own this item")

    item = state.items.get(body.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="unknown item")
    if item.slot != slot:
        raise HTTPException(
            status_code=400,
            detail=f"'{item.name}' cannot be equipped in the {slot.value} slot",
        )
    character.loadout[slot] = body.item_id
    return character


@router.delete("/{character_id}/loadout/{slot}", response_model=Character)
def unequip(character_id: str, slot: EquipSlot, state: StateDep) -> Character:
    character = get_character(state, character_id)
    character.loadout.pop(slot, None)
    return character

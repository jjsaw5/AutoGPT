"""Quests: browse, accept, report progress events, and claim rewards."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..models import Grant, PlayerQuest, QuestDef
from ..services import quests as quest_svc
from .deps import StateDep, get_character, get_player

router = APIRouter(prefix="/quests", tags=["quests"])


class AcceptRequest(BaseModel):
    character_id: str


class EventRequest(BaseModel):
    character_id: str
    event: str
    target: str | None = None
    amount: int = 1


class ClaimResponse(BaseModel):
    quest_id: str
    granted: list[Grant]


@router.get("", response_model=list[QuestDef])
def list_quests(state: StateDep) -> list[QuestDef]:
    return list(state.quests.values())


@router.post("/{quest_id}/accept", response_model=PlayerQuest)
def accept(quest_id: str, body: AcceptRequest, state: StateDep) -> PlayerQuest:
    character = get_character(state, body.character_id)
    try:
        return quest_svc.accept_quest(state, character, quest_id)
    except quest_svc.QuestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/events", response_model=list[str])
def report_event(body: EventRequest, state: StateDep) -> list[str]:
    """Report a gameplay event; returns ids of quests that just completed."""
    character = get_character(state, body.character_id)
    return quest_svc.track_event(
        state, character, body.event, body.target, body.amount
    )


@router.post("/{quest_id}/claim", response_model=ClaimResponse)
def claim(quest_id: str, body: AcceptRequest, state: StateDep) -> ClaimResponse:
    character = get_character(state, body.character_id)
    player = get_player(state, character.player_id)
    try:
        grants = quest_svc.claim_rewards(state, player, character, quest_id)
    except quest_svc.QuestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ClaimResponse(quest_id=quest_id, granted=grants)

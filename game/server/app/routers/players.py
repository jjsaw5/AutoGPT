"""Player accounts: create, fetch, wallet + inventory."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..models import CurrencyCode, Player
from .deps import StateDep, get_player

router = APIRouter(prefix="/players", tags=["players"])

# New accounts get a small premium-currency welcome gift.
STARTING_COINS = 500
STARTING_GEMS = 100


class CreatePlayerRequest(BaseModel):
    name: str


@router.post("", response_model=Player, status_code=201)
def create_player(body: CreatePlayerRequest, state: StateDep) -> Player:
    player = Player(
        id=state.next_id("player"),
        name=body.name,
        wallet={CurrencyCode.COINS: STARTING_COINS, CurrencyCode.GEMS: STARTING_GEMS},
    )
    state.players[player.id] = player
    return player


@router.get("/{player_id}", response_model=Player)
def get_player_route(player_id: str, state: StateDep) -> Player:
    return get_player(state, player_id)

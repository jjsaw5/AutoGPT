"""Quest acceptance, progress tracking and reward claiming."""

from __future__ import annotations

from ..models import (
    Character,
    Player,
    PlayerQuest,
    QuestStatus,
)
from ..state import GameState
from . import economy


class QuestError(Exception):
    pass


def accept_quest(state: GameState, character: Character, quest_id: str) -> PlayerQuest:
    quest = state.quests.get(quest_id)
    if quest is None:
        raise QuestError(f"unknown quest '{quest_id}'")
    if quest_id in character.quests:
        raise QuestError("quest already accepted")
    if character.level < quest.required_level:
        raise QuestError(f"requires level {quest.required_level}")

    pq = PlayerQuest(
        quest_id=quest_id,
        progress={obj.id: 0 for obj in quest.objectives},
    )
    character.quests[quest_id] = pq
    return pq


def track_event(
    state: GameState,
    character: Character,
    event: str,
    target: str | None = None,
    amount: int = 1,
) -> list[str]:
    """Advance any active quest objectives matching this game event.

    Returns the ids of quests that just became COMPLETED.
    """
    newly_completed: list[str] = []
    for quest_id, pq in character.quests.items():
        if pq.status != QuestStatus.ACTIVE:
            continue
        quest = state.quests[quest_id]
        for obj in quest.objectives:
            if obj.event != event:
                continue
            if obj.target is not None and obj.target != target:
                continue
            pq.progress[obj.id] = min(obj.count, pq.progress[obj.id] + amount)

        if all(pq.progress[o.id] >= o.count for o in quest.objectives):
            pq.status = QuestStatus.COMPLETED
            newly_completed.append(quest_id)
    return newly_completed


def claim_rewards(state: GameState, player: Player, character: Character,
                  quest_id: str):
    """Claim a completed quest's rewards. Returns the granted rewards.

    XP rewards are applied via the progression service by the caller's router,
    so here we only hand back item/currency grants and the XP amount separately.
    """
    pq = character.quests.get(quest_id)
    if pq is None:
        raise QuestError("quest not accepted")
    if pq.status == QuestStatus.CLAIMED:
        raise QuestError("rewards already claimed")
    if pq.status != QuestStatus.COMPLETED:
        raise QuestError("quest not complete")

    quest = state.quests[quest_id]
    economy.apply_grants(player, quest.rewards)
    pq.status = QuestStatus.CLAIMED
    return quest.rewards

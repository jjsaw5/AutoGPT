"""Character progression: XP, leveling, attributes and skill trees.

Leveling grants points the player spends in two systems:
  * attribute points -> raw stat values (might/agility/vitality/tech)
  * skill points     -> nodes in branching skill trees (Arc Raiders style)
"""

from __future__ import annotations

from ..models import Character
from ..state import GameState

# Tuning knobs for the economy of progression.
MAX_LEVEL = 50
ATTRIBUTE_POINTS_PER_LEVEL = 2
SKILL_POINTS_PER_LEVEL = 1


class ProgressionError(Exception):
    pass


def xp_to_next_level(level: int) -> int:
    """XP required to go from `level` to `level + 1`.

    A gently accelerating curve: cheap early levels, steeper later ones.
    """
    return int(80 * level + 20 * level ** 1.6)


def total_xp_for_level(level: int) -> int:
    """Cumulative XP required to *reach* a given level from level 1."""
    return sum(xp_to_next_level(lvl) for lvl in range(1, level))


def add_xp(character: Character, amount: int) -> list[int]:
    """Add XP and apply any level-ups. Returns the list of levels gained."""
    if amount < 0:
        raise ProgressionError("xp amount must be non-negative")
    character.xp += amount
    gained: list[int] = []
    while character.level < MAX_LEVEL and character.xp >= xp_to_next_level(
        character.level
    ):
        character.xp -= xp_to_next_level(character.level)
        character.level += 1
        character.attribute_points += ATTRIBUTE_POINTS_PER_LEVEL
        character.skill_points += SKILL_POINTS_PER_LEVEL
        gained.append(character.level)
    if character.level >= MAX_LEVEL:
        character.xp = 0  # cap: no overflow XP stored at max level
    return gained


def allocate_attribute(character: Character, code: str, points: int = 1) -> None:
    if code not in _attribute_codes():
        raise ProgressionError(f"unknown attribute '{code}'")
    if points <= 0:
        raise ProgressionError("points must be positive")
    if character.attribute_points < points:
        raise ProgressionError("not enough attribute points")
    character.attribute_points -= points
    character.attributes[code] = character.attributes.get(code, 0) + points


def unlock_skill(state: GameState, character: Character, node_id: str) -> int:
    """Spend skill points to take (or rank up) a skill node. Returns new rank."""
    node = state.skill_nodes.get(node_id)
    if node is None:
        raise ProgressionError(f"unknown skill node '{node_id}'")

    current_rank = character.unlocked_skills.get(node_id, 0)
    if current_rank >= node.max_rank:
        raise ProgressionError(f"'{node_id}' already at max rank")

    # Prerequisites must each be unlocked at least once.
    for req in node.requires:
        if character.unlocked_skills.get(req, 0) < 1:
            raise ProgressionError(f"requires '{req}' first")

    if character.skill_points < node.cost:
        raise ProgressionError("not enough skill points")

    character.skill_points -= node.cost
    new_rank = current_rank + 1
    character.unlocked_skills[node_id] = new_rank
    return new_rank


def effective_bonuses(state: GameState, character: Character) -> dict[str, float]:
    """Aggregate all unlocked skill bonuses (rank-scaled) for the engine to use."""
    totals: dict[str, float] = {}
    for node_id, rank in character.unlocked_skills.items():
        node = state.skill_nodes.get(node_id)
        if not node:
            continue
        for key, value in node.bonuses.items():
            totals[key] = totals.get(key, 0) + value * rank
    return totals


def _attribute_codes() -> set[str]:
    # Local import to avoid a circular import at module load time.
    from .. import content

    return {a.code for a in content.ATTRIBUTES}

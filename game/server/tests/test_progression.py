from __future__ import annotations

import pytest

from app.models import Character
from app.services import progression
from app.state import GameState


def make_char() -> Character:
    return Character(id="c1", player_id="p1", name="Hero")


def test_xp_curve_is_monotonic_increasing():
    prev = 0
    for lvl in range(1, 50):
        cost = progression.xp_to_next_level(lvl)
        assert cost > prev
        prev = cost


def test_add_xp_levels_up_and_grants_points():
    char = make_char()
    need = progression.xp_to_next_level(1)
    gained = progression.add_xp(char, need)
    assert gained == [2]
    assert char.level == 2
    assert char.attribute_points == progression.ATTRIBUTE_POINTS_PER_LEVEL
    assert char.skill_points == progression.SKILL_POINTS_PER_LEVEL


def test_add_xp_multi_level():
    char = make_char()
    total = (
        progression.xp_to_next_level(1)
        + progression.xp_to_next_level(2)
        + progression.xp_to_next_level(3)
    )
    gained = progression.add_xp(char, total)
    assert gained == [2, 3, 4]
    assert char.level == 4
    assert char.xp == 0


def test_level_cap():
    char = make_char()
    progression.add_xp(char, 10_000_000)
    assert char.level == progression.MAX_LEVEL
    assert char.xp == 0


def test_allocate_attribute_requires_points():
    char = make_char()
    with pytest.raises(progression.ProgressionError):
        progression.allocate_attribute(char, "might", 1)

    char.attribute_points = 3
    progression.allocate_attribute(char, "might", 2)
    assert char.attributes["might"] == 2
    assert char.attribute_points == 1


def test_allocate_unknown_attribute_rejected():
    char = make_char()
    char.attribute_points = 5
    with pytest.raises(progression.ProgressionError):
        progression.allocate_attribute(char, "luck", 1)


def test_skill_prerequisites_and_ranks():
    state = GameState()
    char = make_char()
    char.skill_points = 10

    # Quick Hands requires Sharpshooter first.
    with pytest.raises(progression.ProgressionError):
        progression.unlock_skill(state, char, "cmb_quickhands")

    progression.unlock_skill(state, char, "cmb_sharpshooter")
    progression.unlock_skill(state, char, "cmb_quickhands")
    assert char.unlocked_skills["cmb_sharpshooter"] == 1
    assert char.unlocked_skills["cmb_quickhands"] == 1


def test_skill_max_rank_enforced():
    state = GameState()
    char = make_char()
    char.skill_points = 10
    # Sharpshooter has max_rank 3.
    for _ in range(3):
        progression.unlock_skill(state, char, "cmb_sharpshooter")
    assert char.unlocked_skills["cmb_sharpshooter"] == 3
    with pytest.raises(progression.ProgressionError):
        progression.unlock_skill(state, char, "cmb_sharpshooter")


def test_effective_bonuses_scale_with_rank():
    state = GameState()
    char = make_char()
    char.skill_points = 10
    progression.unlock_skill(state, char, "cmb_sharpshooter")
    progression.unlock_skill(state, char, "cmb_sharpshooter")
    bonuses = progression.effective_bonuses(state, char)
    assert bonuses["weapon_damage_pct"] == 10  # 5 per rank * 2 ranks

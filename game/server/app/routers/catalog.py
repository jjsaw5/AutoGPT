"""Read-only content catalog: items, skill trees, attributes."""

from __future__ import annotations

from fastapi import APIRouter

from .. import content
from ..models import AttributeDef, ItemDef, SkillNode, SkillTree
from .deps import StateDep

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/items", response_model=list[ItemDef])
def list_items(state: StateDep) -> list[ItemDef]:
    return list(state.items.values())


@router.get("/skill-trees", response_model=list[SkillTree])
def list_skill_trees() -> list[SkillTree]:
    return content.SKILL_TREES


@router.get("/skill-nodes", response_model=list[SkillNode])
def list_skill_nodes(state: StateDep) -> list[SkillNode]:
    return list(state.skill_nodes.values())


@router.get("/attributes", response_model=list[AttributeDef])
def list_attributes() -> list[AttributeDef]:
    return content.ATTRIBUTES

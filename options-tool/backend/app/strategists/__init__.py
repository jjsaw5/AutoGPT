"""Strategist implementations. Only Sosnoff is wired in Phase 1."""
from app.strategists.base import Strategist
from app.strategists.sosnoff import SosnoffStrategist

__all__ = ["Strategist", "SosnoffStrategist"]

"""Options Opportunity Scanner — recommend-only options decision-support engine.

Ingests market / options-flow / vol / catalyst data, filters and scores
optionable candidates, selects a best-fit structure, and emits a ranked
GO / WATCH / PASS readout. A human confirms every order (Build Spec v0.2).
"""

from .config import Config, load_config
from .models import (
    Candidate,
    CapTier,
    Decision,
    Direction,
    EvaluatedCandidate,
    Horizon,
    Structure,
    StructureType,
    Thesis,
    Tier,
    VolRegime,
)
from .scanner import Scanner, ScanResult

__version__ = "0.2.0"

__all__ = [
    "Config",
    "load_config",
    "Scanner",
    "ScanResult",
    "Candidate",
    "CapTier",
    "Decision",
    "Direction",
    "EvaluatedCandidate",
    "Horizon",
    "Structure",
    "StructureType",
    "Thesis",
    "Tier",
    "VolRegime",
]

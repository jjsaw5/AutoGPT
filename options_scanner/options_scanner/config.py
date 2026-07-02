"""Configuration loading for the Options Opportunity Scanner.

Loads the YAML config (non-secret knobs) and API keys from the environment.
Secrets are never read from or written to the YAML file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:  # optional; scanner still works if python-dotenv is absent
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass
class Credentials:
    """API keys pulled from the environment (never from YAML)."""

    fmp_api_key: str | None = None
    uw_api_key: str | None = None

    @property
    def has_fmp(self) -> bool:
        return bool(self.fmp_api_key)

    @property
    def has_uw(self) -> bool:
        return bool(self.uw_api_key)


@dataclass
class Config:
    """Parsed scanner configuration.

    The raw YAML mapping is kept on ``raw`` so callers can reach any knob;
    convenience accessors cover the hot paths used across the pipeline.
    """

    raw: dict[str, Any] = field(default_factory=dict)
    credentials: Credentials = field(default_factory=Credentials)

    # --- convenience accessors -------------------------------------------------
    def section(self, name: str) -> dict[str, Any]:
        value = self.raw.get(name, {})
        return value if isinstance(value, dict) else {}

    @property
    def account(self) -> dict[str, Any]:
        return self.section("account")

    @property
    def gates(self) -> dict[str, Any]:
        return self.section("gates")

    @property
    def scoring(self) -> dict[str, Any]:
        return self.section("scoring")

    @property
    def structure(self) -> dict[str, Any]:
        return self.section("structure")

    @property
    def universe(self) -> dict[str, Any]:
        return self.section("universe")

    @property
    def budget(self) -> dict[str, Any]:
        return self.section("budget")

    @property
    def speculative(self) -> dict[str, Any]:
        return self.section("speculative_bucket")

    @property
    def data(self) -> dict[str, Any]:
        return self.section("data")

    @property
    def weights(self) -> dict[str, float]:
        w = self.scoring.get("weights", {})
        return {k: float(v) for k, v in w.items()}

    @property
    def go_threshold(self) -> float:
        return float(self.scoring.get("go_threshold", 72))

    @property
    def watch_threshold(self) -> float:
        return float(self.scoring.get("watch_threshold", 58))


def load_config(
    path: str | os.PathLike[str] | None = None,
    *,
    load_env: bool = True,
) -> Config:
    """Load YAML config and environment credentials into a :class:`Config`."""

    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(config_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Config root must be a mapping, got {type(raw).__name__}")

    if load_env:
        # Load .env from the project root if present; real env always wins.
        load_dotenv(PROJECT_ROOT / ".env")

    creds = Credentials(
        fmp_api_key=os.environ.get("FMP_API_KEY"),
        uw_api_key=os.environ.get("UW_API_KEY"),
    )
    return Config(raw=raw, credentials=creds)

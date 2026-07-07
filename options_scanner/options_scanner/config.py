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
    turso_database_url: str | None = None
    turso_auth_token: str | None = None

    @property
    def has_fmp(self) -> bool:
        return bool(self.fmp_api_key)

    @property
    def has_uw(self) -> bool:
        return bool(self.uw_api_key)

    @property
    def has_turso(self) -> bool:
        return bool(self.turso_database_url and self.turso_auth_token)


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
    def market_context(self) -> dict[str, Any]:
        return self.section("market_context")

    @property
    def catalysts(self) -> dict[str, Any]:
        return self.section("catalysts")

    @property
    def weights(self) -> dict[str, float]:
        w = self.scoring.get("weights", {})
        return {k: float(v) for k, v in w.items()}

    # --- sizing (percentage-based, of account size, with $ fallbacks) ---------
    @property
    def account_size(self) -> float:
        return float(self.account.get("size", 5000))

    def _risk_dollars(self, pct_key: str, dollar_key: str, dollar_default: float) -> float:
        pct = self.account.get(pct_key)
        if pct is not None:
            return round(self.account_size * float(pct), 2)
        return float(self.account.get(dollar_key, dollar_default))

    def risk_standard(self) -> float:
        return self._risk_dollars("risk_standard_pct", "risk_standard_max", 200)

    def risk_high_conviction(self) -> float:
        return self._risk_dollars("risk_high_conviction_pct", "risk_high_conviction_max", 500)

    def max_trade_risk(self) -> float:
        """Explicit per-trade risk ceiling ($). A 'learning-mode' override that
        *raises* the G6 cap so bigger setups can green-light while we accumulate
        data points. 0/absent → disabled (use the %-based ceiling). Narrow this
        as the model is dialed in."""
        return float(self.account.get("max_trade_risk", 0) or 0)

    def per_trade_risk_cap(self) -> float:
        """Effective G6 per-trade ceiling: the larger of the %-based
        high-conviction ceiling and the explicit ``max_trade_risk`` override."""
        return max(self.risk_high_conviction(), self.max_trade_risk())

    def max_open_risk(self) -> float:
        return self._risk_dollars("max_open_pct", "max_open_risk", 2000)

    def max_correlated_risk(self) -> float:
        pct = self.account.get("max_correlated_pct", 0.15)
        return round(self.account_size * float(pct), 2)

    def max_positions(self) -> int:
        return int(self.account.get("max_positions", 6))

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
        turso_database_url=os.environ.get("TURSO_DATABASE_URL"),
        turso_auth_token=os.environ.get("TURSO_AUTH_TOKEN"),
    )
    return Config(raw=raw, credentials=creds)

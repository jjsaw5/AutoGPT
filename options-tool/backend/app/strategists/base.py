"""Shared ``Strategist`` protocol.

Every strategy module must implement this protocol so the Unified Trade Card
can evaluate one ticker against all five philosophies side-by-side.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.models import (
    Account,
    Candidate,
    ManagementAction,
    MarketSnapshot,
    OptionChain,
    Position,
    PositionSize,
    TradeSetup,
)


@runtime_checkable
class Strategist(Protocol):
    """One trading philosophy. Composable across the trade-card surface."""

    name: str

    def screen(self, universe: list[str]) -> list[Candidate]:
        """Coarse filter — returns tickers worth running ``analyze`` on."""
        ...

    def analyze(self, ticker: str, chain: OptionChain) -> TradeSetup | None:
        """Produce a concrete setup, or None if the strategy has nothing to offer."""
        ...

    def size(self, setup: TradeSetup, account: Account) -> PositionSize:
        """Translate the setup + account state into a contract count."""
        ...

    def manage(self, position: Position, market: MarketSnapshot) -> ManagementAction:
        """Decide whether to hold, close, or adjust an open position."""
        ...

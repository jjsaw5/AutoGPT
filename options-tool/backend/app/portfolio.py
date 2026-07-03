"""Portfolio-level aggregation used by the Risk Dashboard and Sosnoff module."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.models import CONTRACT_MULTIPLIER, Position


@dataclass
class PortfolioGreeks:
    delta: float
    gamma: float
    theta: float
    vega: float
    notional: float
    position_count: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
            "notional": self.notional,
            "position_count": self.position_count,
        }


def aggregate(positions: list[Position]) -> PortfolioGreeks:
    delta = gamma = theta = vega = notional = 0.0
    for pos in positions:
        contracts = pos.size.contracts
        for leg in pos.setup.legs:
            qty = leg.quantity * contracts
            c = leg.contract
            delta += (c.delta or 0.0) * qty * CONTRACT_MULTIPLIER
            gamma += (c.gamma or 0.0) * qty * CONTRACT_MULTIPLIER
            theta += (c.theta or 0.0) * qty * CONTRACT_MULTIPLIER
            vega += (c.vega or 0.0) * qty * CONTRACT_MULTIPLIER
            notional += abs(qty) * c.strike * CONTRACT_MULTIPLIER
    return PortfolioGreeks(
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
        notional=notional,
        position_count=len(positions),
    )

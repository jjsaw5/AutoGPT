"""0DTE contract selection and position sizing.

Picking the contract is a liquidity problem before it is a greeks problem.
A 0.40-delta contract with a 12% bid/ask spread hands back a third of the
profit target on the round trip, so the filters run first and the delta
preference only chooses among what survives them.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .config import ContractConfig, RiskConfig
from .models import OptionContract


class NoContractFound(RuntimeError):
    pass


def filter_contracts(
    contracts: Sequence[OptionContract],
    direction: int,
    config: ContractConfig | None = None,
) -> list[OptionContract]:
    config = config or ContractConfig()
    wanted = "call" if direction > 0 else "put"

    survivors = []
    for contract in contracts:
        if contract.option_type != wanted:
            continue
        if contract.mid <= 0 or contract.mid > config.max_premium:
            continue
        if contract.spread_pct > config.max_spread_pct:
            continue
        if contract.open_interest < config.min_open_interest:
            continue
        if contract.volume < config.min_volume:
            continue
        if contract.delta is not None:
            if not (config.min_delta <= abs(contract.delta) <= config.max_delta):
                continue
        survivors.append(contract)
    return survivors


def select_contract(
    contracts: Sequence[OptionContract],
    direction: int,
    config: ContractConfig | None = None,
) -> OptionContract:
    """Closest to target delta among liquid contracts.

    Falls back to spread-ranking when the feed omits greeks, which the
    broker payload sometimes does for far strikes.
    """
    config = config or ContractConfig()
    survivors = filter_contracts(contracts, direction, config)
    if not survivors:
        raise NoContractFound(
            "no contract passed the liquidity filters "
            f"(spread <= {config.max_spread_pct:.0%}, "
            f"OI >= {config.min_open_interest}, vol >= {config.min_volume})"
        )

    with_delta = [c for c in survivors if c.delta is not None]
    if with_delta:
        return min(with_delta, key=lambda c: abs(abs(c.delta) - config.target_delta))
    return min(survivors, key=lambda c: c.spread_pct)


def size_position(
    contract: OptionContract,
    risk_dollars: float,
    config: RiskConfig | None = None,
) -> tuple[int, float]:
    """Contracts to buy, and the dollars actually at risk.

    Risk per contract is premium * 100 * stop%, because the stop is a
    percentage of premium. Size never scales with conviction -- that is the
    failure mode this whole process is built to avoid.
    """
    config = config or RiskConfig()
    premium = contract.mid
    if premium <= 0:
        return 0, 0.0

    risk_per_contract = premium * 100 * config.stop_loss_pct
    if risk_per_contract <= 0:
        return 0, 0.0

    quantity = math.floor(risk_dollars / risk_per_contract)
    quantity = max(0, min(quantity, config.max_contracts))
    return quantity, quantity * risk_per_contract


def describe(contract: OptionContract, quantity: int) -> str:
    delta = f"{abs(contract.delta):.2f}" if contract.delta is not None else "n/a"
    return (
        f"{quantity}x {contract.symbol} {contract.expiration} "
        f"{contract.strike:g}{contract.option_type[0].upper()} "
        f"@ ~{contract.mid:.2f} (delta {delta}, spread {contract.spread_pct:.1%}, "
        f"OI {contract.open_interest}, vol {contract.volume})"
    )

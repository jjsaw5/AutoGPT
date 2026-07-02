"""Chain parsing + structure realization from a synthetic (no-network) chain."""

from __future__ import annotations

import pytest

from options_scanner.models import Leg, StructureType
from options_scanner.pipeline.chain import OptionChain, OptionContract, parse_occ
from options_scanner.pipeline.structure import plan_structure
from options_scanner.pipeline.structure_chain import realize_from_chain
from options_scanner.pipeline.scoring import score_candidate
from options_scanner.models import (
    Catalyst, Direction, Horizon, Thesis, VolRegime,
)

from .conftest import make_candidate


def test_parse_occ():
    assert parse_occ("AAPL260717C00317500") == ("call", "2026-07-17", 317.5)
    assert parse_occ("SPY260102P00450000") == ("put", "2026-01-02", 450.0)
    assert parse_occ("garbage") is None


def _synthetic_chain(spot: float = 100.0) -> OptionChain:
    contracts: list[OptionContract] = []
    for strike in range(int(spot) - 10, int(spot) + 11):
        # Calls: mid falls, delta falls as strike rises.
        call_mid = max(0.1, (spot - strike) + 5.0)
        call_delta = max(0.02, min(0.98, 0.5 - (strike - spot) * 0.05))
        contracts.append(OptionContract(
            "call", "2026-07-17", float(strike), oi=2000, volume=800,
            bid=round(call_mid - 0.1, 2), ask=round(call_mid + 0.1, 2),
            iv=0.3, delta=call_delta,
        ))
        # Puts: mid rises, |delta| rises as strike rises.
        put_mid = max(0.1, (strike - spot) + 5.0)
        put_delta = -max(0.02, min(0.98, 0.5 + (strike - spot) * 0.05))
        contracts.append(OptionContract(
            "put", "2026-07-17", float(strike), oi=2000, volume=800,
            bid=round(put_mid - 0.1, 2), ask=round(put_mid + 0.1, 2),
            iv=0.3, delta=put_delta,
        ))
    return OptionChain("TEST", "2026-07-17", spot, 15, contracts)


def _plan_for(config, **kw):
    base = dict(
        direction=Direction.BULLISH, conviction=0.5, vol_regime=VolRegime.RICH,
        horizon=Horizon.POSITION, catalyst=Catalyst.FLOW_ONLY, iv_rank=80.0,
    )
    base.update(kw)
    t = Thesis(**base)
    return plan_structure(t, config), t


def test_bullish_credit_uses_puts(config):
    # Rich vol + bullish + moderate => credit vertical; correct geometry = bull put.
    plan, _ = _plan_for(config)
    s = realize_from_chain(plan, _synthetic_chain(), ceiling=500.0)
    assert s is not None
    assert s.structure_type == StructureType.CREDIT_VERTICAL
    assert all(leg.option_type == "put" for leg in s.legs)   # bull put spread
    assert s.from_chain and s.max_loss <= 500.0
    assert s.short_delta is not None
    assert s.contract_oi == 2000


def test_bullish_debit_uses_calls(config):
    plan, _ = _plan_for(config, vol_regime=VolRegime.CHEAP, iv_rank=20.0, conviction=0.4)
    assert plan.kind == "debit_vertical"
    s = realize_from_chain(plan, _synthetic_chain(), ceiling=500.0)
    assert s is not None
    assert all(leg.option_type == "call" for leg in s.legs)  # bull call spread
    assert s.max_loss <= 500.0


def test_expensive_long_falls_back_to_spread_on_chain(config):
    # Naked long ATM call mid ~5.0 => $500 premium; at ceiling 300 it must
    # fall back to a debit vertical.
    plan, _ = _plan_for(
        config, vol_regime=VolRegime.CHEAP, iv_rank=15.0, conviction=0.8,
        horizon=Horizon.SWING,
    )
    assert plan.kind == "long"
    s = realize_from_chain(plan, _synthetic_chain(), ceiling=300.0)
    assert s is not None
    assert s.structure_type == StructureType.DEBIT_VERTICAL
    assert s.max_loss <= 300.0


def test_delta_based_pop(config):
    plan, thesis = _plan_for(config)
    s = realize_from_chain(plan, _synthetic_chain(), ceiling=500.0)
    c = make_candidate("TEST", price=100.0)
    score = score_candidate(c, thesis, s, config)
    # Credit spread POP = 1 - |short put delta|; short put is near-ATM (~0.5).
    assert 0.3 < score.pop < 0.95

"""Sanity checks on domain models."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.core.models import (
    OptionContract,
    OptionRight,
    TradeLeg,
)


def _contract(**overrides: object) -> OptionContract:
    defaults: dict[str, object] = dict(
        symbol="SPY260522C00500000",
        underlying="SPY",
        expiry=date(2026, 5, 22),
        strike=500.0,
        right=OptionRight.CALL,
        bid=3.10,
        ask=3.30,
        last=3.20,
        as_of=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return OptionContract(**defaults)  # type: ignore[arg-type]


def test_contract_mid_and_spread() -> None:
    c = _contract()
    assert c.mid == pytest.approx(3.20)
    assert c.spread == pytest.approx(0.20)


def test_contract_mid_falls_back_to_last_when_no_quotes() -> None:
    c = _contract(bid=0, ask=0, last=1.11)
    assert c.mid == pytest.approx(1.11)


def test_trade_leg_rejects_zero_quantity() -> None:
    with pytest.raises(ValidationError):
        TradeLeg(contract=_contract(), quantity=0)


def test_trade_leg_long_short_semantics() -> None:
    long_leg = TradeLeg(contract=_contract(), quantity=2)
    short_leg = TradeLeg(contract=_contract(), quantity=-1)
    assert long_leg.is_long is True
    assert short_leg.is_long is False

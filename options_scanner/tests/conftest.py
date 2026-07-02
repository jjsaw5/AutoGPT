"""Shared test fixtures / helpers."""

from __future__ import annotations

from typing import Any

import pytest

from options_scanner.config import load_config
from options_scanner.models import Candidate, CapTier, Tier


@pytest.fixture
def config():
    return load_config(load_env=False)


def make_candidate(
    ticker: str = "AAPL",
    *,
    cap_tier: CapTier = CapTier.MEGA,
    price: float = 300.0,
    market_cap: float = 4.5e12,
    sector: str = "Technology",
    signals: dict[str, Any] | None = None,
) -> Candidate:
    base_signals: dict[str, Any] = {
        "price": price,
        "market_cap": market_cap,
        "sector": sector,
        "avg_volume": 50_000_000,
        "price_avg_50": price * 0.97,
        "price_avg_200": price * 0.9,
        "iv_rank": 20.0,
        "iv": 0.25,
        "rv": 0.30,
        "net_prem": {
            "net_call_premium": 1_500_000.0,
            "net_put_premium": -200_000.0,
            "net_call_volume": 5000.0,
            "net_put_volume": -1000.0,
        },
        "flow_alerts": [
            {"type": "call", "open_interest": 3000, "volume": 1500,
             "nbbo_bid": "1.00", "nbbo_ask": "1.05", "price": "1.03"},
        ],
        "darkpool": [
            {"price": "301.0", "nbbo_bid": "300.5", "nbbo_ask": "300.7"},
            {"price": "301.5", "nbbo_bid": "300.6", "nbbo_ask": "300.8"},
        ],
        "term_structure": [
            {"dte": 0, "implied_move_perc": "0.004"},
            {"dte": 7, "implied_move_perc": "0.025"},
            {"dte": 30, "implied_move_perc": "0.05"},
        ],
        "max_pain": 290.0,
    }
    if signals:
        base_signals.update(signals)
    return Candidate(
        ticker=ticker,
        tier=Tier.A,
        cap_tier=cap_tier,
        market_cap=market_cap,
        sector=sector,
        price=price,
        signals=base_signals,
    )

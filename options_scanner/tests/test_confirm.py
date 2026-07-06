"""Robinhood confirmation layer — re-pricing actionable candidates on real quotes."""

from __future__ import annotations

from options_scanner.confirm import (
    LegQuote,
    Confirmation,
    confirm_structure,
    render_confirmations,
)
from options_scanner.models import Leg, Structure, StructureType


def _debit_spread(long_k=750, short_k=755):
    return Structure(
        structure_type=StructureType.DEBIT_VERTICAL,
        legs=[Leg("buy", "call", long_k, "2026-07-20", mid=8.0),
              Leg("sell", "call", short_k, "2026-07-20", mid=5.0)],
        max_profit=600.0, max_loss=400.0, breakevens=[753.0], from_chain=True,
    )


def _q(otype, strike, bid, ask, oi=1000, vol=800, delta=None):
    return LegQuote(otype, strike, "2026-07-20", bid, ask, oi, vol, delta)


def test_confirmed_when_pricing_holds():
    s = _debit_spread()
    # real mids: long 8.10, short 5.10 -> debit 3.00 -> cost $300, width 5 ->
    # max profit $200, max loss $300, R:R 0.67 ... that's < 1:1 -> REJECT.
    # Use a wider, cheaper spread so it holds: long 8.00 / short 4.00 on a 750/760.
    s = Structure(
        structure_type=StructureType.DEBIT_VERTICAL,
        legs=[Leg("buy", "call", 750, "2026-07-20", mid=8.0),
              Leg("sell", "call", 760, "2026-07-20", mid=4.0)],
        max_profit=600.0, max_loss=400.0, breakevens=[754.0], from_chain=True,
    )
    quotes = [_q("call", 750, 3.96, 4.04), _q("call", 760, 1.97, 2.03)]
    # debit = 4.00 - 2.00 = 2.00 -> cost $200, width 10 -> maxP $800, maxL $200, R:R 4:1
    c = confirm_structure(s, quotes, ticker="SPY", pop=0.55)
    assert c.verdict == "CONFIRMED"
    assert c.real_cost == 200.0 and c.real_max_loss == 200.0
    assert c.real_rr == 4.0


def test_rejected_on_negative_ev():
    # SPY-like: ATM debit spread that's expensive relative to width -> -EV.
    s = _debit_spread(750, 755)
    quotes = [_q("call", 750, 8.00, 8.20), _q("call", 755, 5.00, 5.20)]
    # debit ~3.10 -> cost $310, width 5 -> maxP $190, maxL $310, R:R 0.61
    c = confirm_structure(s, quotes, ticker="SPY", pop=0.45)
    assert c.verdict == "REJECTED"
    assert c.real_rr < 1.0                 # sub-1:1 on real pricing


def test_rejected_when_illiquid():
    s = _debit_spread(750, 760)
    quotes = [_q("call", 750, 3.97, 4.03, oi=5, vol=3),
              _q("call", 760, 1.98, 2.02, oi=2, vol=1)]
    c = confirm_structure(s, quotes, ticker="XYZ", pop=0.6)
    assert c.verdict == "REJECTED" and "illiquid" in c.reason


def test_credit_spread_economics():
    s = Structure(
        structure_type=StructureType.CREDIT_VERTICAL,
        legs=[Leg("sell", "put", 990, "2026-07-17", mid=6.0),
              Leg("buy", "put", 980, "2026-07-17", mid=2.0)],
        max_profit=400.0, max_loss=600.0, breakevens=[986.0], from_chain=True,
    )
    quotes = [_q("put", 990, 5.95, 6.05), _q("put", 980, 1.97, 2.03)]
    # credit = 6.0 - 2.0 = 4.0 -> maxP $400, width 10 -> maxL $600
    c = confirm_structure(s, quotes, ticker="MU", pop=0.66)
    assert c.is_credit and c.real_max_profit == 400.0 and c.real_max_loss == 600.0
    assert c.verdict in ("CONFIRMED", "DEGRADED")


def test_returns_none_when_legs_unmatched():
    s = _debit_spread()
    assert confirm_structure(s, [_q("put", 750, 1, 2)], ticker="X") is None


def test_render_puts_rejected_first():
    confs = [
        Confirmation("A", "CONFIRMED", "ok", 200, False, 800, 200, 4.0, 754, 50,
                     1000, 800, 0.02),
        Confirmation("B", "REJECTED", "neg EV", 310, False, 190, 310, 0.61, 753, -20,
                     1000, 800, 0.03),
    ]
    out = render_confirmations(confs)
    assert out.index("B") < out.index("A")     # REJECTED shown first
    assert "ROBINHOOD CONFIRMATION" in out

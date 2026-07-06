"""Robinhood confirmation layer — re-price actionable candidates on real quotes.

The scanner proposes structures on Unusual Whales data, which is fine for
*ranking* but can misprice the trade (UW reported OI=0 and a rosy EV for SPY
that a real chain flatly contradicts). Robinhood is the ground truth for
*executable* pricing, but it's only reachable through the MCP (agent context),
not the headless scanner — exactly like the position-review book pull.

So this is a confirmation *layer*, not a data source: the agent pulls live
Robinhood quotes for a candidate's exact legs and feeds them in as
:class:`LegQuote` rows; :func:`confirm_structure` re-computes the real cost,
reward:risk, EV, and liquidity, and returns a verdict —

    CONFIRMED  — real pricing holds up; safe to surface as actionable
    DEGRADED   — still positive-EV but materially worse than the estimate
    REJECTED   — real pricing kills it (negative EV / illiquid / too wide)

Recommend-only: a verdict is decision support, never an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import Structure, StructureType

_FEE = 5.0                      # flat per-trade fee/slippage placeholder ($)
_DEGRADE_COST = 0.15            # >15% costlier than estimate => DEGRADED
_DEGRADE_RR = 0.20             # >20% worse reward:risk => DEGRADED

_DEBIT_FAMILY = {
    StructureType.DEBIT_VERTICAL, StructureType.ZERO_DTE_SPREAD,
    StructureType.LONG_CALL, StructureType.LONG_PUT, StructureType.LONG_STRADDLE,
    StructureType.LEAPS,
}
_CREDIT_FAMILY = {StructureType.CREDIT_VERTICAL, StructureType.IRON_CONDOR}


@dataclass
class LegQuote:
    """A live Robinhood quote for one contract (supplied by the agent via MCP)."""
    option_type: str            # "call" | "put"
    strike: float
    expiry: str                 # ISO
    bid: float
    ask: float
    oi: int = 0
    volume: int = 0
    delta: Optional[float] = None

    @property
    def mid(self) -> Optional[float]:
        if self.bid is None or self.ask is None or self.ask <= 0:
            return None
        return round((self.bid + self.ask) / 2, 4)

    @property
    def spread_pct(self) -> Optional[float]:
        m = self.mid
        if not m or m <= 0:
            return None
        return (self.ask - self.bid) / m


@dataclass
class Confirmation:
    ticker: str
    verdict: str                # CONFIRMED | DEGRADED | REJECTED
    reason: str
    real_cost: float            # debit paid (+) or credit received (+, as cash in)
    is_credit: bool
    real_max_profit: Optional[float]
    real_max_loss: Optional[float]
    real_rr: Optional[float]    # reward : risk
    real_breakeven: Optional[float]
    real_ev: Optional[float]
    min_oi: int
    min_volume: int
    max_spread_pct: Optional[float]
    est_cost: Optional[float] = None
    est_rr: Optional[float] = None


def _match(leg, quotes: list[LegQuote]) -> Optional[LegQuote]:
    """Nearest quote of the same option type by strike (expiry already fixed)."""
    same = [q for q in quotes if q.option_type == leg.option_type]
    if not same:
        return None
    return min(same, key=lambda q: abs(q.strike - leg.strike))


def confirm_structure(
    structure: Structure,
    leg_quotes: list[LegQuote],
    *,
    ticker: str,
    pop: Optional[float] = None,
    oi_min: float = 250.0,
    vol_min: float = 100.0,
    spread_max: float = 0.10,
    fee: float = _FEE,
) -> Optional[Confirmation]:
    """Re-price ``structure`` on real ``leg_quotes`` and return a verdict.

    Returns ``None`` if the legs can't be matched/priced (caller keeps the
    scanner estimate and flags it unconfirmed).
    """
    matched: list[tuple] = []           # (leg, quote)
    for leg in structure.legs:
        q = _match(leg, leg_quotes)
        if q is None or q.mid is None:
            return None
        matched.append((leg, q))

    # Net cash: +mid for a buy (pay), -mid for a sell (receive). >0 => net debit.
    net = sum((q.mid if leg.action == "buy" else -q.mid) for leg, q in matched)
    st = structure.structure_type
    is_credit = st in _CREDIT_FAMILY or (st not in _DEBIT_FAMILY and net < 0)

    max_profit, max_loss, breakeven = _economics(st, matched, net, structure)
    real_cost = round(abs(net) * 100, 2)
    rr = (max_profit / max_loss) if (max_profit and max_loss) else None

    # Liquidity across legs (OI can be a bogus 0; volume carries it — see G1).
    ois = [q.oi for _, q in matched]
    vols = [q.volume for _, q in matched]
    spreads = [q.spread_pct for _, q in matched if q.spread_pct is not None]
    min_oi, min_vol = min(ois), min(vols)
    max_spread = max(spreads) if spreads else None

    # Real EV using the scanner's POP against the real payoff.
    ev = None
    if pop is not None and max_profit is not None and max_loss is not None:
        ev = round(pop * max_profit - (1 - pop) * max_loss - fee, 2)

    est_cost = structure.max_loss if not is_credit else structure.max_profit
    est_rr = (structure.max_profit / structure.max_loss
              if structure.max_profit and structure.max_loss else None)

    verdict, reason = _verdict(
        ev=ev, rr=rr, is_credit=is_credit, min_oi=min_oi, min_vol=min_vol,
        max_spread=max_spread, oi_min=oi_min, vol_min=vol_min, spread_max=spread_max,
        real_cost=real_cost, est_cost=est_cost, est_rr=est_rr,
    )

    return Confirmation(
        ticker=ticker, verdict=verdict, reason=reason,
        real_cost=real_cost, is_credit=is_credit,
        real_max_profit=max_profit, real_max_loss=max_loss, real_rr=rr,
        real_breakeven=breakeven, real_ev=ev,
        min_oi=min_oi, min_volume=min_vol, max_spread_pct=max_spread,
        est_cost=est_cost, est_rr=est_rr,
    )


def _economics(st, matched, net, structure):
    """Real (max_profit, max_loss, breakeven) from the matched legs, in $."""
    legs = [(leg, q) for leg, q in matched]
    if st in (StructureType.LONG_CALL, StructureType.LONG_PUT,
              StructureType.LEAPS, StructureType.LONG_STRADDLE):
        cost = abs(net) * 100
        # single/naked long: profit uncapped — keep the scanner's target ratio.
        mp = round(structure.max_profit, 2) if structure.max_profit else None
        return mp, round(cost, 2), None

    strikes = sorted(q.strike for _, q in legs)
    if st in (StructureType.DEBIT_VERTICAL, StructureType.CREDIT_VERTICAL,
              StructureType.ZERO_DTE_SPREAD):
        width = abs(strikes[-1] - strikes[0])
        if net > 0:                       # debit
            debit = net
            mp = round((width - debit) * 100, 2)
            ml = round(debit * 100, 2)
            long_leg = next(q for leg, q in legs if leg.action == "buy")
            be = (long_leg.strike + debit if long_leg.option_type == "call"
                  else long_leg.strike - debit)
        else:                             # credit
            credit = -net
            mp = round(credit * 100, 2)
            ml = round((width - credit) * 100, 2)
            short_leg = next(q for leg, q in legs if leg.action == "sell")
            be = (short_leg.strike + credit if short_leg.option_type == "call"
                  else short_leg.strike - credit)
        return mp, ml, round(be, 2)

    if st == StructureType.IRON_CONDOR:
        credit = -net if net < 0 else 0.0
        calls = sorted(q.strike for leg, q in legs if q.option_type == "call")
        puts = sorted(q.strike for leg, q in legs if q.option_type == "put")
        wing = 0.0
        if len(calls) >= 2:
            wing = max(wing, calls[-1] - calls[0])
        if len(puts) >= 2:
            wing = max(wing, puts[-1] - puts[0])
        mp = round(credit * 100, 2)
        ml = round((wing - credit) * 100, 2) if wing else None
        return mp, ml, None

    return None, None, None


def _verdict(*, ev, rr, is_credit, min_oi, min_vol, max_spread,
             oi_min, vol_min, spread_max, real_cost, est_cost, est_rr) -> tuple[str, str]:
    # Hard rejects on real economics / tradability.
    if ev is not None and ev <= 0:
        return "REJECTED", f"negative EV on real pricing (${ev:.0f})"
    if max_spread is not None and max_spread > spread_max:
        return "REJECTED", f"spread too wide ({max_spread:.0%} > {spread_max:.0%})"
    if min_vol < vol_min and min_oi < oi_min:
        return "REJECTED", f"illiquid (OI {min_oi}, vol {min_vol})"
    # For a debit trade, a sub-1:1 real reward:risk is a red flag.
    if not is_credit and rr is not None and rr < 1.0:
        return "REJECTED", f"reward:risk {rr:.2f}:1 below 1:1 on real pricing"

    # Degraded: positive but materially worse than the scanner estimate.
    if est_cost and real_cost > est_cost * (1 + _DEGRADE_COST):
        return "DEGRADED", f"real cost ${real_cost:.0f} vs est ${est_cost:.0f}"
    if est_rr and rr is not None and rr < est_rr * (1 - _DEGRADE_RR):
        return "DEGRADED", f"real R:R {rr:.2f} vs est {est_rr:.2f}"

    detail = f"EV ${ev:.0f}" if ev is not None else "priced on real quotes"
    return "CONFIRMED", f"holds on real pricing ({detail})"


def render_confirmations(confs: list[Confirmation]) -> str:
    """Compact confirmation block, REJECTED first (most important to see)."""
    if not confs:
        return "[C] ROBINHOOD CONFIRMATION\n  (no candidates confirmed)\n"
    order = {"REJECTED": 0, "DEGRADED": 1, "CONFIRMED": 2}
    lines = ["[C] ROBINHOOD CONFIRMATION  (actionable candidates re-priced on live quotes)"]
    for c in sorted(confs, key=lambda x: order.get(x.verdict, 9)):
        kind = "cr" if c.is_credit else "db"
        rr = f"{c.real_rr:.2f}:1" if c.real_rr is not None else "—"
        ev = f"${c.real_ev:.0f}" if c.real_ev is not None else "—"
        lines.append(
            f"  {c.ticker:<6} {c.verdict:<9} cost ${c.real_cost:.0f}{kind} · "
            f"R:R {rr} · EV {ev} · OI {c.min_oi}/vol {c.min_volume} — {c.reason}"
        )
    return "\n".join(lines) + "\n"

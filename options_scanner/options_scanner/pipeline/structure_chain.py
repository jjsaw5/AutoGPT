"""Realize a structure :class:`Plan` against a live :class:`OptionChain`.

Produces structures with *real* strikes, premiums (NBBO mid), max profit/loss,
breakevens, and per-leg liquidity + delta — so gates G1/G2/G9 and POP evaluate
on the actual chain rather than proxies/placeholders. Returns ``None`` when the
chain lacks the data to build a given structure, so the caller falls back to the
nominal placeholder path.

Directional conventions (correct spread geometry):
  debit  bullish → bull call spread (calls); bearish → bear put spread (puts)
  credit bullish → bull put spread  (puts);  bearish → bear call spread (calls)
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Leg, Structure, StructureType
from .chain import OptionChain, OptionContract

_LONG_TARGET_RR = 1.3
_LEAPS_TARGET_RR = 1.5
_MAX_WIDTH_STRIKES = 8  # widest vertical to consider, in strike steps


def realize_from_chain(plan, chain: OptionChain, ceiling: float) -> Structure | None:
    kind = plan.kind
    if kind == "long":
        return _long(plan, chain, ceiling)
    if kind == "leaps":
        return _leaps(plan, chain, ceiling)
    if kind == "iron_condor":
        return _condor(chain, ceiling, plan.rationale)
    if kind in ("debit_vertical", "credit_vertical", "zerodte"):
        credit = plan.credit
        st = (
            StructureType.ZERO_DTE_SPREAD if kind == "zerodte"
            else StructureType.CREDIT_VERTICAL if credit
            else StructureType.DEBIT_VERTICAL
        )
        return _vertical(chain, bullish=plan.call, credit=credit, ceiling=ceiling,
                         structure_type=st, rationale=plan.rationale)
    return None


# --- single-leg long ----------------------------------------------------------
def _long(plan, chain: OptionChain, ceiling: float) -> Structure | None:
    opt = "call" if plan.call else "put"
    c = chain.atm(opt)
    if c is None or c.mid is None:
        return None
    premium = c.mid * 100
    if premium > ceiling:
        # Naked long too expensive → debit vertical, sized to the cap.
        v = _vertical(chain, bullish=plan.call, credit=False, ceiling=ceiling,
                      structure_type=StructureType.DEBIT_VERTICAL,
                      rationale="cheap vol, strong conviction, but naked long exceeds risk cap — debit spread")
        return v
    be = c.strike + c.mid if plan.call else c.strike - c.mid
    return Structure(
        structure_type=StructureType.LONG_CALL if plan.call else StructureType.LONG_PUT,
        legs=[Leg("buy", opt, c.strike, c.expiry)],
        max_profit=round(premium * _LONG_TARGET_RR, 2),
        max_loss=round(premium, 2),
        breakevens=[round(be, 2)],
        rationale=plan.rationale,
        is_defined_risk=True,
        contract_oi=c.oi,
        contract_volume=c.volume,
        spread_pct=c.spread_pct,
        short_delta=abs(c.delta) if c.delta is not None else None,
        expiry=c.expiry,
        from_chain=True,
    )


def _leaps(plan, chain: OptionChain, ceiling: float) -> Structure | None:
    opt = "call" if plan.call else "put"
    c = chain.by_delta(opt, 0.75)  # deep-ITM ~0.75Δ stock replacement
    if c is None or c.mid is None:
        return None
    premium = c.mid * 100
    be = c.strike + c.mid if plan.call else c.strike - c.mid
    return Structure(
        structure_type=StructureType.LEAPS,
        legs=[Leg("buy", opt, c.strike, c.expiry)],
        max_profit=round(premium * _LEAPS_TARGET_RR, 2),
        max_loss=round(premium, 2),
        breakevens=[round(be, 2)],
        rationale=plan.rationale,
        is_defined_risk=True,
        contract_oi=c.oi, contract_volume=c.volume, spread_pct=c.spread_pct,
        short_delta=abs(c.delta) if c.delta is not None else None,
        expiry=c.expiry, from_chain=True,
    )


# --- verticals ----------------------------------------------------------------
@dataclass
class _VResult:
    short: OptionContract
    long: OptionContract
    credit: bool
    max_profit: float
    max_loss: float
    breakeven: float


def _pick_vertical(
    chain: OptionChain, opt: str, credit: bool, sign: int, ceiling: float
) -> _VResult | None:
    """Choose the widest vertical (in strike steps) whose max loss fits the cap.

    ``sign`` = +1 means the outer/protective leg is above the anchor strike,
    -1 below. For credit, the anchor is the near-OTM short strike; for debit the
    anchor is the ATM long strike.
    """
    side = chain._side(opt)
    if len(side) < 2:
        return None

    if credit:
        anchor = _otm_anchor(side, chain.spot, sign)
    else:
        anchor = chain.at_strike(opt, chain.spot)
    if anchor is None or anchor.mid is None:
        return None

    fitting: list[_VResult] = []
    fallback: _VResult | None = None  # narrowest-risk if nothing fits the cap
    for n in range(1, _MAX_WIDTH_STRIKES + 1):
        outer = chain.offset_strike(opt, anchor.strike, sign * n)
        if outer is None or outer.mid is None or outer.oi <= 0:
            continue
        if credit:
            short, long = anchor, outer
            credit_amt = short.mid - long.mid
            if credit_amt <= 0:
                continue
            width = abs(long.strike - short.strike)
            max_loss = round((width - credit_amt) * 100, 2)
            max_profit = round(credit_amt * 100, 2)
            be = short.strike - credit_amt if sign < 0 else short.strike + credit_amt
        else:
            long, short = anchor, outer
            debit_amt = long.mid - short.mid
            if debit_amt <= 0:
                continue
            width = abs(long.strike - short.strike)
            max_profit = round((width - debit_amt) * 100, 2)
            max_loss = round(debit_amt * 100, 2)
            be = long.strike + debit_amt if sign > 0 else long.strike - debit_amt
        candidate = _VResult(short, long, credit, max_profit, max_loss, round(be, 2))
        if max_loss <= ceiling:
            fitting.append(candidate)
        if fallback is None or max_loss < fallback.max_loss:
            fallback = candidate
    if not fitting:
        return fallback  # may exceed ceiling; G6 will judge
    # Among widths that fit the cap, choose the most liquid (max of the
    # least-liquid leg's OI) so we don't stretch into a dead outer strike;
    # tie-break toward the wider spread for better reward:risk.
    return max(
        fitting,
        key=lambda r: (min(r.short.oi, r.long.oi), abs(r.long.strike - r.short.strike)),
    )


def _otm_anchor(side: list[OptionContract], spot: float, sign: int) -> OptionContract | None:
    """Near-OTM strike: for puts (sign<0) the highest strike ≤ spot; for calls
    (sign>0) the lowest strike ≥ spot."""
    if sign < 0:  # puts, OTM below spot
        below = [c for c in side if c.strike <= spot and c.mid]
        return below[-1] if below else None
    above = [c for c in side if c.strike >= spot and c.mid]  # calls, OTM above
    return above[0] if above else None


def _vertical(
    chain: OptionChain, *, bullish: bool, credit: bool, ceiling: float,
    structure_type: StructureType, rationale: str,
) -> Structure | None:
    # Correct geometry: debit uses trade-direction type; credit uses opposite.
    if credit:
        opt = "put" if bullish else "call"
        sign = -1 if bullish else 1
    else:
        opt = "call" if bullish else "put"
        sign = 1 if bullish else -1

    r = _pick_vertical(chain, opt, credit, sign, ceiling)
    if r is None:
        return None

    if credit:
        legs = [
            Leg("sell", opt, r.short.strike, r.short.expiry),
            Leg("buy", opt, r.long.strike, r.long.expiry),
        ]
        short_delta = abs(r.short.delta) if r.short.delta is not None else None
    else:
        legs = [
            Leg("buy", opt, r.long.strike, r.long.expiry),
            Leg("sell", opt, r.short.strike, r.short.expiry),
        ]
        # For a debit, prob-of-profit tracks the long leg's delta (prob ITM).
        short_delta = abs(r.long.delta) if r.long.delta is not None else None

    oi = min(r.short.oi, r.long.oi)
    vol = min(r.short.volume, r.long.volume)
    spreads = [s for s in (r.short.spread_pct, r.long.spread_pct) if s is not None]
    spread_pct = max(spreads) if spreads else None

    return Structure(
        structure_type=structure_type,
        legs=legs,
        max_profit=r.max_profit,
        max_loss=r.max_loss,
        breakevens=[r.breakeven],
        rationale=rationale,
        is_defined_risk=True,
        is_speculative=(structure_type == StructureType.ZERO_DTE_SPREAD),
        contract_oi=oi, contract_volume=vol, spread_pct=spread_pct,
        short_delta=short_delta, expiry=r.short.expiry, from_chain=True,
    )


def _condor(chain: OptionChain, ceiling: float, rationale: str) -> Structure | None:
    # Bull put spread + bear call spread; only one side can lose, so each side
    # may use the full ceiling.
    put_leg = _pick_vertical(chain, "put", credit=True, sign=-1, ceiling=ceiling)
    call_leg = _pick_vertical(chain, "call", credit=True, sign=1, ceiling=ceiling)
    if put_leg is None or call_leg is None:
        return None
    legs = [
        Leg("sell", "put", put_leg.short.strike, put_leg.short.expiry),
        Leg("buy", "put", put_leg.long.strike, put_leg.long.expiry),
        Leg("sell", "call", call_leg.short.strike, call_leg.short.expiry),
        Leg("buy", "call", call_leg.long.strike, call_leg.long.expiry),
    ]
    total_credit = put_leg.max_profit + call_leg.max_profit
    max_loss = max(put_leg.max_loss, call_leg.max_loss) - min(put_leg.max_profit, call_leg.max_profit)
    max_loss = round(max(max_loss, 0.0), 2)
    contracts = [put_leg.short, put_leg.long, call_leg.short, call_leg.long]
    oi = min(c.oi for c in contracts)
    vol = min(c.volume for c in contracts)
    spreads = [c.spread_pct for c in contracts if c.spread_pct is not None]
    put_short_delta = abs(put_leg.short.delta) if put_leg.short.delta is not None else None
    call_short_delta = abs(call_leg.short.delta) if call_leg.short.delta is not None else None
    short_delta = max([d for d in (put_short_delta, call_short_delta) if d is not None], default=None)
    return Structure(
        structure_type=StructureType.IRON_CONDOR,
        legs=legs,
        max_profit=round(total_credit, 2),
        max_loss=max_loss,
        breakevens=[put_leg.breakeven, call_leg.breakeven],
        rationale=rationale,
        is_defined_risk=True,
        contract_oi=oi, contract_volume=vol,
        spread_pct=(max(spreads) if spreads else None),
        short_delta=short_delta, expiry=put_leg.short.expiry, from_chain=True,
    )

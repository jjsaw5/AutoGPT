"""Stage 4 — Structure selection (spec §7).

Match structure to vol regime *first*, then direction/horizon. Strikes and
risk figures are nominal placeholders derived from spot and a width heuristic;
they are refined against the live Robinhood chain at the human confirmation
step. Baked-in rules from §7 are enforced here (LEAPS deep-ITM by default,
0DTE always defined-risk, prefer spreads over naked long premium when IV rank
is elevated).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from ..config import Config
from ..models import (
    Candidate,
    Catalyst,
    Direction,
    Horizon,
    Leg,
    Structure,
    StructureType,
    Thesis,
    VolRegime,
)

_STRONG = 0.6
_MODERATE = 0.35

# Long premium has theoretically unbounded upside, so any "max profit" is a
# placeholder. For EV purposes we use a realistic *taken-profit* reward:risk
# target rather than a best-case number — chosen to sit inside the reward:risk
# range that defined-risk spreads span (~0.5-1.5) so pool-level EV normalization
# (§6a) doesn't systematically favor long options over spreads. Priors — §9.
_LONG_TARGET_RR = 1.3
_LEAPS_TARGET_RR = 1.5  # longer horizon / deep-ITM => a touch more room to run


@dataclass
class Plan:
    """Intended structure (regime-first decision), independent of realization."""

    kind: str            # long | leaps | debit_vertical | credit_vertical | iron_condor | zerodte
    call: bool = True
    credit: bool = False
    width_pct: float = 0.05
    rationale: str = ""


def plan_structure(thesis: Thesis, config: Config) -> Plan:
    """Decide the intended structure from the thesis (spec §7). Pure — no prices.

    Realized either against a live chain (real strikes) or via placeholders.
    """
    ivr_rich = float(config.structure.get("ivr_rich_min", 50))
    call = thesis.direction != Direction.BEARISH  # bullish/neutral default calls
    regime = thesis.vol_regime
    conviction = thesis.conviction
    ivr = thesis.iv_rank or 0.0

    # 0DTE: only when explicitly intraday.
    if thesis.horizon == Horizon.INTRADAY:
        return Plan("zerodte", call, credit=(regime == VolRegime.RICH), width_pct=0.02,
                    rationale="0DTE defined-risk (top-liquidity, weekly cap applies)")

    # Earnings overrides (directional only — a neutral earnings thesis falls
    # through to the regime logic: straddle if cheap, iron condor if rich).
    if thesis.direction != Direction.NEUTRAL and thesis.is_earnings_play \
            and thesis.days_to_catalyst is not None \
            and thesis.expected_move and thesis.implied_move:
        if thesis.expected_move > thesis.implied_move:
            return Plan("debit_vertical", call, credit=False,
                        rationale="earnings: expected move > implied — debit spread")
        return Plan("credit_vertical", call, credit=True,
                    rationale="earnings: harvest IV crush — credit spread")

    # Cheap vol => buy premium.
    if regime == VolRegime.CHEAP:
        if thesis.direction == Direction.NEUTRAL:
            # Selling premium (condor) in cheap vol is poorly compensated. If we
            # expect an expansion (a catalyst is present), buy vol via a
            # straddle; otherwise the best trade is no trade.
            has_catalyst = (
                thesis.catalyst != Catalyst.FLOW_ONLY
                and thesis.days_to_catalyst is not None
            )
            if has_catalyst:
                return Plan("straddle", rationale="cheap vol, neutral + catalyst — long straddle (buy expansion)")
            return Plan("skip", rationale="cheap vol, neutral, no catalyst — no edge selling premium; pass")
        if thesis.horizon == Horizon.LEAPS:
            return Plan("leaps", call, rationale="cheap vol, LEAPS deep-ITM stock replacement (~0.75Δ)")
        if conviction >= _STRONG and thesis.horizon == Horizon.SWING:
            if ivr >= ivr_rich:
                return Plan("debit_vertical", call, credit=False,
                            rationale="strong swing but elevated IVR — debit spread over naked long")
            return Plan("long", call, rationale="cheap vol, strong conviction — long premium")
        if conviction >= _MODERATE:
            return Plan("debit_vertical", call, credit=False,
                        rationale="cheap vol, moderate conviction — debit vertical")

    # Rich vol => sell premium.
    if regime == VolRegime.RICH:
        if thesis.direction == Direction.NEUTRAL:
            return Plan("iron_condor", rationale="rich vol, neutral — iron condor")
        if conviction >= _MODERATE:
            return Plan("credit_vertical", call, credit=True,
                        rationale="rich vol — sell premium via credit vertical")

    # Fair vol / low conviction fallback.
    if thesis.direction == Direction.NEUTRAL:
        return Plan("iron_condor", rationale="neutral, fair vol — iron condor")
    return Plan(
        "credit_vertical" if regime == VolRegime.RICH else "debit_vertical",
        call, credit=(regime == VolRegime.RICH),
        rationale="fair vol — directional vertical",
    )


def select_structure(
    candidate: Candidate, thesis: Thesis, config: Config, chain=None
) -> Structure:
    """Choose a structure for the candidate. Uses the live ``chain`` for real
    strikes/premiums when provided; otherwise nominal placeholders."""
    plan = plan_structure(thesis, config)
    ceiling = config.risk_high_conviction()

    if chain is not None:
        from .structure_chain import realize_from_chain
        realized = realize_from_chain(plan, chain, ceiling)
        if realized is not None:
            return realized

    price = candidate.price or candidate.signals.get("price") or 0.0
    return realize_placeholder(plan, price, ceiling)


def realize_placeholder(plan: Plan, price: float, ceiling: float) -> Structure:
    """Build a nominal structure from spot + width heuristics (no live chain)."""
    spread = partial(_defined_risk_spread, price, risk_ceiling=ceiling)

    if plan.kind == "skip":
        return Structure(structure_type=StructureType.NONE, legs=[], max_loss=None,
                         max_profit=None, rationale=plan.rationale)
    if plan.kind == "zerodte":
        return spread(call=plan.call, credit=plan.credit,
                      structure_type=StructureType.ZERO_DTE_SPREAD,
                      width_pct=plan.width_pct, rationale=plan.rationale)
    if plan.kind == "straddle":
        return _straddle(price, rationale=plan.rationale)
    if plan.kind == "leaps":
        return _leaps(price, call=plan.call)
    if plan.kind == "iron_condor":
        return _iron_condor(price, risk_ceiling=ceiling, rationale=plan.rationale)
    if plan.kind == "long":
        long = _long_option(price, call=plan.call)
        if long.max_loss is not None and long.max_loss <= ceiling:
            return long
        return spread(call=plan.call, credit=False,
                      structure_type=StructureType.DEBIT_VERTICAL,
                      rationale="cheap vol, strong conviction, but naked long exceeds risk cap — debit spread")
    # debit_vertical / credit_vertical
    st = StructureType.CREDIT_VERTICAL if plan.credit else StructureType.DEBIT_VERTICAL
    return spread(call=plan.call, credit=plan.credit, structure_type=st,
                  width_pct=plan.width_pct, rationale=plan.rationale)


# --- builders -----------------------------------------------------------------
def _round_strike(value: float) -> float:
    if value >= 100:
        return round(value)
    return round(value * 2) / 2  # nearest 0.5 for cheaper names


def _long_option(price: float, *, call: bool) -> Structure:
    strike = _round_strike(price)
    premium = round(price * 0.03, 2)  # nominal ATM premium estimate
    max_loss = premium * 100
    opt = "call" if call else "put"
    be = strike + premium if call else strike - premium
    return Structure(
        structure_type=StructureType.LONG_CALL if call else StructureType.LONG_PUT,
        legs=[Leg("buy", opt, strike, _exp("swing"))],
        max_profit=round(max_loss * _LONG_TARGET_RR, 2),  # realistic taken-profit target
        max_loss=round(max_loss, 2),
        breakevens=[round(be, 2)],
        rationale="cheap vol, strong conviction — long premium",
        is_defined_risk=True,
    )


def _straddle(price: float, *, rationale: str = "") -> Structure:
    """Long ATM call + put — a defined-risk long-vol play for cheap-vol neutrals."""
    strike = _round_strike(price)
    call_prem = round(price * 0.03, 2)
    put_prem = round(price * 0.03, 2)
    debit = (call_prem + put_prem) * 100
    return Structure(
        structure_type=StructureType.LONG_STRADDLE,
        legs=[Leg("buy", "call", strike, _exp("swing")), Leg("buy", "put", strike, _exp("swing"))],
        max_profit=round(debit * _LONG_TARGET_RR, 2),
        max_loss=round(debit, 2),
        breakevens=[round(strike - (call_prem + put_prem), 2), round(strike + (call_prem + put_prem), 2)],
        rationale=rationale or "cheap vol, neutral + catalyst — long straddle",
        is_defined_risk=True,
    )


def _leaps(price: float, *, call: bool) -> Structure:
    # Deep-ITM ~0.75 delta stock replacement.
    strike = _round_strike(price * (0.75 if call else 1.25))
    premium = round(price * 0.28, 2)
    max_loss = premium * 100
    opt = "call" if call else "put"
    be = strike + premium if call else strike - premium
    return Structure(
        structure_type=StructureType.LEAPS,
        legs=[Leg("buy", opt, strike, _exp("leaps"))],
        max_profit=round(max_loss * _LEAPS_TARGET_RR, 2),
        max_loss=round(max_loss, 2),
        breakevens=[round(be, 2)],
        rationale="cheap vol, LEAPS deep-ITM stock replacement (~0.75Δ)",
        is_defined_risk=True,
    )


def _fit_width(price: float, width_pct: float, per_point_loss: float, ceiling: float) -> float:
    """Largest sensible spread width whose 1-contract max loss fits the ceiling.

    ``per_point_loss`` is the $ risk per 1.0 of strike width (e.g. credit
    verticals risk ~$65/point, debit ~$40/point). Width is the smaller of the
    preferred %-of-spot width and the ceiling-implied cap, floored to a strike
    increment and at least one increment wide.
    """
    increment = 1.0 if price >= 100 else 0.5
    preferred = price * width_pct
    cap = ceiling / per_point_loss if per_point_loss > 0 else preferred
    width = min(preferred, cap)
    width = max(increment, (width // increment) * increment)
    return width


def _defined_risk_spread(
    price: float,
    *,
    call: bool,
    credit: bool,
    structure_type: StructureType,
    width_pct: float = 0.05,
    risk_ceiling: float = 500.0,
    rationale: str = "",
) -> Structure:
    per_point = 65.0 if credit else 40.0  # $ risk per 1.0 strike width
    width = _fit_width(price, width_pct, per_point, risk_ceiling)
    short_strike = _round_strike(price)
    exp = _exp("0dte" if structure_type == StructureType.ZERO_DTE_SPREAD else "swing")
    # Correct geometry: debit uses the trade-direction type (bull call / bear
    # put); credit uses the opposite (bull put / bear call).
    if credit:
        opt = "put" if call else "call"
        credit_amt = round(width * 0.35, 2)
        max_profit = credit_amt * 100
        max_loss = round((width - credit_amt) * 100, 2)
        # Sell near-OTM, buy protection one width further OTM (below for a bull
        # put, above for a bear call).
        long_strike = short_strike - width if call else short_strike + width
        legs = [
            Leg("sell", opt, short_strike, exp),
            Leg("buy", opt, long_strike, exp),
        ]
        be = short_strike - credit_amt if call else short_strike + credit_amt
    else:
        opt = "call" if call else "put"
        debit_amt = round(width * 0.40, 2)
        max_profit = round((width - debit_amt) * 100, 2)
        max_loss = debit_amt * 100
        long_strike = short_strike
        short_out = short_strike + width if call else short_strike - width
        legs = [
            Leg("buy", opt, long_strike, exp),
            Leg("sell", opt, short_out, exp),
        ]
        be = short_strike + debit_amt if call else short_strike - debit_amt

    return Structure(
        structure_type=structure_type,
        legs=legs,
        max_profit=round(max_profit, 2),
        max_loss=round(max_loss, 2),
        breakevens=[round(be, 2)],
        rationale=rationale,
        is_defined_risk=True,
        is_speculative=(structure_type == StructureType.ZERO_DTE_SPREAD),
    )


def _iron_condor(price: float, *, risk_ceiling: float = 500.0, rationale: str = "") -> Structure:
    width = max(_round_strike(price * 0.05), 1.0)
    # Each wing risks ~$70 per 1.0 of width; fit so 1-contract max loss ≤ ceiling.
    wing = _fit_width(price, 0.03, 70.0, risk_ceiling)
    put_short = _round_strike(price - width)
    call_short = _round_strike(price + width)
    exp = _exp("swing")
    credit_amt = round(wing * 0.30 * 2, 2)
    max_profit = credit_amt * 100
    max_loss = round((wing - (credit_amt / 2)) * 100, 2)
    legs = [
        Leg("sell", "put", put_short, exp),
        Leg("buy", "put", _round_strike(put_short - wing), exp),
        Leg("sell", "call", call_short, exp),
        Leg("buy", "call", _round_strike(call_short + wing), exp),
    ]
    return Structure(
        structure_type=StructureType.IRON_CONDOR,
        legs=legs,
        max_profit=round(max_profit, 2),
        max_loss=round(max_loss, 2),
        breakevens=[round(put_short - credit_amt / 2, 2), round(call_short + credit_amt / 2, 2)],
        rationale=rationale or "rich vol, neutral — iron condor",
        is_defined_risk=True,
    )


def _exp(horizon: str) -> str:
    """Nominal expiry descriptor (live calendar resolved at chain confirmation)."""
    return {
        "0dte": "0DTE",
        "swing": "~7-30d",
        "leaps": ">6mo",
    }.get(horizon, "~30d")

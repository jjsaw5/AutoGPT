"""Stage 4 — Structure selection (spec §7).

Match structure to vol regime *first*, then direction/horizon. Strikes and
risk figures are nominal placeholders derived from spot and a width heuristic;
they are refined against the live Robinhood chain at the human confirmation
step. Baked-in rules from §7 are enforced here (LEAPS deep-ITM by default,
0DTE always defined-risk, prefer spreads over naked long premium when IV rank
is elevated).
"""

from __future__ import annotations

from functools import partial

from ..config import Config
from ..models import (
    Candidate,
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


def select_structure(
    candidate: Candidate, thesis: Thesis, config: Config
) -> Structure:
    price = candidate.price or candidate.signals.get("price") or 0.0
    cfg = config.structure
    ivr_rich = float(cfg.get("ivr_rich_min", 50))
    call = thesis.direction != Direction.BEARISH  # bullish/neutral default calls

    # Inject the per-trade risk ceiling so spread/condor widths fit the account.
    ceiling = float(config.account.get("risk_high_conviction_max", 500))
    spread = partial(_defined_risk_spread, price, risk_ceiling=ceiling)
    condor = partial(_iron_condor, price, risk_ceiling=ceiling)

    # --- 0DTE: only when explicitly intraday, top-liquidity, strong flow -------
    if thesis.horizon == Horizon.INTRADAY:
        return spread(
            call=call, credit=(thesis.vol_regime == VolRegime.RICH),
            structure_type=StructureType.ZERO_DTE_SPREAD,
            width_pct=0.02,
            rationale="0DTE defined-risk (top-liquidity, weekly cap applies)",
        )

    regime = thesis.vol_regime
    conviction = thesis.conviction
    ivr = thesis.iv_rank or 0.0

    # --- Earnings event overrides ---------------------------------------------
    if thesis.is_earnings_play and thesis.days_to_catalyst is not None:
        if thesis.expected_move and thesis.implied_move:
            if thesis.expected_move > thesis.implied_move:
                return spread(
                    call=call, credit=False,
                    structure_type=StructureType.DEBIT_VERTICAL,
                    rationale="earnings: expected move > implied — debit spread",
                )
            return spread(
                call=call, credit=True,
                structure_type=StructureType.CREDIT_VERTICAL,
                rationale="earnings: harvest IV crush — credit spread",
            )

    # --- Cheap vol => buy premium ---------------------------------------------
    if regime == VolRegime.CHEAP:
        if thesis.direction == Direction.NEUTRAL:
            return condor(rationale="neutral, cheap vol fallback to condor")
        if thesis.horizon == Horizon.LEAPS:
            return _leaps(price, call=call)
        if conviction >= _STRONG and thesis.horizon == Horizon.SWING:
            # Prefer spreads over naked long premium when IV rank is elevated.
            if ivr >= ivr_rich:
                return spread(
                    call=call, credit=False,
                    structure_type=StructureType.DEBIT_VERTICAL,
                    rationale="strong swing but elevated IVR — debit spread over naked long",
                )
            # Prefer a naked long only when it fits the per-trade risk ceiling;
            # otherwise fall back to a debit vertical sized to the cap.
            long = _long_option(price, call=call)
            if long.max_loss is not None and long.max_loss <= ceiling:
                return long
            return spread(
                call=call, credit=False,
                structure_type=StructureType.DEBIT_VERTICAL,
                rationale="cheap vol, strong conviction, but naked long exceeds risk cap — debit spread",
            )
        if conviction >= _MODERATE:
            return spread(
                call=call, credit=False,
                structure_type=StructureType.DEBIT_VERTICAL,
                rationale="cheap vol, moderate conviction — debit vertical",
            )

    # --- Rich vol => sell premium ---------------------------------------------
    if regime == VolRegime.RICH:
        if thesis.direction == Direction.NEUTRAL:
            return condor(rationale="rich vol, neutral — iron condor")
        if conviction >= _MODERATE:
            return spread(
                call=call, credit=True,
                structure_type=StructureType.CREDIT_VERTICAL,
                rationale="rich vol — sell premium via credit vertical",
            )

    # --- Fair vol / low conviction: default to a directional debit spread -----
    if thesis.direction == Direction.NEUTRAL:
        return condor(rationale="neutral, fair vol — iron condor")
    return spread(
        call=call, credit=(regime == VolRegime.RICH),
        structure_type=(
            StructureType.CREDIT_VERTICAL if regime == VolRegime.RICH
            else StructureType.DEBIT_VERTICAL
        ),
        rationale="fair vol — directional vertical",
    )


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
    opt = "call" if call else "put"
    exp = _exp("0dte" if structure_type == StructureType.ZERO_DTE_SPREAD else "swing")

    if credit:
        credit_amt = round(width * 0.35, 2)
        max_profit = credit_amt * 100
        max_loss = round((width - credit_amt) * 100, 2)
        # Sell nearer strike, buy protection one width out.
        long_strike = short_strike + width if call else short_strike - width
        legs = [
            Leg("sell", opt, short_strike, exp),
            Leg("buy", opt, long_strike, exp),
        ]
        be = short_strike - credit_amt if call else short_strike + credit_amt
    else:
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

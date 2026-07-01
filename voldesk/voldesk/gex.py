"""GEX (gamma exposure) and related dealer-positioning math computed from a
raw options chain plus Black-Scholes greeks.

This module implements only the standard, well-defined GEX/DEX/VEX/CEX
math described in the vendor's own published methodology (net exposure per
strike, totals, ratios, the zero-gamma crossing strike, and OI walls). It
does **not** implement pTrans, nTrans, COTMP, COTMC, the 11-point "grade",
or "db_change" -- no published formula exists for those Vol Desk
proprietary levels. See the ``GexSnapshot`` docstring below and the
project README for details; they must continue to come from the vendor's
CSV export (``voldesk.ingest``) if you have it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Optional, Union

from .greeks import Greeks

OptionType = Literal["call", "put"]


def _normalize_option_type(option_type: str) -> OptionType:
    lowered = option_type.strip().lower()
    if lowered in ("call", "c"):
        return "call"
    if lowered in ("put", "p"):
        return "put"
    raise ValueError(f"Unrecognized option_type: {option_type!r}")


@dataclass
class OptionContract:
    """One normalized options-chain contract, ready for GEX math.

    ``greeks`` is optional so a contract can be constructed straight from
    a raw chain fetch before greeks have been computed and attached (e.g.
    by ``black_scholes_greeks``).
    """

    strike: float
    expiration: str
    option_type: OptionType
    open_interest: float
    volume: float
    implied_volatility: float
    greeks: Optional[Greeks] = None

    def __post_init__(self) -> None:
        self.option_type = _normalize_option_type(self.option_type)


@dataclass
class StrikeBreakdown:
    """Per-strike GEX/DEX/VEX/CEX and open-interest breakdown."""

    strike: float
    call_oi: float = 0.0
    put_oi: float = 0.0
    total_oi: float = 0.0

    call_gex: float = 0.0
    put_gex: float = 0.0
    net_gex: float = 0.0

    call_vgex: float = 0.0
    put_vgex: float = 0.0
    net_vgex: float = 0.0

    call_dex: float = 0.0
    put_dex: float = 0.0
    net_dex: float = 0.0

    call_vex: float = 0.0
    put_vex: float = 0.0
    net_vex: float = 0.0

    call_cex: float = 0.0
    put_cex: float = 0.0
    net_cex: float = 0.0


@dataclass
class GexSnapshot:
    """Aggregate GEX/dealer-positioning snapshot for one symbol.

    Fields with a documented formula (GEX/vGEX/DEX/VEX/CEX, their ratios,
    zero-gamma strike, OI walls) are computed by ``compute_gex_snapshot``
    below from standard, well-defined math.

    ``p_trans``, ``n_trans``, ``cotmp``, ``cotmc``, ``grade``, and
    ``db_change`` are Vol Desk *proprietary* levels for which no published
    formula exists. No published formula exists for these Vol Desk
    proprietary levels; they remain unset (None) here. Populate them via
    ``voldesk.ingest`` CSV loading if you obtain the vendor's actual
    methodology -- do not guess at a formula for them.
    """

    symbol: str
    spot: float
    as_of: Union[date, datetime, str]

    total_call_gex: float = 0.0
    total_put_gex: float = 0.0
    total_net_gex: float = 0.0
    gex_ratio: Optional[float] = None

    total_call_vgex: float = 0.0
    total_put_vgex: float = 0.0
    net_vgex: float = 0.0
    vgex_ratio: Optional[float] = None

    zero_gamma_strike: Optional[float] = None

    max_oi_strike: Optional[float] = None
    oi_ratio: Optional[float] = None

    net_dex: float = 0.0
    dex_ratio: Optional[float] = None

    net_vex: float = 0.0
    vex_ratio: Optional[float] = None

    net_cex: float = 0.0
    cex_ratio: Optional[float] = None

    per_strike: list[StrikeBreakdown] = field(default_factory=list)

    # Vol Desk proprietary levels -- NO PUBLISHED FORMULA. See class
    # docstring. Do not compute these; they must come from the vendor CSV.
    p_trans: Optional[float] = None
    n_trans: Optional[float] = None
    cotmp: Optional[float] = None
    cotmc: Optional[float] = None
    grade: Optional[int] = None
    db_change: Optional[float] = None


def _safe_ratio(call_total: float, put_total: float) -> Optional[float]:
    """call_total / (call_total + put_total), or None if the denominator is 0.

    DESIGN CHOICE: we return None (not 0.5) when total exposure is zero,
    because "no exposure either way" is not the same claim as "exposure is
    perfectly balanced" -- a caller that silently treats None as 0.5 is
    making that substitution explicitly rather than having it hidden here.
    """
    denom = call_total + put_total
    if denom == 0:
        return None
    return call_total / denom


def _zero_gamma_strike(sorted_strikes: list[StrikeBreakdown]) -> Optional[float]:
    """Interpolated strike where cumulative Net GEX crosses zero.

    Walks unique strikes in ascending order, accumulating Net GEX as we
    go (this is the standard "zero gamma level" construction: dealer net
    gamma exposure summed from the lowest strike upward). Finds the first
    adjacent pair of strikes where the cumulative total changes sign and
    linearly interpolates between them for the crossing point. Returns
    None if cumulative Net GEX never changes sign across the whole chain.
    """
    cumulative = 0.0
    prev_strike: Optional[float] = None
    prev_cumulative: Optional[float] = None

    for sb in sorted_strikes:
        cumulative += sb.net_gex

        if cumulative == 0:
            return sb.strike

        if prev_cumulative is not None and (prev_cumulative < 0) != (cumulative < 0):
            # Sign change between prev_strike and sb.strike -- interpolate.
            span = cumulative - prev_cumulative
            frac = -prev_cumulative / span
            return prev_strike + frac * (sb.strike - prev_strike)

        prev_strike = sb.strike
        prev_cumulative = cumulative

    return None


def compute_gex_snapshot(
    symbol: str,
    spot: float,
    contracts: list[OptionContract],
    as_of: Union[date, datetime, str],
) -> GexSnapshot:
    """Compute a full GEX/DEX/VEX/CEX/OI snapshot from a list of contracts.

    Every contract in ``contracts`` must have ``greeks`` populated (e.g.
    via ``black_scholes_greeks``) -- contracts missing greeks are treated
    as contributing zero to every greek-derived metric (their OI still
    counts toward the OI-wall math), which is the correct behavior when a
    caller intentionally passes greeks-less contracts for OI-only analysis
    but would silently understate GEX if that's not the intent, so make
    sure greeks are attached before calling this in the GEX-fetch path.
    """
    by_strike: dict[float, StrikeBreakdown] = {}

    for c in contracts:
        sb = by_strike.setdefault(c.strike, StrikeBreakdown(strike=c.strike))

        oi = c.open_interest
        vol = c.volume
        g = c.greeks

        if c.option_type == "call":
            sb.call_oi += oi
            if g is not None:
                sb.call_gex += g.gamma * oi * 100
                sb.call_vgex += g.gamma * vol * 100
                sb.call_dex += g.delta * oi * 100
                sb.call_vex += g.vanna * oi * 100
                sb.call_cex += g.charm * oi * 100
        else:
            sb.put_oi += oi
            if g is not None:
                sb.put_gex += g.gamma * oi * 100
                sb.put_vgex += g.gamma * vol * 100
                sb.put_dex += g.delta * oi * 100
                sb.put_vex += g.vanna * oi * 100
                sb.put_cex += g.charm * oi * 100

    for sb in by_strike.values():
        sb.total_oi = sb.call_oi + sb.put_oi
        sb.net_gex = sb.call_gex - sb.put_gex
        sb.net_vgex = sb.call_vgex - sb.put_vgex
        sb.net_dex = sb.call_dex - sb.put_dex
        sb.net_vex = sb.call_vex - sb.put_vex
        sb.net_cex = sb.call_cex - sb.put_cex

    sorted_strikes = sorted(by_strike.values(), key=lambda sb: sb.strike)

    total_call_gex = sum(sb.call_gex for sb in sorted_strikes)
    total_put_gex = sum(sb.put_gex for sb in sorted_strikes)
    total_call_vgex = sum(sb.call_vgex for sb in sorted_strikes)
    total_put_vgex = sum(sb.put_vgex for sb in sorted_strikes)
    total_call_dex = sum(sb.call_dex for sb in sorted_strikes)
    total_put_dex = sum(sb.put_dex for sb in sorted_strikes)
    total_call_vex = sum(sb.call_vex for sb in sorted_strikes)
    total_put_vex = sum(sb.put_vex for sb in sorted_strikes)
    total_call_cex = sum(sb.call_cex for sb in sorted_strikes)
    total_put_cex = sum(sb.put_cex for sb in sorted_strikes)
    total_call_oi = sum(sb.call_oi for sb in sorted_strikes)
    total_put_oi = sum(sb.put_oi for sb in sorted_strikes)

    max_oi_strike: Optional[float] = None
    if sorted_strikes:
        max_oi_strike = max(sorted_strikes, key=lambda sb: sb.total_oi).strike

    return GexSnapshot(
        symbol=symbol,
        spot=spot,
        as_of=as_of,
        total_call_gex=total_call_gex,
        total_put_gex=total_put_gex,
        total_net_gex=total_call_gex - total_put_gex,
        gex_ratio=_safe_ratio(total_call_gex, total_put_gex),
        total_call_vgex=total_call_vgex,
        total_put_vgex=total_put_vgex,
        net_vgex=total_call_vgex - total_put_vgex,
        vgex_ratio=_safe_ratio(total_call_vgex, total_put_vgex),
        zero_gamma_strike=_zero_gamma_strike(sorted_strikes),
        max_oi_strike=max_oi_strike,
        oi_ratio=_safe_ratio(total_call_oi, total_put_oi),
        net_dex=total_call_dex - total_put_dex,
        dex_ratio=_safe_ratio(total_call_dex, total_put_dex),
        net_vex=total_call_vex - total_put_vex,
        vex_ratio=_safe_ratio(total_call_vex, total_put_vex),
        net_cex=total_call_cex - total_put_cex,
        cex_ratio=_safe_ratio(total_call_cex, total_put_cex),
        per_strike=sorted_strikes,
    )

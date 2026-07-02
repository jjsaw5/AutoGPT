"""Stage 4 — Thesis construction (spec §4).

Assemble a structured :class:`Thesis` per candidate from its signal snapshot:
direction + conviction, vol regime (the pivotal field: buy vs sell premium),
horizon, catalyst, and implied-vs-expected move.

All logic is signal-driven with explicit fallbacks so a candidate with partial
data still yields a coherent (if low-conviction) thesis.
"""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..models import (
    Candidate,
    Catalyst,
    Direction,
    Horizon,
    Thesis,
    VolRegime,
)


def _signed_premium(signals: dict[str, Any]) -> float:
    """Net directional premium: positive = bullish, negative = bearish."""
    net = signals.get("net_prem", {})
    call = net.get("net_call_premium", 0.0) or 0.0
    put = net.get("net_put_premium", 0.0) or 0.0
    # Bullish when calls are bought (positive net call prem) and puts sold.
    return call - put


def _technical_bias(signals: dict[str, Any]) -> float:
    """-1..1 from price vs 50/200-day moving averages."""
    price = signals.get("price")
    ma50 = signals.get("price_avg_50")
    ma200 = signals.get("price_avg_200")
    if not price:
        return 0.0
    votes = []
    if ma50:
        votes.append(1.0 if price >= ma50 else -1.0)
    if ma200:
        votes.append(1.0 if price >= ma200 else -1.0)
    if not votes:
        return 0.0
    return sum(votes) / len(votes)


def _darkpool_bias(signals: dict[str, Any]) -> float:
    """-1..1 from dark-pool prints executed above vs below the NBBO midpoint."""
    prints = signals.get("darkpool", [])
    if not prints:
        return 0.0
    above = below = 0
    for p in prints:
        try:
            price = float(p.get("price"))
            bid = float(p.get("nbbo_bid"))
            ask = float(p.get("nbbo_ask"))
        except (TypeError, ValueError):
            continue
        mid = (bid + ask) / 2
        if price > mid:
            above += 1
        elif price < mid:
            below += 1
    total = above + below
    if total == 0:
        return 0.0
    return (above - below) / total


def build_thesis(candidate: Candidate, config: Config) -> Thesis:
    signals = candidate.signals
    struct_cfg = config.structure

    # --- Direction + conviction -----------------------------------------------
    prem = _signed_premium(signals)
    tech = _technical_bias(signals)
    dp = _darkpool_bias(signals)

    # Normalize premium into a -1..1 vote via a soft sign.
    prem_vote = 0.0
    if prem:
        prem_vote = max(-1.0, min(1.0, prem / 1_000_000.0))

    votes = [v for v in (prem_vote, tech, dp) if v != 0.0]
    net_vote = sum(votes) / len(votes) if votes else 0.0
    agreement = _agreement(prem_vote, tech, dp)

    if net_vote > 0.15:
        direction = Direction.BULLISH
    elif net_vote < -0.15:
        direction = Direction.BEARISH
    else:
        direction = Direction.NEUTRAL

    conviction = round(min(1.0, abs(net_vote) * 0.6 + agreement * 0.4), 3)

    supporting = []
    if prem_vote:
        supporting.append("net_premium")
    if tech:
        supporting.append("technical")
    if dp:
        supporting.append("darkpool")

    # --- Vol regime (pivotal) --------------------------------------------------
    iv_rank = signals.get("iv_rank")
    iv = signals.get("iv")
    rv = signals.get("rv")
    vol_regime = _classify_vol_regime(
        iv_rank, iv, rv,
        cheap_max=float(struct_cfg.get("ivr_cheap_max", 30)),
        rich_min=float(struct_cfg.get("ivr_rich_min", 50)),
    )

    # --- Catalyst + horizon ----------------------------------------------------
    days_to_earnings = signals.get("days_to_earnings")
    if days_to_earnings is not None and 0 <= days_to_earnings <= 14:
        catalyst = Catalyst.EARNINGS
        days_to_catalyst = days_to_earnings
    elif signals.get("flow_alerts"):
        catalyst = Catalyst.FLOW_ONLY
        days_to_catalyst = signals.get("days_to_catalyst")
    elif tech:
        catalyst = Catalyst.TECHNICAL
        days_to_catalyst = signals.get("days_to_catalyst")
    else:
        catalyst = Catalyst.NEWS
        days_to_catalyst = signals.get("days_to_catalyst")

    horizon = _pick_horizon(days_to_catalyst)

    # --- Implied vs expected move ---------------------------------------------
    # Both must be same-horizon fractions of spot to be comparable. The implied
    # move comes from the nearest term-structure expiry; the expected move is a
    # conviction-scaled version of it (high conviction => expect > implied, which
    # is what justifies long premium). If no implied move is available, fall back
    # to realized vol de-annualized to a ~1-month horizon. Placeholder heuristic
    # to be calibrated against logged outcomes (§9).
    implied_move = _nearest_implied_move(signals.get("term_structure", []))
    if implied_move is not None:
        expected_move = round(implied_move * (0.6 + 0.9 * conviction), 4)
    elif rv or iv:
        monthly = (rv or iv) * 0.29  # ~sqrt(21/252) de-annualization
        expected_move = round(monthly * (0.5 + conviction), 4)
    else:
        expected_move = None

    return Thesis(
        direction=direction,
        conviction=conviction,
        vol_regime=vol_regime,
        horizon=horizon,
        catalyst=catalyst,
        days_to_catalyst=days_to_catalyst,
        days_to_earnings=days_to_earnings,
        implied_move=implied_move,
        expected_move=expected_move,
        iv_rank=iv_rank,
        iv=iv,
        rv=rv,
        supporting_signals=supporting,
    )


def _agreement(*votes: float) -> float:
    """Fraction agreement among non-zero directional votes (0..1)."""
    nz = [v for v in votes if v != 0.0]
    if len(nz) < 2:
        return 0.0
    pos = sum(1 for v in nz if v > 0)
    neg = sum(1 for v in nz if v < 0)
    return max(pos, neg) / len(nz)


def _classify_vol_regime(
    iv_rank: float | None,
    iv: float | None,
    rv: float | None,
    *,
    cheap_max: float,
    rich_min: float,
) -> VolRegime:
    if iv_rank is None:
        # Fall back to IV-vs-RV alone when IV rank is missing.
        if iv is not None and rv is not None:
            if iv < rv * 0.9:
                return VolRegime.CHEAP
            if iv > rv * 1.2:
                return VolRegime.RICH
        return VolRegime.FAIR
    if iv_rank <= cheap_max:
        return VolRegime.CHEAP
    if iv_rank >= rich_min:
        return VolRegime.RICH
    return VolRegime.FAIR


def _pick_horizon(days_to_catalyst: int | None) -> Horizon:
    if days_to_catalyst is None:
        return Horizon.SWING
    if days_to_catalyst <= 0:
        return Horizon.INTRADAY
    if days_to_catalyst <= 10:
        return Horizon.SWING
    if days_to_catalyst <= 56:
        return Horizon.POSITION
    return Horizon.LEAPS


def _nearest_implied_move(term_structure: list[dict[str, Any]]) -> float | None:
    """Nearest non-0DTE implied move (fraction of spot) from the term structure."""
    best: float | None = None
    best_dte = None
    for row in term_structure:
        try:
            dte = int(row.get("dte"))
            move = float(row.get("implied_move_perc"))
        except (TypeError, ValueError):
            continue
        if dte < 1:
            continue
        if best_dte is None or dte < best_dte:
            best_dte = dte
            best = move
    return round(best, 4) if best is not None else None

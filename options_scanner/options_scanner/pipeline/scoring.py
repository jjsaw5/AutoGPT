"""Stage 3 — Scoring (spec §6).

Composite 0-100 = weighted sum of six normalized pillars. Each pillar is scored
0-100 by an explicit, documented heuristic. Per the spec these weights and
formulas are *priors* — hypotheses to be recalibrated against logged outcomes
(§9), not ground truth.
"""

from __future__ import annotations

from ..config import Config
from ..models import (
    Candidate,
    Direction,
    Score,
    Structure,
    StructureType,
    Thesis,
    VolRegime,
)

_BUY_PREMIUM = {
    StructureType.LONG_CALL,
    StructureType.LONG_PUT,
    StructureType.LEAPS,
    StructureType.LONG_STRADDLE,
    StructureType.DEBIT_VERTICAL,
}
_SELL_PREMIUM = {
    StructureType.CREDIT_VERTICAL,
    StructureType.IRON_CONDOR,
}

# Round-trip fee + slippage assumption per spread ($). Calibrated in §9 (P3/EV).
_FEE_SLIPPAGE = 5.0


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def score_candidate(
    candidate: Candidate,
    thesis: Thesis,
    structure: Structure,
    config: Config,
) -> Score:
    p1 = _p1_volatility_edge(thesis, structure)
    p2 = _p2_directional_signal(candidate, thesis)
    pop = _estimate_pop(thesis, structure)
    ev = _expected_value(pop, structure)
    p3 = _p3_expected_value(ev, structure)
    p4 = _p4_catalyst_quality(thesis, structure)
    p5 = _p5_liquidity(candidate)
    p6 = _p6_corroboration(thesis)

    w = config.weights
    composite = (
        w.get("P1", 25) * p1
        + w.get("P2", 22) * p2
        + w.get("P3", 20) * p3
        + w.get("P4", 18) * p4
        + w.get("P5", 10) * p5
        + w.get("P6", 5) * p6
    ) / max(1.0, sum(w.values()))

    return Score(
        p1=round(p1, 1), p2=round(p2, 1), p3=round(p3, 1),
        p4=round(p4, 1), p5=round(p5, 1), p6=round(p6, 1),
        composite=round(composite, 1),
        pop=round(pop, 3),
        expected_value=round(ev, 2),
    )


# --- P1 Volatility Edge -------------------------------------------------------
def _p1_volatility_edge(thesis: Thesis, structure: Structure) -> float:
    ivr = thesis.iv_rank
    if ivr is None:
        return 40.0  # neutral prior when IV rank unknown

    buying = structure.structure_type in _BUY_PREMIUM
    selling = structure.structure_type in _SELL_PREMIUM

    if buying:
        base = 100.0 - ivr  # cheaper vol => better for long premium
        if thesis.regime_iv_vs_rv() is not None:
            base = 0.5 * base + 0.5 * thesis.regime_iv_vs_rv()
        # Mismatch: buying premium while regime is rich => kill.
        if thesis.vol_regime == VolRegime.RICH:
            base *= 0.2
        return _clamp(base)

    if selling:
        if ivr < 50:
            return _clamp(ivr * 0.4)  # selling cheap vol has little edge
        base = ivr  # richer vol => better for short premium
        if thesis.regime_iv_vs_rv() is not None:
            # For selling, positive VRP (iv>rv) is good => invert.
            base = 0.5 * base + 0.5 * (100.0 - thesis.regime_iv_vs_rv())
        if thesis.vol_regime == VolRegime.CHEAP:
            base *= 0.3
        return _clamp(base)

    # 0DTE / other defined-risk spreads: mild, regime-neutral edge.
    return _clamp(50.0 + (ivr - 50.0) * 0.2)


# --- P2 Directional Signal ----------------------------------------------------
def _p2_directional_signal(candidate: Candidate, thesis: Thesis) -> float:
    if thesis.direction == Direction.NEUTRAL:
        # Neutral theses score on *stability*: low conviction directional pull.
        return _clamp(60.0 - abs(thesis.conviction) * 20.0 + 20.0)
    # Strength (conviction) × agreement (# supporting signals).
    strength = thesis.conviction * 100.0
    agreement_bonus = min(3, len(thesis.supporting_signals)) * 8.0
    return _clamp(strength * 0.7 + agreement_bonus)


# --- P3 Expected Value --------------------------------------------------------
def _estimate_pop(thesis: Thesis, structure: Structure) -> float:
    """Probability of profit (0-1). Uses the real short-leg delta from the live
    chain when available (credit: POP ≈ 1 − |Δ short|; long/debit: ≈ |Δ| ITM
    probability); otherwise falls back to a regime/conviction heuristic prior.
    """
    st = structure.structure_type

    # Real delta-based POP when the structure was built from the chain.
    if structure.short_delta is not None:
        d = min(0.99, max(0.01, structure.short_delta))
        if st in _SELL_PREMIUM:
            return round(1.0 - d, 3)
        if st in _BUY_PREMIUM:
            return round(d, 3)
        if st == StructureType.ZERO_DTE_SPREAD:
            return round(1.0 - d if structure.max_loss and structure.max_profit
                         and structure.max_loss > structure.max_profit else d, 3)
    if st in _SELL_PREMIUM:
        base = 0.62 + 0.10 * thesis.conviction
        if st == StructureType.IRON_CONDOR:
            base = 0.65
        return min(0.90, base)
    if st in _BUY_PREMIUM:
        base = 0.42 + 0.15 * thesis.conviction
        # Long premium only justified when expected move exceeds implied.
        if thesis.expected_move and thesis.implied_move:
            if thesis.expected_move > thesis.implied_move:
                base += 0.08
            else:
                base -= 0.08
        return max(0.20, min(0.75, base))
    if st == StructureType.ZERO_DTE_SPREAD:
        return 0.55
    return 0.5


def _expected_value(pop: float, structure: Structure) -> float:
    win = structure.max_profit or 0.0
    loss = structure.max_loss or 0.0
    return pop * win - (1 - pop) * loss - _FEE_SLIPPAGE


def _p3_expected_value(ev: float, structure: Structure) -> float:
    """Map EV/risk ratio to 0-100. Pool-level normalization happens in ranking."""
    risk = structure.max_loss or 0.0
    if risk <= 0:
        return 50.0 if ev >= 0 else 30.0
    ratio = ev / risk  # EV as a fraction of risk
    # ratio of 0 => 50; +0.5 => ~85; -0.5 => ~15.
    return _clamp(50.0 + ratio * 70.0)


# --- P4 Catalyst Quality ------------------------------------------------------
_CATALYST_RELIABILITY = {
    "earnings": 0.9,
    "fda": 0.85,
    "macro": 0.7,
    "news": 0.55,
    "technical": 0.5,
    "flow_only": 0.45,
}


def _p4_catalyst_quality(thesis: Thesis, structure: Structure) -> float:
    reliability = _CATALYST_RELIABILITY.get(thesis.catalyst.value, 0.5)
    # Proximity fit: closer catalyst => higher, but 0-day for non-0DTE is risky.
    dtc = thesis.days_to_catalyst
    if dtc is None:
        proximity = 0.5
    elif dtc < 0:
        proximity = 0.3  # catalyst passed
    elif dtc <= 5:
        proximity = 1.0
    elif dtc <= 14:
        proximity = 0.8
    elif dtc <= 45:
        proximity = 0.55
    else:
        proximity = 0.35

    base = reliability * proximity * 100.0

    # Earnings: bonus if expected move > implied; penalty if long premium reverse.
    if thesis.is_earnings_play and thesis.expected_move and thesis.implied_move:
        buying = structure.structure_type in _BUY_PREMIUM
        if thesis.expected_move > thesis.implied_move:
            base += 10.0
        elif buying:
            base -= 15.0
    return _clamp(base)


# --- P5 Liquidity / Execution -------------------------------------------------
def _p5_liquidity(candidate: Candidate) -> float:
    """Continuous version of G1/G2: tighter spread %, higher OI/vol => higher."""
    signals = candidate.signals
    oi = None
    vol = None
    for alert in signals.get("flow_alerts", []):
        try:
            oi = max(oi or 0, float(alert.get("open_interest")))
            vol = max(vol or 0, float(alert.get("volume")))
        except (TypeError, ValueError):
            continue
    score = 50.0
    if oi:
        score += min(25.0, (oi / 5000.0) * 25.0)
    if vol:
        score += min(25.0, (vol / 2000.0) * 25.0)
    return _clamp(score)


# --- P6 Corroboration ---------------------------------------------------------
def _p6_corroboration(thesis: Thesis) -> float:
    n = len(set(thesis.supporting_signals))
    return {0: 0.0, 1: 20.0, 2: 50.0, 3: 75.0}.get(n, 100.0)

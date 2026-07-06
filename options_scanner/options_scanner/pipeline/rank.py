"""Stage 5 — Ranking, decision and sizing (spec §6b, §5 G6/G7).

Applies the GO/WATCH/PASS thresholds, normalizes P3/EV across the day's pool,
sizes GO candidates within the tiered risk caps, and attaches a one-line
"why this trade" plus the single biggest risk.
"""

from __future__ import annotations

from ..config import Config
from ..models import Decision, Direction, EvaluatedCandidate, StructureType, VolRegime

_SELL_PREMIUM = {StructureType.CREDIT_VERTICAL, StructureType.IRON_CONDOR}


def rank_and_decide(
    evaluated: list[EvaluatedCandidate], config: Config, *, regime=None
) -> list[EvaluatedCandidate]:
    if not evaluated:
        return []

    _normalize_pool_ev(evaluated, config)

    max_adj = float(config.market_context.get("max_composite_adjustment", 0))
    for ec in evaluated:
        _apply_regime(ec, regime, max_adj)

    go = config.go_threshold
    watch = config.watch_threshold
    for ec in evaluated:
        _decide(ec, go, watch, config)

    evaluated.sort(key=lambda ec: (_decision_order(ec.decision), -ec.effective_composite))
    return evaluated


def _apply_regime(ec: EvaluatedCandidate, regime, max_adj: float) -> None:
    """Nudge the composite when the thesis aligns with / fights the market regime.

    Bullish thesis in a risk-on tape (or bearish in risk-off) gets a bonus;
    fighting the regime gets a penalty, scaled by how strong the regime is.
    """
    if regime is None or max_adj <= 0:
        return
    tdir = 1 if ec.thesis.direction == Direction.BULLISH else (
        -1 if ec.thesis.direction == Direction.BEARISH else 0)
    mdir = regime.direction
    if tdir == 0 or mdir == 0:
        return
    strength = min(1.0, abs(regime.composite) / 0.5)
    ec.regime_adj = round(tdir * mdir * max_adj * strength, 1)


def _decision_order(decision: Decision) -> int:
    return {Decision.GO: 0, Decision.WATCH: 1, Decision.PASS: 2}[decision]


def _normalize_pool_ev(evaluated: list[EvaluatedCandidate], config: Config) -> None:
    """Rescale EV across the pool into P3 and recompute the composite (§6a)."""
    evs = [ec.score.expected_value for ec in evaluated]
    lo, hi = min(evs), max(evs)
    if hi - lo < 1e-9:
        return  # degenerate pool; keep per-candidate P3
    w = config.weights
    denom = max(1.0, sum(w.values()))
    for ec in evaluated:
        norm = (ec.score.expected_value - lo) / (hi - lo) * 100.0
        s = ec.score
        s.p3 = round(norm, 1)
        s.composite = round(
            (
                w.get("P1", 25) * s.p1 + w.get("P2", 22) * s.p2
                + w.get("P3", 20) * s.p3 + w.get("P4", 18) * s.p4
                + w.get("P5", 10) * s.p5 + w.get("P6", 5) * s.p6
            )
            / denom,
            1,
        )


def _decide(
    ec: EvaluatedCandidate, go: float, watch: float, config: Config
) -> None:
    # No-trade structures (e.g. cheap-vol neutral with no catalyst) are PASS.
    if ec.structure.structure_type == StructureType.NONE:
        ec.decision = Decision.PASS
        ec.suggested_size = 0.0
        ec.size_tier = "none"
        ec.why = ec.structure.rationale or "no tradeable structure"
        ec.biggest_risk = "—"
        return
    composite = ec.effective_composite
    gates_pass = ec.gates.passed
    ev_positive = ec.score.expected_value > 0

    # All three required for GO (§6b).
    if composite >= go and gates_pass and ev_positive:
        ec.decision = Decision.GO
        _size(ec, go, config)
    elif composite >= watch:
        ec.decision = Decision.WATCH
        ec.suggested_size = 0.0
        ec.size_tier = "none"
    else:
        ec.decision = Decision.PASS
        ec.suggested_size = 0.0
        ec.size_tier = "none"

    ec.why = _why(ec)
    ec.biggest_risk = _biggest_risk(ec)


def _size(ec: EvaluatedCandidate, go: float, config: Config) -> None:
    """Size scales with score above the GO line, capped by G6 tiered ceilings."""
    standard = config.risk_standard()
    high = config.risk_high_conviction()

    composite = ec.effective_composite
    fraction = min(1.0, (composite - go) / max(1.0, 100.0 - go))
    # High-conviction ceiling reserved for top-decile composite.
    ceiling = high if composite >= 85 else standard
    target = standard + fraction * (ceiling - standard)

    per_contract = ec.structure.max_loss or 0.0
    if per_contract <= 0:
        ec.suggested_size = round(target, 2)
        ec.size_tier = "high_conviction" if ceiling == high else "standard"
        return
    contracts = int(target // per_contract)
    if contracts < 1:
        # One contract already exceeds the target risk; G6 ceiling still governs.
        contracts = 1 if per_contract <= high else 0
    ec.suggested_size = round(contracts * per_contract, 2)
    ec.size_tier = "high_conviction" if ceiling == high else "standard"


def _why(ec: EvaluatedCandidate) -> str:
    t = ec.thesis
    regime = t.vol_regime.value
    verb = "sell" if ec.structure.structure_type in _SELL_PREMIUM else "buy"
    cat = t.catalyst.value
    return (
        f"{t.direction.value} {ec.ticker}; {regime} vol → {verb} premium via "
        f"{ec.structure.structure_type.value}; catalyst={cat}"
        f"{f' in {t.days_to_catalyst}d' if t.days_to_catalyst is not None else ''}"
    )


def _biggest_risk(ec: EvaluatedCandidate) -> str:
    t = ec.thesis
    if ec.regime_adj < 0:
        return f"Fights the market regime (macro nudge {ec.regime_adj:+.0f})."
    if t.is_earnings_play:
        return "Earnings binary — IV crush / gap through the spread."
    if t.vol_regime == VolRegime.CHEAP and ec.structure.structure_type.value.startswith("long"):
        return "Theta decay if the move doesn't materialize quickly."
    if t.conviction < 0.4:
        return "Thin directional corroboration — single-signal thesis."
    if ec.gates.failures:
        return f"Gate risk: {', '.join(f.gate_id for f in ec.gates.failures)}."
    return "Adverse move beyond the short strike / defined max loss."

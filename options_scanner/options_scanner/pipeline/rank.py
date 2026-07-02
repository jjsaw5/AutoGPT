"""Stage 5 — Ranking, decision and sizing (spec §6b, §5 G6/G7).

Applies the GO/WATCH/PASS thresholds, normalizes P3/EV across the day's pool,
sizes GO candidates within the tiered risk caps, and attaches a one-line
"why this trade" plus the single biggest risk.
"""

from __future__ import annotations

from ..config import Config
from ..models import Decision, EvaluatedCandidate, StructureType, VolRegime

_SELL_PREMIUM = {StructureType.CREDIT_VERTICAL, StructureType.IRON_CONDOR}


def rank_and_decide(
    evaluated: list[EvaluatedCandidate], config: Config
) -> list[EvaluatedCandidate]:
    if not evaluated:
        return []

    _normalize_pool_ev(evaluated, config)

    go = config.go_threshold
    watch = config.watch_threshold
    for ec in evaluated:
        _decide(ec, go, watch, config)

    evaluated.sort(key=lambda ec: (_decision_order(ec.decision), -ec.score.composite))
    return evaluated


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
    composite = ec.score.composite
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
    acct = config.account
    standard = float(acct.get("risk_standard_max", 200))
    high = float(acct.get("risk_high_conviction_max", 500))

    composite = ec.score.composite
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
    if t.is_earnings_play:
        return "Earnings binary — IV crush / gap through the spread."
    if t.vol_regime == VolRegime.CHEAP and ec.structure.structure_type.value.startswith("long"):
        return "Theta decay if the move doesn't materialize quickly."
    if t.conviction < 0.4:
        return "Thin directional corroboration — single-signal thesis."
    if ec.gates.failures:
        return f"Gate risk: {', '.join(f.gate_id for f in ec.gates.failures)}."
    return "Adverse move beyond the short strike / defined max loss."

"""The five entry filters for the Vol Desk setup, and the setup classifier."""

from __future__ import annotations

from .models import FilterResult, GammaScreenRow, SetupClassification, SetupEvaluation

GRADE_HARD_BLOCK_MAX = 8  # grade <= 8 is a hard block, no exceptions
GRADE_MIN_PASS = 9  # grade >= 9 required

DB_CHANGE_THRESHOLD_DEFAULT = 0.50
DB_CHANGE_THRESHOLD_GRADE_11_DEEP = 0.30

COTMP_CUSHION_THRESHOLD_DEFAULT = 2.0  # percent
COTMP_CUSHION_THRESHOLD_RELAXED = 1.0  # percent, Grade 11 DEEP or high db_change

RISK_REWARD_MIN = 2.0

PENDING_ZONE_PCT = 0.995  # spot >= p_trans * 0.995 and spot < p_trans -> PENDING


def _filter_grade(row: GammaScreenRow) -> FilterResult:
    """Filter 1: Grade >= 9/11 hard block at <= 8, no exceptions."""
    passed = row.grade >= GRADE_MIN_PASS
    reason = (
        f"grade={row.grade} >= {GRADE_MIN_PASS} required"
        if passed
        else f"grade={row.grade} <= {GRADE_HARD_BLOCK_MAX} is a hard block"
    )
    return FilterResult(name="grade", passed=passed, reason=reason)


def _filter_db_change(row: GammaScreenRow) -> FilterResult:
    """Filter 2: db_change >= 0.50 (0.30 for Grade 11 DEEP), exempt if db is
    pegged at 1.00 for two consecutive sessions (sustained, not recovering)."""
    sustained_peg = (
        row.db_prior_2_sessions is not None
        and row.db_prior_2_sessions == 1.00
        and row.dealer_delta_balance == 1.00
    )
    if sustained_peg:
        return FilterResult(
            name="db_change",
            passed=True,
            reason=(
                f"exempt: db pegged at 1.00 for two consecutive sessions "
                f"(prior={row.db_prior_2_sessions}, current={row.dealer_delta_balance})"
            ),
        )

    threshold = (
        DB_CHANGE_THRESHOLD_GRADE_11_DEEP
        if row.grade_11_deep
        else DB_CHANGE_THRESHOLD_DEFAULT
    )
    passed = row.db_change >= threshold
    reason = (
        f"db_change={row.db_change:.2f} >= {threshold:.2f} threshold "
        f"({'Grade 11 DEEP' if row.grade_11_deep else 'default'})"
        if passed
        else (
            f"db_change={row.db_change:.2f} < {threshold:.2f} threshold "
            f"({'Grade 11 DEEP' if row.grade_11_deep else 'default'})"
        )
    )
    return FilterResult(name="db_change", passed=passed, reason=reason)


def _filter_cotmp_cushion(row: GammaScreenRow) -> tuple[FilterResult, float]:
    """Filter 3: COTMP cushion = (spot - cotmp) / cotmp * 100 >= 2.0%, relaxed to
    1.0% for Grade 11 DEEP OR "high db_change". ASSUMPTION: "high db_change" reuses
    the base filter-2 threshold (0.50) rather than a separately-specified bar."""
    cushion_pct = (row.spot - row.cotmp) / row.cotmp * 100 if row.cotmp else float("nan")

    high_db_change = row.db_change >= DB_CHANGE_THRESHOLD_DEFAULT
    relaxed = row.grade_11_deep or high_db_change
    threshold = COTMP_CUSHION_THRESHOLD_RELAXED if relaxed else COTMP_CUSHION_THRESHOLD_DEFAULT

    passed = cushion_pct >= threshold
    qualifier = "Grade 11 DEEP/high db_change" if relaxed else "default"
    reason = (
        f"cotmp_cushion={cushion_pct:.2f}% "
        f"{'>=' if passed else '<'} {threshold:.1f}% threshold ({qualifier})"
    )
    return FilterResult(name="cotmp_cushion", passed=passed, reason=reason), cushion_pct


def _filter_spike_crash(row: GammaScreenRow) -> FilterResult:
    """Filter 4: spike_crash_pattern True is a hard block regardless of everything
    else. Evaluated independently so it always gets its own FilterResult."""
    passed = not row.spike_crash_pattern
    reason = (
        "spike_crash_pattern is False"
        if passed
        else "spike_crash_pattern is True: +GEX target is a prior spike high with "
        "institutional selling already there -- hard block"
    )
    return FilterResult(name="spike_crash_pattern", passed=passed, reason=reason)


def _filter_risk_reward(row: GammaScreenRow) -> tuple[FilterResult, float | None]:
    """Filter 5: R/R = (plus_gex - spot) / (spot - p_trans) >= 2.0. Undefined
    (and treated as failed) if spot has not yet cleared p_trans."""
    if row.spot <= row.p_trans:
        return (
            FilterResult(
                name="risk_reward",
                passed=False,
                reason="spot has not cleared pTrans",
            ),
            None,
        )

    rr = (row.plus_gex - row.spot) / (row.spot - row.p_trans)
    passed = rr >= RISK_REWARD_MIN
    reason = f"R/R={rr:.2f} {'>=' if passed else '<'} {RISK_REWARD_MIN:.1f} required"
    return FilterResult(name="risk_reward", passed=passed, reason=reason), rr


def evaluate_setup(row: GammaScreenRow) -> SetupEvaluation:
    """Run all five entry filters (always, no short-circuiting) and classify.

    ASSUMPTION: filter 5 (R/R) is undefined -- not failed -- when spot has not
    cleared pTrans, since the spec separately defines a PENDING classification
    for that exact zone. If R/R's "undefined" state were treated as a hard
    filter failure like the others, PENDING would be unreachable (any_failed
    would always be True below pTrans), contradicting the PENDING branch below.
    So: filters 1-4 (grade, db_change, cotmp_cushion, spike_crash_pattern) are
    hard pass/fail gates; filter 5 hard-fails the setup only when spot has
    cleared pTrans and R/R is actually below the 2.0 minimum. When spot hasn't
    cleared pTrans, filter 5's FilterResult is still recorded (marked not
    passed, for visibility) but does not by itself force BLOCKED -- proximity
    to pTrans decides PENDING vs BLOCKED instead.
    """
    grade_result = _filter_grade(row)
    db_change_result = _filter_db_change(row)
    cotmp_result, cushion_pct = _filter_cotmp_cushion(row)
    spike_result = _filter_spike_crash(row)
    rr_result, rr_value = _filter_risk_reward(row)

    filters = [grade_result, db_change_result, cotmp_result, spike_result, rr_result]

    hard_gates = [grade_result, db_change_result, cotmp_result, spike_result]
    any_hard_gate_failed = any(not f.passed for f in hard_gates)
    spot_cleared_p_trans = row.spot > row.p_trans
    rr_hard_failed = spot_cleared_p_trans and not rr_result.passed

    if any_hard_gate_failed or rr_hard_failed:
        classification = SetupClassification.BLOCKED
    elif row.spot >= row.p_trans:
        classification = SetupClassification.CONFIRMED
    elif row.spot >= row.p_trans * PENDING_ZONE_PCT:
        classification = SetupClassification.PENDING
    else:
        classification = SetupClassification.BLOCKED
        filters.append(
            FilterResult(name="proximity", passed=False, reason="not near pTrans")
        )

    return SetupEvaluation(
        symbol=row.symbol,
        classification=classification,
        filters=filters,
        risk_reward=rr_value,
        cotmp_cushion_pct=cushion_pct,
    )

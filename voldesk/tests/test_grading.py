"""Tests for the five entry filters and the setup classifier."""

from __future__ import annotations

from conftest import make_row

from voldesk.grading import evaluate_setup
from voldesk.models import SetupClassification


def _filter(evaluation, name):
    return next(f for f in evaluation.filters if f.name == name)


class TestGradeFilter:
    def test_grade_9_passes(self):
        row = make_row(grade=9)
        ev = evaluate_setup(row)
        assert _filter(ev, "grade").passed is True

    def test_grade_11_passes(self):
        row = make_row(grade=11)
        ev = evaluate_setup(row)
        assert _filter(ev, "grade").passed is True

    def test_grade_8_hard_blocked(self):
        row = make_row(grade=8)
        ev = evaluate_setup(row)
        assert _filter(ev, "grade").passed is False
        assert ev.classification == SetupClassification.BLOCKED

    def test_grade_0_hard_blocked_no_exceptions(self):
        # Even with everything else favorable, grade 0 is a hard block.
        row = make_row(grade=0, grade_11_deep=True)
        ev = evaluate_setup(row)
        assert _filter(ev, "grade").passed is False
        assert ev.classification == SetupClassification.BLOCKED


class TestDbChangeFilter:
    def test_default_threshold_pass(self):
        row = make_row(db_change=0.50, grade_11_deep=False)
        ev = evaluate_setup(row)
        assert _filter(ev, "db_change").passed is True

    def test_default_threshold_fail(self):
        row = make_row(db_change=0.49, grade_11_deep=False)
        ev = evaluate_setup(row)
        assert _filter(ev, "db_change").passed is False

    def test_grade_11_deep_relaxed_threshold_pass(self):
        row = make_row(db_change=0.30, grade_11_deep=True, grade=11)
        ev = evaluate_setup(row)
        assert _filter(ev, "db_change").passed is True

    def test_grade_11_deep_relaxed_threshold_fail_below(self):
        row = make_row(db_change=0.29, grade_11_deep=True, grade=11)
        ev = evaluate_setup(row)
        assert _filter(ev, "db_change").passed is False

    def test_sustained_peg_exemption_auto_passes(self):
        # db pegged at 1.00 for two consecutive sessions is exempt entirely,
        # even though db_change itself is far below any threshold.
        row = make_row(
            dealer_delta_balance=1.00,
            db_prior_2_sessions=1.00,
            db_change=0.0,
        )
        ev = evaluate_setup(row)
        result = _filter(ev, "db_change")
        assert result.passed is True
        assert "pegged" in result.reason

    def test_recovering_not_sustained_does_not_exempt(self):
        # db == 1.00 now but prior session was NOT 1.00 -- "recovering", not
        # "sustained" -- so the exemption must not apply.
        row = make_row(
            dealer_delta_balance=1.00,
            db_prior_2_sessions=0.40,
            db_change=0.10,
        )
        ev = evaluate_setup(row)
        result = _filter(ev, "db_change")
        assert result.passed is False


class TestCotmpCushionFilter:
    def test_default_threshold_pass(self):
        # cushion = (102 - 100) / 100 * 100 = 2.0%
        row = make_row(spot=102.0, cotmp=100.0, db_change=0.10, grade_11_deep=False)
        ev = evaluate_setup(row)
        assert _filter(ev, "cotmp_cushion").passed is True
        assert ev.cotmp_cushion_pct == 2.0

    def test_default_threshold_fail(self):
        row = make_row(spot=100.5, cotmp=100.0, db_change=0.10, grade_11_deep=False)
        ev = evaluate_setup(row)
        assert _filter(ev, "cotmp_cushion").passed is False

    def test_grade_11_deep_relaxed_threshold_pass(self):
        # cushion = 1.0%, would fail default 2.0% bar but passes relaxed 1.0% bar.
        row = make_row(
            spot=101.0, cotmp=100.0, db_change=0.10, grade_11_deep=True, grade=11
        )
        ev = evaluate_setup(row)
        assert _filter(ev, "cotmp_cushion").passed is True

    def test_high_db_change_relaxed_threshold_pass(self):
        # High db_change (>= 0.50) also relaxes the cushion bar to 1.0%.
        row = make_row(spot=101.0, cotmp=100.0, db_change=0.60, grade_11_deep=False)
        ev = evaluate_setup(row)
        assert _filter(ev, "cotmp_cushion").passed is True


class TestSpikeCrashFilter:
    def test_false_passes(self):
        row = make_row(spike_crash_pattern=False)
        ev = evaluate_setup(row)
        assert _filter(ev, "spike_crash_pattern").passed is True

    def test_true_hard_blocks_overriding_everything_else(self):
        # Every other filter would pass, but spike_crash_pattern overrides all.
        row = make_row(
            grade=11,
            grade_11_deep=True,
            db_change=0.90,
            spot=110.0,
            cotmp=90.0,
            p_trans=100.0,
            plus_gex=200.0,
            spike_crash_pattern=True,
        )
        ev = evaluate_setup(row)
        assert _filter(ev, "spike_crash_pattern").passed is False
        assert ev.classification == SetupClassification.BLOCKED
        # All other filters still get evaluated and recorded.
        assert len(ev.filters) >= 5


class TestRiskRewardFilter:
    def test_rr_meets_minimum_passes(self):
        # R/R = (110 - 101) / (101 - 100) = 9.0
        row = make_row(spot=101.0, p_trans=100.0, plus_gex=110.0)
        ev = evaluate_setup(row)
        assert _filter(ev, "risk_reward").passed is True
        assert ev.risk_reward == 9.0

    def test_rr_below_minimum_fails(self):
        # R/R = (103 - 101) / (101 - 100) = 2.0... make it fail: (100.5-101)/(101-100)<2
        row = make_row(spot=101.0, p_trans=100.0, plus_gex=101.5)
        ev = evaluate_setup(row)
        assert _filter(ev, "risk_reward").passed is False

    def test_spot_below_p_trans_is_undefined_and_fails(self):
        row = make_row(spot=99.0, p_trans=100.0)
        ev = evaluate_setup(row)
        result = _filter(ev, "risk_reward")
        assert result.passed is False
        assert result.reason == "spot has not cleared pTrans"
        assert ev.risk_reward is None

    def test_spot_equal_p_trans_is_undefined_and_fails(self):
        row = make_row(spot=100.0, p_trans=100.0)
        ev = evaluate_setup(row)
        result = _filter(ev, "risk_reward")
        assert result.passed is False


class TestClassification:
    def test_all_pass_and_spot_above_p_trans_is_confirmed(self):
        row = make_row(spot=101.0, p_trans=100.0)
        ev = evaluate_setup(row)
        assert ev.classification == SetupClassification.CONFIRMED

    def test_any_fail_is_blocked(self):
        row = make_row(grade=5)
        ev = evaluate_setup(row)
        assert ev.classification == SetupClassification.BLOCKED

    def test_pending_zone_below_p_trans_within_half_percent(self):
        # spot = 99.6 is within 0.5% below p_trans=100 (>= 99.5). R/R is undefined
        # here (spot hasn't cleared pTrans) but per the documented assumption in
        # grading.py, that undefined state does not itself force BLOCKED -- it
        # falls through to the proximity check, which lands in PENDING.
        row = make_row(spot=99.6, p_trans=100.0, plus_gex=110.0, cotmp=98.0)
        ev = evaluate_setup(row)
        assert ev.classification == SetupClassification.PENDING
        assert _filter(ev, "risk_reward").reason == "spot has not cleared pTrans"
        assert _filter(ev, "risk_reward").passed is False

    def test_far_below_p_trans_is_blocked_not_near(self):
        row = make_row(spot=90.0, p_trans=100.0)
        ev = evaluate_setup(row)
        assert ev.classification == SetupClassification.BLOCKED

    def test_all_five_filters_always_present(self):
        row = make_row(grade=0, spike_crash_pattern=True, spot=50.0, p_trans=100.0)
        ev = evaluate_setup(row)
        names = {f.name for f in ev.filters}
        assert {"grade", "db_change", "cotmp_cushion", "spike_crash_pattern", "risk_reward"} <= names

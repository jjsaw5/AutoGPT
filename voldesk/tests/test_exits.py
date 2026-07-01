"""Tests for the position exit/stop framework and take-profit logic."""

from __future__ import annotations

from datetime import date

from voldesk.exits import evaluate_exits, evaluate_take_profit
from voldesk.models import ExitUrgency, Position, PositionStatus


def make_position(**overrides) -> Position:
    defaults = dict(
        symbol="TEST",
        entry_price=100.0,
        entry_date=date(2026, 6, 1),
        p_trans=100.0,
        n_trans=90.0,
        t1_target=120.0,
        t2_target=None,
    )
    defaults.update(overrides)
    return Position(**defaults)


class TestStop1ClosedBelowNTrans:
    def test_triggers_next_open_exit(self):
        position = make_position()
        decision = evaluate_exits(
            position, current_price=95.0, current_date=date(2026, 6, 2), closed_below_n_trans=True
        )
        assert decision.should_exit is True
        assert decision.exit_urgency == ExitUrgency.NEXT_OPEN
        assert "nTrans" in decision.reason

    def test_takes_priority_over_other_stops(self):
        # Also deep drawdown, but stop 1 should be reported since it's checked first.
        position = make_position(entry_price=100.0, p_trans=100.0)
        decision = evaluate_exits(
            position, current_price=50.0, current_date=date(2026, 6, 2), closed_below_n_trans=True
        )
        assert decision.exit_urgency == ExitUrgency.NEXT_OPEN


class TestStop2HardDrawdown:
    def test_triggers_immediate_exit(self):
        position = make_position(entry_price=100.0, p_trans=100.0)
        # 89 <= 90 (90% of entry) and 89 < p_trans(100)
        decision = evaluate_exits(
            position, current_price=89.0, current_date=date(2026, 6, 2), closed_below_n_trans=False
        )
        assert decision.should_exit is True
        assert decision.exit_urgency == ExitUrgency.IMMEDIATE

    def test_does_not_trigger_above_threshold(self):
        position = make_position(entry_price=100.0, p_trans=100.0)
        decision = evaluate_exits(
            position, current_price=95.0, current_date=date(2026, 6, 2), closed_below_n_trans=False
        )
        assert decision.should_exit is False

    def test_requires_both_drawdown_and_below_p_trans(self):
        # Price at exactly 90% of entry but p_trans is very low, so price is
        # not below p_trans -- stop 2 should not fire.
        position = make_position(entry_price=100.0, p_trans=50.0)
        decision = evaluate_exits(
            position, current_price=90.0, current_date=date(2026, 6, 2), closed_below_n_trans=False
        )
        assert decision.should_exit is False


class TestStop3TimeStop:
    def test_triggers_revisit_after_7_days_insufficient_progress(self):
        position = make_position(
            entry_price=100.0, t1_target=120.0, entry_date=date(2026, 6, 1)
        )
        # progress = (105 - 100) / (120 - 100) = 0.25 < 0.5
        decision = evaluate_exits(
            position, current_price=105.0, current_date=date(2026, 6, 8), closed_below_n_trans=False
        )
        assert decision.should_exit is True
        assert decision.exit_urgency == ExitUrgency.REVISIT

    def test_does_not_trigger_before_7_days(self):
        position = make_position(
            entry_price=100.0, t1_target=120.0, entry_date=date(2026, 6, 1)
        )
        decision = evaluate_exits(
            position, current_price=105.0, current_date=date(2026, 6, 7), closed_below_n_trans=False
        )
        assert decision.should_exit is False

    def test_does_not_trigger_with_sufficient_progress(self):
        position = make_position(
            entry_price=100.0, t1_target=120.0, entry_date=date(2026, 6, 1)
        )
        # progress = (115 - 100) / (120 - 100) = 0.75 >= 0.5
        decision = evaluate_exits(
            position, current_price=115.0, current_date=date(2026, 6, 8), closed_below_n_trans=False
        )
        assert decision.should_exit is False


class TestStop4Stalling:
    def test_triggers_revisit_when_three_sessions_below_10pct_progress(self):
        position = make_position(entry_price=100.0, t1_target=120.0)
        # T1 distance = 20. Day-over-day progress: 1/20=5%, 1/20=5%, 1/20=5% -- all < 10%.
        position.daily_closes = [
            (date(2026, 6, 1), 100.0),
            (date(2026, 6, 2), 101.0),
            (date(2026, 6, 3), 102.0),
            (date(2026, 6, 4), 103.0),
        ]
        decision = evaluate_exits(
            position, current_price=103.0, current_date=date(2026, 6, 4), closed_below_n_trans=False
        )
        assert decision.should_exit is True
        assert decision.exit_urgency == ExitUrgency.REVISIT

    def test_does_not_trigger_with_fewer_than_3_prior_sessions(self):
        position = make_position(entry_price=100.0, t1_target=120.0)
        position.daily_closes = [
            (date(2026, 6, 1), 100.0),
            (date(2026, 6, 2), 101.0),
        ]
        decision = evaluate_exits(
            position, current_price=101.0, current_date=date(2026, 6, 2), closed_below_n_trans=False
        )
        assert decision.should_exit is False

    def test_does_not_trigger_when_progress_strong(self):
        position = make_position(entry_price=100.0, t1_target=120.0)
        # Day-over-day progress: 3/20=15%, 3/20=15%, 3/20=15% -- all >= 10%.
        position.daily_closes = [
            (date(2026, 6, 1), 100.0),
            (date(2026, 6, 2), 103.0),
            (date(2026, 6, 3), 106.0),
            (date(2026, 6, 4), 109.0),
        ]
        decision = evaluate_exits(
            position, current_price=109.0, current_date=date(2026, 6, 4), closed_below_n_trans=False
        )
        assert decision.should_exit is False


class TestPassiveHoldStatus:
    def test_price_at_or_above_p_trans_holds_confirmed(self):
        position = make_position(entry_price=100.0, p_trans=100.0, n_trans=90.0)
        decision = evaluate_exits(
            position, current_price=105.0, current_date=date(2026, 6, 2), closed_below_n_trans=False
        )
        assert decision.should_exit is False
        assert decision.new_status == PositionStatus.CONFIRMED

    def test_price_between_n_trans_and_p_trans_is_watch(self):
        position = make_position(entry_price=100.0, p_trans=100.0, n_trans=90.0)
        decision = evaluate_exits(
            position, current_price=95.0, current_date=date(2026, 6, 2), closed_below_n_trans=False
        )
        assert decision.should_exit is False
        assert decision.new_status == PositionStatus.WATCH


class TestTakeProfit:
    def test_t1_reached_returns_choices_and_note(self):
        position = make_position(entry_price=100.0, t1_target=120.0, t2_target=140.0)
        result = evaluate_take_profit(position, current_price=121.0)
        assert result["t1_reached"] is True
        assert len(result["choices"]) == 2
        assert "stop_locked_to_entry" in result["note"]

    def test_t1_not_reached(self):
        position = make_position(entry_price=100.0, t1_target=120.0)
        result = evaluate_take_profit(position, current_price=110.0)
        assert result["t1_reached"] is False

    def test_t1_already_hit_does_not_report_reached_again(self):
        position = make_position(entry_price=100.0, t1_target=120.0)
        position.t1_hit = True
        result = evaluate_take_profit(position, current_price=125.0)
        assert result["t1_reached"] is False

    def test_does_not_mutate_position(self):
        position = make_position(entry_price=100.0, t1_target=120.0)
        evaluate_take_profit(position, current_price=125.0)
        assert position.t1_hit is False
        assert position.stop_locked_to_entry is False

    def test_t2_pursuit_requires_stop_locked(self):
        position = make_position(entry_price=100.0, t1_target=120.0, t2_target=140.0)
        result = evaluate_take_profit(position, current_price=125.0)
        assert result["stop_locked_to_entry"] is False
        assert "T2 must not be pursued" in result["note"]

"""Tests for the 5-minute candle close entry trigger."""

from __future__ import annotations

from conftest import make_row

from voldesk.entry import confirm_entry_trigger
from voldesk.grading import evaluate_setup
from voldesk.models import FilterResult, SetupClassification, SetupEvaluation


def _confirmed_eval() -> SetupEvaluation:
    row = make_row(spot=101.0, p_trans=100.0)
    ev = evaluate_setup(row)
    assert ev.classification == SetupClassification.CONFIRMED
    return ev


def _pending_eval() -> SetupEvaluation:
    row = make_row(spot=99.6, p_trans=100.0, plus_gex=110.0, cotmp=98.0)
    ev = evaluate_setup(row)
    assert ev.classification == SetupClassification.PENDING
    return ev


def test_confirmed_and_close_above_p_trans_triggers():
    ev = _confirmed_eval()
    assert confirm_entry_trigger(ev, five_min_candle_close=100.5, p_trans=100.0) is True


def test_confirmed_but_close_not_above_p_trans_does_not_trigger():
    ev = _confirmed_eval()
    assert confirm_entry_trigger(ev, five_min_candle_close=99.9, p_trans=100.0) is False


def test_confirmed_but_close_equal_p_trans_does_not_trigger():
    ev = _confirmed_eval()
    assert confirm_entry_trigger(ev, five_min_candle_close=100.0, p_trans=100.0) is False


def test_pending_classification_never_triggers_even_if_close_above_p_trans():
    ev = _pending_eval()
    assert confirm_entry_trigger(ev, five_min_candle_close=101.0, p_trans=100.0) is False


def test_blocked_classification_never_triggers():
    ev = SetupEvaluation(
        symbol="TEST",
        classification=SetupClassification.BLOCKED,
        filters=[FilterResult(name="grade", passed=False, reason="grade too low")],
    )
    assert confirm_entry_trigger(ev, five_min_candle_close=999.0, p_trans=100.0) is False

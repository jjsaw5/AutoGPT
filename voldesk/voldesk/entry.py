"""The actual entry trigger: the first 5-minute candle close above pTrans."""

from __future__ import annotations

from .models import SetupClassification, SetupEvaluation


def confirm_entry_trigger(
    evaluation: SetupEvaluation, five_min_candle_close: float, p_trans: float
) -> bool:
    """True only if evaluation is CONFIRMED and the 5-min candle CLOSE is above
    pTrans. Never pass pre-market prices here -- only a real 5-minute candle close."""
    return (
        evaluation.classification == SetupClassification.CONFIRMED
        and five_min_candle_close > p_trans
    )

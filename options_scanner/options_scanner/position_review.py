"""Position management — grade a held position and recommend an action.

Codifies the manual regrade rubric into a reproducible read: given a position's
state (direction, premium side, P&L, DTE, earnings) and the scanner's *current*
thesis on the underlying, produce a letter grade **and** a recommended action —
CLOSE / TRIM / ROLL / HOLD / WATCH — with a one-line reason.

Heuristic priors like the rest of the engine — explicit and consistent, and the
same signals the entry scanner uses (vol-regime fit, flow alignment, earnings /
IV-crush risk), so entries and exits speak the same language. Not advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class PositionReview:
    ticker: str
    grade: str
    action: str          # CLOSE | TRIM | ROLL | HOLD | WATCH
    reason: str
    score: float = 0.0
    aligned: Optional[bool] = None


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _letter(score: float) -> str:
    for cut, g in [
        (95, "A+"), (90, "A"), (85, "A-"), (80, "B+"), (75, "B"), (70, "B-"),
        (64, "C+"), (57, "C"), (51, "C-"), (45, "D+"), (40, "D"), (34, "D-"),
    ]:
        if score >= cut:
            return g
    return "F"


_MIN_CLOSE_CONVICTION = 0.5   # below this, a misaligned thesis is WATCH, not CLOSE


def _vol_fit(is_long_premium: bool, iv_rank: Optional[float], vol_regime: str) -> float:
    """Vol-regime fit, ramped by IV rank so grades don't cliff at IVR=50.

    Long premium wants cheap vol (reward low IVR, penalize high); short premium
    the reverse. Falls back to the discrete regime label when IVR is missing.
    """
    if iv_rank is None:
        if is_long_premium:
            return 12 if vol_regime == "cheap" else (-12 if vol_regime == "rich" else 0)
        return 10 if vol_regime == "rich" else (-10 if vol_regime == "cheap" else 0)
    if is_long_premium:
        return _clamp((40 - iv_rank) / 40 * 12, -12, 12)   # +12 @IVR0 · 0 @IVR40 · -12 @IVR80
    return _clamp((iv_rank - 50) / 40 * 10, -10, 10)       # -10 @IVR10 · 0 @IVR50 · +10 @IVR90


def review_position(
    ticker: str,
    *,
    direction: int,             # +1 bullish / -1 bearish / 0 neutral (position bias)
    is_long_premium: bool,      # long option / debit spread vs short premium
    pnl_pct: Optional[float],   # current P&L as a fraction of cost/risk
    dte: Optional[int],
    days_to_earnings: Optional[int],
    thesis_dir: int,            # scanner's current direction on the underlying
    thesis_conviction: float,
    vol_regime: str,            # 'cheap' | 'fair' | 'rich'
    iv_rank: Optional[float] = None,   # for the ramped vol penalty
    driver: str = "signals",           # what's driving the thesis (for reasons)
    stop_pnl_pct: float = -0.40,       # hard stop: close when P&L slides past this
) -> PositionReview:
    aligned = (direction == 0 and thesis_dir == 0) or (direction != 0 and thesis_dir == direction)
    misaligned = direction != 0 and thesis_dir == -direction
    d2e = days_to_earnings
    earnings_in_hold = is_long_premium and d2e is not None and dte is not None and 0 <= d2e <= dte
    earnings_imminent = is_long_premium and d2e is not None and 0 <= d2e <= 7

    # --- grade ---------------------------------------------------------------
    score = 55.0
    if direction != 0:
        if thesis_dir == direction:
            score += 22 * thesis_conviction
        elif thesis_dir == -direction:
            score -= 28 * thesis_conviction
    score += _vol_fit(is_long_premium, iv_rank, vol_regime)
    if pnl_pct is not None:
        score += _clamp(pnl_pct * 30, -15, 15)
    if earnings_in_hold:  # penalty scales with proximity, not a flat hit
        score -= 12 if d2e <= 10 else (6 if d2e <= 21 else 3)
    score = _clamp(score, 0, 100)
    grade = _letter(score)

    # --- action cascade ------------------------------------------------------
    # CLOSE requires a real exit TRIGGER (stop hit / conviction reversal /
    # imminent earnings) — NOT just a weak grade. A low grade means "wouldn't
    # OPEN this today", which for a defined-risk position with runway is a WATCH,
    # not a reason to close. "Close if it keeps sliding" = the stop trigger.
    if earnings_imminent:
        action, reason = "CLOSE", f"earnings in {d2e}d — close long premium before the IV crush"
    elif pnl_pct is not None and pnl_pct <= stop_pnl_pct:
        action, reason = "CLOSE", f"hit stop-loss ({pnl_pct:.0%} ≤ {stop_pnl_pct:.0%})"
    elif misaligned and (pnl_pct is None or pnl_pct < 0) and thesis_conviction >= _MIN_CLOSE_CONVICTION:
        action, reason = "CLOSE", f"{driver} reversed against the position (conviction {thesis_conviction:.2f})"
    elif pnl_pct is not None and pnl_pct >= 0.40 and aligned:
        action, reason = "TRIM", f"take profit into strength (+{pnl_pct:.0%})"
    elif not is_long_premium and dte is not None and dte <= 3:
        action, reason = "ROLL", "short premium near expiry — roll or close, don't hold short gamma"
    elif aligned and score >= 63:
        action, reason = "HOLD", "thesis intact — hold toward target"
    elif grade in ("F", "D-", "D"):
        # Weak, but defined-risk with runway and no trigger → watch, don't close.
        action, reason = "WATCH", f"weak setup (grade {grade}) — tighten stop; close if it slides to {stop_pnl_pct:.0%}"
    elif misaligned and thesis_conviction < _MIN_CLOSE_CONVICTION:
        action, reason = "WATCH", f"{driver} weakly against (conviction {thesis_conviction:.2f}) — tighten stop"
    elif misaligned:
        action, reason = "WATCH", "thesis against but green — use strength to exit"
    else:
        action, reason = "WATCH", "mixed / below-average — watch, tighten stop"

    return PositionReview(
        ticker=ticker, grade=grade, action=action, reason=reason,
        score=round(score, 1), aligned=aligned,
    )

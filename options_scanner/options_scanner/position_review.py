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
    if is_long_premium:
        score += 12 if vol_regime == "cheap" else (-12 if vol_regime == "rich" else 0)
    else:
        score += 10 if vol_regime == "rich" else (-10 if vol_regime == "cheap" else 0)
    if pnl_pct is not None:
        score += _clamp(pnl_pct * 30, -15, 15)
    if earnings_in_hold:  # penalty scales with proximity, not a flat hit
        score -= 12 if d2e <= 10 else (6 if d2e <= 21 else 3)
    score = _clamp(score, 0, 100)
    grade = _letter(score)

    # --- action cascade ------------------------------------------------------
    if earnings_imminent:
        action, reason = "CLOSE", f"earnings in {d2e}d — close long premium before the IV crush"
    elif misaligned and (pnl_pct is None or pnl_pct < 0):
        action, reason = "CLOSE", "flow flipped against the position"
    elif grade in ("F", "D-"):
        action, reason = "CLOSE", f"setup broken (grade {grade})"
    elif pnl_pct is not None and pnl_pct >= 0.40 and aligned:
        action, reason = "TRIM", f"take profit into strength (+{pnl_pct:.0%})"
    elif not is_long_premium and dte is not None and dte <= 3:
        action, reason = "ROLL", "short premium near expiry — roll or close, don't hold short gamma"
    elif aligned and score >= 63:
        action, reason = "HOLD", "thesis intact — hold toward target"
    elif misaligned:
        action, reason = "WATCH", "flow against but green — use strength to exit"
    else:
        action, reason = "WATCH", "mixed / below-average setup — watch, tighten stop"

    return PositionReview(
        ticker=ticker, grade=grade, action=action, reason=reason,
        score=round(score, 1), aligned=aligned,
    )

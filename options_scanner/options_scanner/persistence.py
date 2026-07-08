"""GO persistence — corroborate a fresh GO against recent history.

The intraday-noise lesson (SPY, then BAC): a GO printed off a single scan can be
whipsawed by the next tick. Our own logic liking a name *once* isn't the same as
it liking the name *repeatedly*. This module decides whether a GO is:

- ``confirmed``  — our logic has flagged the name GO-grade across enough recent
  sessions (``min_sessions``, counting the current one). Act-now.
- ``provisional`` — first recent session at GO-grade. Promising, but hold for
  confirmation before entering; a single-session GO is a hypothesis, not a signal.

The check is read-only against the durable candidate history (the same rows the
readout is built from), so it needs no new data — only a lookback.
"""

from __future__ import annotations

from typing import Any

CONFIRMED = "confirmed"
PROVISIONAL = "provisional"


def _is_go_grade(row: dict[str, Any], go_threshold: float) -> bool:
    """A prior scan counts as GO-grade if it decided GO, or (robust to transient
    gate flaps) its effective composite was at/above the GO line."""
    if str(row.get("decision") or "").upper() == "GO":
        return True
    comp = row.get("effective_composite")
    if comp is None:
        comp = row.get("composite")
    try:
        return comp is not None and float(comp) >= go_threshold
    except (TypeError, ValueError):
        return False


def go_persistence_status(
    prior_timeline: list[dict[str, Any]],
    *,
    go_threshold: float,
    min_sessions: int = 2,
    lookback: int = 4,
) -> str:
    """Classify a *current* GO given the ticker's PRIOR-scan timeline.

    ``prior_timeline`` is the chronological (oldest→newest) list of the ticker's
    earlier scans — NOT including the current one (which isn't persisted yet).
    We look at the most recent ``lookback`` prior scans, count how many were
    GO-grade, and confirm only if that count plus the current session reaches
    ``min_sessions``. With ``min_sessions=2`` a GO is confirmed the moment it has
    held GO-grade for one prior recent scan; a brand-new GO is provisional.
    """
    if min_sessions <= 1:
        return CONFIRMED  # persistence disabled — every GO is act-now
    recent = prior_timeline[-lookback:] if lookback and lookback > 0 else prior_timeline
    prior_go = sum(1 for r in recent if _is_go_grade(r, go_threshold))
    return CONFIRMED if prior_go + 1 >= min_sessions else PROVISIONAL

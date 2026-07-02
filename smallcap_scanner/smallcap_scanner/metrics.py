"""Pure computations over EOD price/volume history.

This is what detects the actual SLS pattern — a stock *grinding up on rising
volume over months* — as opposed to the single-snapshot "above its moving
averages today" checks that quote data allows. Input rows come from FMP's
``/stable/historical-price-eod/light`` endpoint: dicts with ``date`` (ISO),
``price`` and ``volume``. Order doesn't matter; rows are re-sorted here.

All functions are pure and offline so they can be unit-tested without a
network.
"""

from __future__ import annotations

from typing import Dict, List

# Trading-day offsets for the return windows (21 trading days ~ 1 month).
_RET_WINDOWS = {"ret_1m": 21, "ret_3m": 63, "ret_6m": 126}

# Minimum rows before we compute anything at all — below this, every metric
# would be noise and the candidate is better served by the quote-only path.
_MIN_ROWS = 22


def compute_history_metrics(rows: List[dict]) -> Dict[str, float]:
    """Derive momentum/volume metrics from EOD history rows.

    Returns a dict with whichever of these could be computed from the data:
      history_days     number of usable rows
      avg_volume_30d   mean daily volume over the 30 trading days BEFORE today
                       (excludes today so a surge doesn't inflate its own base)
      volume_trend     mean volume of the last 10 days / mean of the 30 days
                       before that — >1 means volume is building
      ret_1m/3m/6m     simple returns vs ~21/63/126 trading days ago
      up_week_ratio    fraction of the last up-to-26 weeks that closed higher
                       than the prior week — the "steady climb" signal that
                       separates a grind-up from a one-day spike

    Returns {} when there are too few rows to say anything.
    """
    clean = sorted(
        (r for r in rows if r.get("price") and r.get("date")),
        key=lambda r: str(r["date"]),
        reverse=True,  # newest first
    )
    n = len(clean)
    if n < _MIN_ROWS:
        return {}

    prices = [float(r["price"]) for r in clean]
    vols = [float(r.get("volume") or 0) for r in clean]
    out: Dict[str, float] = {"history_days": n}

    # True average volume, excluding today's (possibly surging) print.
    window = vols[1:31]
    out["avg_volume_30d"] = sum(window) / len(window)

    # Volume building: recent 10-day average vs the 30 days before that.
    if n >= 40:
        recent = sum(vols[0:10]) / 10
        base = sum(vols[10:40]) / 30
        if base > 0:
            out["volume_trend"] = recent / base

    for key, days in _RET_WINDOWS.items():
        if n > days and prices[days] > 0:
            out[key] = prices[0] / prices[days] - 1.0

    # Weekly consistency: compare closes 5 trading days apart, up to 26 weeks.
    weeks = min((n - 1) // 5, 26)
    if weeks >= 8:
        ups = sum(1 for i in range(weeks) if prices[i * 5] > prices[(i + 1) * 5])
        out["up_week_ratio"] = ups / weeks

    return out


def apply_history_metrics(stock, metrics: Dict[str, float]) -> None:
    """Copy computed metrics onto a StockCandidate in place."""
    for field in (
        "history_days",
        "avg_volume_30d",
        "volume_trend",
        "ret_1m",
        "ret_3m",
        "ret_6m",
        "up_week_ratio",
    ):
        if field in metrics:
            setattr(stock, field, metrics[field])

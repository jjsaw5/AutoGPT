"""Options-flow quality analysis (spec §4 direction).

Raw net premium is easy to misread — a big call buy could be a hedge, a spread
leg, or a closing trade. This turns UW flow-alert flags into a *quality-weighted*
directional read: aggressive (ask-side) opening single-leg sweeps count for more
than passive, closing, or multi-leg prints.

Uses fields already in the UW flow-alerts payload: `type`, `total_ask_side_prem`,
`total_bid_side_prem`, `all_opening_trades`, `has_sweep`, `has_multileg`,
`volume_oi_ratio`.
"""

from __future__ import annotations

from dataclasses import dataclass


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@dataclass
class FlowRead:
    vote: float = 0.0      # -1..+1 quality-weighted direction (+ bullish)
    quality: float = 0.0   # 0..1 how clean/actionable the flow is
    n: int = 0
    summary: str = ""


def analyze_flow(alerts: list[dict]) -> FlowRead:
    if not alerts:
        return FlowRead()

    signed = 0.0
    total_w = 0.0
    opening = single = decisive = 0
    sweeps = 0
    for a in alerts:
        typ = a.get("type")
        ask = _f(a.get("total_ask_side_prem")) or 0.0
        bid = _f(a.get("total_bid_side_prem")) or 0.0
        if typ not in ("call", "put") or (ask + bid) <= 0:
            continue
        base = 1.0 if typ == "call" else -1.0     # call bullish, put bearish
        net_aggr = ask - bid                        # >0 => bought at ask (aggressive)
        directional = base * net_aggr               # bullish if call-bought or put-sold

        weight = 1.0
        is_opening = bool(a.get("all_opening_trades"))
        is_multileg = bool(a.get("has_multileg"))
        is_sweep = bool(a.get("has_sweep"))
        voo = _f(a.get("volume_oi_ratio")) or 0.0
        if is_opening:
            weight *= 1.3
            opening += 1
        if is_sweep:
            weight *= 1.2
            sweeps += 1
        if is_multileg:
            weight *= 0.6            # multi-leg = less cleanly directional
        else:
            single += 1
        if voo > 1.0:
            weight *= 1.15           # trading more than existing OI = new positioning
        if abs(net_aggr) / (ask + bid) > 0.5:
            decisive += 1

        signed += directional * weight
        total_w += (ask + bid) * weight

    if total_w <= 0:
        return FlowRead(n=len(alerts))

    vote = max(-1.0, min(1.0, signed / 2_000_000.0))
    n = len(alerts)
    quality = round((opening / n + single / n + decisive / n) / 3.0, 3)
    summary = f"{n} alerts · {opening} opening · {sweeps} sweeps · {single} single-leg"
    return FlowRead(vote=round(vote, 3), quality=quality, n=n, summary=summary)

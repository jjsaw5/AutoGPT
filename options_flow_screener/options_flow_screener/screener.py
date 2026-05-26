"""Filter spec, aggregation, ranking — pure functions, no I/O."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


Side = Literal["bullish", "bearish", "any"]
RankBy = Literal["bullish_flow_pct", "open_interest", "premium", "iv_rank", "largest_order"]


@dataclass
class FilterSpec:
    market_cap_min_usd: float | None = None
    market_cap_max_usd: float | None = None
    premium_min_usd: float | None = None
    iv_rank_min: float | None = None
    bullish_flow_pct_min: float | None = None
    vol_oi_max: float | None = None
    dte_min: int | None = None
    dte_max: int | None = None
    side: Side = "bullish"
    rank_by: RankBy = "bullish_flow_pct"
    rank_direction: Literal["asc", "desc"] = "desc"
    limit: int = 10


@dataclass
class TickerSummary:
    ticker: str
    market_cap: float | None
    sector: str | None
    iv_rank: float | None
    bullish_premium: float
    bearish_premium: float
    total_premium: float
    bullish_flow_pct: float
    largest_order: float
    open_interest: int
    volume: int
    vol_oi: float | None
    alert_count: int
    largest_dte: int | None


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def alert_premium(alert: dict[str, Any]) -> float:
    for k in ("total_premium", "premium", "total_value"):
        v = alert.get(k)
        if v is not None:
            return float(v)
    return float(alert.get("total_ask_side_prem", 0) or 0) + float(
        alert.get("total_bid_side_prem", 0) or 0
    )


def _bullish_bearish_split(alert: dict[str, Any]) -> tuple[float, float]:
    """Bullish if call bought at ask OR put sold at bid; bearish otherwise.

    Returns (bullish_premium, bearish_premium) for this alert.
    """
    typ = (alert.get("type") or alert.get("option_type") or "").lower()
    ask = float(alert.get("total_ask_side_prem") or 0)
    bid = float(alert.get("total_bid_side_prem") or 0)
    if typ == "call":
        return ask, bid
    if typ == "put":
        return bid, ask
    total = alert_premium(alert)
    return total / 2, total / 2


def aggregate(alerts: list[dict[str, Any]]) -> dict[str, TickerSummary]:
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for a in alerts:
        t = a.get("ticker") or a.get("underlying_symbol")
        if not t:
            continue
        by_ticker.setdefault(t, []).append(a)

    out: dict[str, TickerSummary] = {}
    for t, group in by_ticker.items():
        bull = bear = 0.0
        largest = 0.0
        oi = 0
        vol = 0
        largest_dte: int | None = None
        for a in group:
            b, r = _bullish_bearish_split(a)
            bull += b
            bear += r
            p = alert_premium(a)
            if p > largest:
                largest = p
                d = a.get("dte")
                if d is not None:
                    largest_dte = int(d)
            oi += int(a.get("open_interest") or 0)
            vol += int(a.get("volume") or 0)
        total = bull + bear
        first = group[0]
        out[t] = TickerSummary(
            ticker=t,
            market_cap=_to_float(first.get("marketcap") or first.get("market_cap")),
            sector=first.get("sector"),
            iv_rank=_to_float(first.get("iv_rank") or first.get("underlying_iv_rank")),
            bullish_premium=bull,
            bearish_premium=bear,
            total_premium=total,
            bullish_flow_pct=(bull / total * 100) if total > 0 else 0.0,
            largest_order=largest,
            open_interest=oi,
            volume=vol,
            vol_oi=(vol / oi) if oi > 0 else None,
            alert_count=len(group),
            largest_dte=largest_dte,
        )
    return out


def apply_filters(
    summaries: dict[str, TickerSummary], spec: FilterSpec
) -> list[TickerSummary]:
    out: list[TickerSummary] = []
    for s in summaries.values():
        if spec.market_cap_min_usd is not None and (
            s.market_cap is None or s.market_cap < spec.market_cap_min_usd
        ):
            continue
        if spec.market_cap_max_usd is not None and (
            s.market_cap is None or s.market_cap > spec.market_cap_max_usd
        ):
            continue
        if spec.iv_rank_min is not None and (
            s.iv_rank is None or s.iv_rank < spec.iv_rank_min
        ):
            continue
        if spec.bullish_flow_pct_min is not None and s.bullish_flow_pct < spec.bullish_flow_pct_min:
            continue
        if spec.vol_oi_max is not None and (s.vol_oi is None or s.vol_oi > spec.vol_oi_max):
            continue
        if spec.side == "bullish" and s.bullish_flow_pct < 50:
            continue
        if spec.side == "bearish" and s.bullish_flow_pct >= 50:
            continue
        out.append(s)

    key_fn = {
        "bullish_flow_pct": lambda x: x.bullish_flow_pct,
        "open_interest": lambda x: x.open_interest,
        "premium": lambda x: x.total_premium,
        "iv_rank": lambda x: (x.iv_rank or 0),
        "largest_order": lambda x: x.largest_order,
    }[spec.rank_by]
    out.sort(key=key_fn, reverse=(spec.rank_direction == "desc"))
    return out[: spec.limit]

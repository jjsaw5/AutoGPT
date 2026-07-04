"""Market-wide cross-asset regime pillar (risk-on / risk-off).

Computed ONCE per scan (it's market-wide, not per-ticker). Blends six cross-asset
signals into a composite in [-1, +1] and a regime label, then maps it to a
-2..+2 macro score the scanner uses to (a) nudge the composite of theses that
fight the regime and (b) surface a risk-on/off line in the portfolio summary.

Signal orientation: +1 = risk-on / broadening, -1 = risk-off / concentration.

Adapted from the cross-asset macro pillar in Oft3r/agentic-trading-desk
(MIT-licensed) — its component set, weights, and regime cascade — reimplemented
here in this project's style and fed from FMP historical closes + treasury rates
rather than Robinhood/Investing.com. Original © 2026 Oft3r, MIT.

stdlib only for the math.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# name -> (ratio label, weight, numerator sym, denominator sym)
_COMPONENTS = [
    ("concentration", "RSP/SPY", 0.25, "RSP", "SPY"),  # equal- vs cap-weight (broadening = +)
    ("credit", "HYG/LQD", 0.15, "HYG", "LQD"),          # high-yield vs IG (risk-on = +)
    ("size", "IWM/SPY", 0.15, "IWM", "SPY"),            # small vs large (broadening = +)
    ("equity_bond", "SPY/TLT", 0.15, "SPY", "TLT"),     # stocks vs bonds (risk-on = +)
    ("sector", "XLY/XLP", 0.10, "XLY", "XLP"),          # cyclical vs defensive (risk-on = +)
]
_YIELD_WEIGHT = 0.20  # 10Y-2Y curve, injected separately
ETFS = ["SPY", "RSP", "IWM", "HYG", "LQD", "TLT", "XLY", "XLP"]


# --- math (stdlib) ------------------------------------------------------------
def _sma(series: list[float], window: int) -> Optional[float]:
    if len(series) < window:
        return None
    return sum(series[-window:]) / window


def _ratio_series(num: list[float], den: list[float]) -> list[float]:
    n = min(len(num), len(den))
    return [a / b for a, b in zip(num[-n:], den[-n:]) if b != 0]


def _pct_returns(series: list[float]) -> list[float]:
    return [series[i] / series[i - 1] - 1.0 for i in range(1, len(series)) if series[i - 1] != 0]


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    n = min(len(xs), len(ys))
    if n < 5:
        return None
    xs, ys = xs[-n:], ys[-n:]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx ** 0.5 * vy ** 0.5)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _trend_signal(series: list[float], slow: int, slope_win: int) -> tuple[Optional[float], str]:
    """-1/0/+1 from position vs the slow SMA and the slope of that SMA."""
    s_slow = _sma(series, slow)
    if s_slow is None or len(series) < slow + slope_win:
        return None, "insufficient data"
    base = 1.0 if series[-1] > s_slow else -1.0
    slow_then = _sma(series[:-slope_win], slow)
    if slow_then is None:
        return None, "insufficient data"
    trend = 1.0 if s_slow > slow_then else -1.0
    return 0.5 * base + 0.5 * trend, (
        f"{'above' if base > 0 else 'below'} SMA{slow}, {'rising' if trend > 0 else 'falling'}"
    )


@dataclass
class RegimeComponent:
    name: str
    ratio: str
    weight: float
    signal: Optional[float] = None
    detail: str = ""
    available: bool = True


@dataclass
class MarketRegime:
    as_of: str
    composite: float                 # -1..+1
    regime: str
    macro_score: int                 # -2..+2
    macro_label: str
    inflationary_flag: bool = False
    spy_tlt_corr: Optional[float] = None
    components: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def direction(self) -> int:
        """+1 risk-on (favors bullish), -1 risk-off (favors bearish), 0 neutral."""
        if self.composite >= 0.2:
            return 1
        if self.composite <= -0.2:
            return -1
        return 0


def score_market(
    series: dict[str, list[float]],
    *,
    yield_spread: float | None = None,
    as_of: str = "",
    slow: int = 200,
    slope_win: int = 20,
    corr_win: int = 40,
) -> MarketRegime:
    notes: list[str] = []
    comps: dict[str, RegimeComponent] = {}

    for name, label, weight, num, den in _COMPONENTS:
        c = RegimeComponent(name, label, weight)
        ns, ds = series.get(num), series.get(den)
        if ns and ds:
            c.signal, c.detail = _trend_signal(_ratio_series(ns, ds), slow, slope_win)
        if c.signal is None:
            c.available = False
        comps[name] = c

    # Yield curve 10Y-2Y (level only — a single scalar): inverted = risk-off.
    yc = RegimeComponent("yield_curve", "10Y-2Y", _YIELD_WEIGHT)
    if yield_spread is not None:
        yc.signal = 0.5 if yield_spread > 0 else -0.5
        yc.detail = f"spread {yield_spread:+.2f} (level)"
    else:
        yc.available = False
        notes.append("no yield spread — 20% weight redistributed across other components")
    comps["yield_curve"] = yc

    # SPY-TLT correlation → inflationary flag
    spy_tlt_corr = None
    spy, tlt = series.get("SPY"), series.get("TLT")
    if spy and tlt:
        spy_tlt_corr = _pearson(
            _pct_returns(spy[-(corr_win + 1):]), _pct_returns(tlt[-(corr_win + 1):])
        )

    avail = [c for c in comps.values() if c.available and c.signal is not None]
    if not avail:
        raise ValueError("no cross-asset components with sufficient data")
    wsum = sum(c.weight for c in avail)
    composite = _clamp(sum(c.signal * c.weight for c in avail) / wsum, -1.0, 1.0)

    eb = comps["equity_bond"]
    inflationary = bool(
        spy_tlt_corr is not None and spy_tlt_corr > 0.25
        and eb.available and eb.signal is not None and eb.signal <= 0
    )

    # Regime classification (priority cascade)
    conc = comps["concentration"].signal or 0
    size = comps["size"].signal or 0
    credit = comps["credit"].signal or 0
    if inflationary:
        regime = "Inflationary"
    elif composite <= -0.5 and credit < 0:
        regime = "Contraction"
    elif composite >= 0.4 and size > 0:
        regime = "Broadening"
    elif conc < 0 and size < 0 and composite > -0.5:
        regime = "Concentration"
    else:
        regime = "Transitional"

    # Map composite → -2..+2 macro score
    if composite >= 0.5:
        macro, label = 2, "strongly risk-on"
    elif composite >= 0.2:
        macro, label = 1, "risk-on"
    elif composite > -0.2:
        macro, label = 0, "neutral"
    elif composite > -0.5:
        macro, label = -1, "risk-off"
    else:
        macro, label = -2, "strongly risk-off"

    if regime in ("Contraction", "Inflationary") and macro > -1:
        macro, label = -1, f"risk-off (capped by {regime})"
        notes.append(f"macro capped at -1 due to {regime} regime")

    return MarketRegime(
        as_of=as_of, composite=round(composite, 3), regime=regime,
        macro_score=macro, macro_label=label, inflationary_flag=inflationary,
        spy_tlt_corr=round(spy_tlt_corr, 3) if spy_tlt_corr is not None else None,
        components=[
            {"ratio": c.ratio, "weight": c.weight,
             "signal": round(c.signal, 2) if c.signal is not None else None,
             "detail": c.detail, "available": c.available}
            for c in comps.values()
        ],
        notes=notes,
    )


def build_market_regime(fmp, *, now: datetime | None = None) -> MarketRegime | None:
    """Fetch the ETF closes + treasury spread from FMP and score the regime."""
    if fmp is None:
        return None
    now = now or datetime.now(timezone.utc)
    series: dict[str, list[float]] = {}
    for sym in ETFS:
        closes = fmp.historical_closes(sym, limit=300)
        if closes:
            series[sym] = closes
    if len(series) < 4:
        logger.warning("market regime: too few ETF series (%d) — skipping", len(series))
        return None
    spread = fmp.treasury_spread()
    try:
        return score_market(series, yield_spread=spread, as_of=now.date().isoformat())
    except ValueError as exc:
        logger.warning("market regime: %s", exc)
        return None

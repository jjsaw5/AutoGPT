"""Deterministic technical indicators for the direction model (spec §4).

Upgrades the old direction technical vote (price vs 50/200-day MA) to a real
stack: EMA 8/21/50/200 alignment + slope, RSI-14 (Wilder), MACD histogram — plus
a *late-entry* (stretch) penalty, because for options, direction isn't enough:
buying calls after a vertical move into resistance is usually bad even when the
thesis is bullish.

Adapted from the indicator engine in Oft3r/agentic-trading-desk (MIT). stdlib
only; input is a list of daily closes oldest→newest.
"""

from __future__ import annotations

from typing import Optional


def ema_series(values: list[float], period: int) -> list[Optional[float]]:
    n = len(values)
    out: list[Optional[float]] = [None] * n
    if n < period:
        return out
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _last(series: list[Optional[float]]) -> Optional[float]:
    for v in reversed(series):
        if v is not None:
            return v
    return None


def rsi_wilder(closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - 100.0 / (1.0 + rs)


def macd_hist(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[float]:
    ef, es = ema_series(closes, fast), ema_series(closes, slow)
    macd_line = [
        (a - b) if a is not None and b is not None else None
        for a, b in zip(ef, es)
    ]
    clean = [m for m in macd_line if m is not None]
    if len(clean) < signal + 1:
        return None
    sig = ema_series(clean, signal)
    last_macd, last_sig = clean[-1], _last(sig)
    if last_sig is None:
        return None
    return last_macd - last_sig


def compute_technicals(closes: list[float]) -> Optional[dict]:
    if len(closes) < 30:
        return None
    price = closes[-1]
    e8, e21, e50, e200 = (_last(ema_series(closes, p)) for p in (8, 21, 50, 200))
    e200_series = ema_series(closes, 200)
    e200_then = e200_series[-6] if len(e200_series) >= 6 else None
    e200_slope = (e200 - e200_then) if (e200 is not None and e200_then is not None) else None
    stretch = (price / e21 - 1.0) if e21 else 0.0
    return {
        "price": price, "ema8": e8, "ema21": e21, "ema50": e50, "ema200": e200,
        "ema200_slope": e200_slope, "rsi14": rsi_wilder(closes),
        "macd_hist": macd_hist(closes), "stretch": stretch,
    }


def technical_vote(tech: dict | None) -> float:
    """-1..+1 from EMA alignment/slope + RSI regime + MACD histogram."""
    if not tech:
        return 0.0
    pts, n = 0.0, 0
    price, e8, e21, e50, e200 = (tech.get(k) for k in ("price", "ema8", "ema21", "ema50", "ema200"))
    if e21 is not None:
        pts += 1 if price > e21 else -1; n += 1
    if e8 is not None and e21 is not None:
        pts += 1 if e8 > e21 else -1; n += 1
    if e50 is not None and e200 is not None:
        pts += 1 if e50 > e200 else -1; n += 1
    if tech.get("ema200_slope") is not None:
        pts += 1 if tech["ema200_slope"] > 0 else -1; n += 1
    rsi = tech.get("rsi14")
    if rsi is not None:
        pts += 1 if rsi >= 55 else (-1 if rsi <= 45 else 0); n += 1
    hist = tech.get("macd_hist")
    if hist is not None:
        pts += 1 if hist > 0 else -1; n += 1
    return round(pts / n, 3) if n else 0.0


def late_entry_penalty(tech: dict | None, direction: int) -> float:
    """0..1 multiplier — penalize buying into an already-stretched move.

    ``direction`` is +1 bullish / -1 bearish. Being >10% past EMA21 in the
    trade's direction (or RSI already extreme) trims conviction.
    """
    if not tech or direction == 0:
        return 1.0
    penalty = 1.0
    stretch = tech.get("stretch", 0.0) * direction   # positive = extended in our favor already
    if stretch >= 0.10:
        penalty *= 0.7
    elif stretch >= 0.06:
        penalty *= 0.85
    rsi = tech.get("rsi14")
    if rsi is not None:
        if direction > 0 and rsi >= 75:
            penalty *= 0.8
        elif direction < 0 and rsi <= 25:
            penalty *= 0.8
    return round(penalty, 3)

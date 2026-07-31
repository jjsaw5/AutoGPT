"""Indicator maths.

Pure functions over ordered bar lists (oldest first). No I/O, so these are
the parts of the process that can be tested exactly.
"""

from __future__ import annotations

from collections.abc import Sequence

from .models import Bar


def sma(values: Sequence[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values: Sequence[float], period: int) -> list[float]:
    """Standard EMA seeded with the SMA of the first `period` values."""
    if period <= 0 or len(values) < period:
        return []
    multiplier = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out = [seed]
    for value in values[period:]:
        out.append((value - out[-1]) * multiplier + out[-1])
    return out


def ema(values: Sequence[float], period: int) -> float | None:
    series = ema_series(values, period)
    return series[-1] if series else None


def true_range(current: Bar, previous: Bar | None) -> float:
    if previous is None:
        return current.high - current.low
    return max(
        current.high - current.low,
        abs(current.high - previous.close),
        abs(current.low - previous.close),
    )


def atr(bars: Sequence[Bar], period: int) -> float | None:
    """Wilder's ATR."""
    if len(bars) < period + 1:
        return None
    ranges = [true_range(bars[i], bars[i - 1]) for i in range(1, len(bars))]
    if len(ranges) < period:
        return None
    value = sum(ranges[:period]) / period
    for r in ranges[period:]:
        value = (value * (period - 1) + r) / period
    return value


def vwap(bars: Sequence[Bar]) -> float | None:
    """Session VWAP from typical price.

    Callers are responsible for passing only the bars belonging to the
    session they want anchored -- this does not filter by session itself.
    """
    total_volume = sum(b.volume for b in bars)
    if total_volume <= 0:
        return None
    numerator = sum(((b.high + b.low + b.close) / 3) * b.volume for b in bars)
    return numerator / total_volume


def closes(bars: Sequence[Bar]) -> list[float]:
    return [b.close for b in bars]

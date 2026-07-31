"""Tech-regime scoring.

This is the part of the process taken from the thread that prompted it:
strong tech tends to drag SPY and QQQ with it, weak tech drags them down,
and a neutral tech tape is the hard day where a trend process should simply
not be trading. The scorer turns that into a number so "neutral" becomes a
threshold instead of a feeling.

Three components, each normalised to [-1, 1]:

  sector_rs  XLK's day change relative to SPY's. The sector proxy.
  breadth    How much of the mega-cap tech complex is green. Catches the
             case where one name (an NVDA gap, say) carries XLK while the
             rest of the group is flat -- that is not a real tech bid.
  qqq_rs     QQQ relative to SPY. Confirms the index is expressing it.
"""

from __future__ import annotations

from .config import TECH_MEGACAPS, TECH_SECTOR_PROXY, RegimeConfig
from .models import Quote, Regime, RegimeScore


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def required_symbols() -> list[str]:
    return [TECH_SECTOR_PROXY, "SPY", "QQQ", *TECH_MEGACAPS]


def score_regime(
    quotes: dict[str, Quote],
    config: RegimeConfig | None = None,
) -> RegimeScore:
    config = config or RegimeConfig()

    spy = quotes.get("SPY")
    if spy is None:
        return RegimeScore(
            regime=Regime.NEUTRAL,
            score=0.0,
            sector_rs=0.0,
            breadth=0.0,
            qqq_rs=0.0,
            detail="no SPY quote; regime undefined",
        )

    baseline = spy.change_pct

    xlk = quotes.get(TECH_SECTOR_PROXY)
    sector_rs = (
        _clamp((xlk.change_pct - baseline) / config.rs_saturation_pct) if xlk else 0.0
    )

    qqq = quotes.get("QQQ")
    qqq_rs = (
        _clamp((qqq.change_pct - baseline) / config.rs_saturation_pct) if qqq else 0.0
    )

    present = [quotes[s] for s in TECH_MEGACAPS if s in quotes]
    if present:
        green = sum(1 for q in present if q.change_pct > 0)
        breadth = _clamp(2 * (green / len(present)) - 1)
    else:
        breadth = 0.0

    score = (
        sector_rs * config.sector_rs_weight
        + breadth * config.breadth_weight
        + qqq_rs * config.qqq_rs_weight
    )

    regime = _classify(score, config)
    detail = (
        f"{regime.value} (score {score:+.2f}) | "
        f"XLK vs SPY {sector_rs:+.2f}, breadth {breadth:+.2f} "
        f"({sum(1 for q in present if q.change_pct > 0)}/{len(present)} green), "
        f"QQQ vs SPY {qqq_rs:+.2f}"
    )

    return RegimeScore(
        regime=regime,
        score=score,
        sector_rs=sector_rs,
        breadth=breadth,
        qqq_rs=qqq_rs,
        detail=detail,
    )


def _classify(score: float, config: RegimeConfig) -> Regime:
    if score >= config.strong_threshold:
        return Regime.STRONG_BULL
    if score >= config.directional_threshold:
        return Regime.BULL
    if score <= -config.strong_threshold:
        return Regime.STRONG_BEAR
    if score <= -config.directional_threshold:
        return Regime.BEAR
    return Regime.NEUTRAL

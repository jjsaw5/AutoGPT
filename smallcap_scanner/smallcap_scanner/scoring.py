"""Turn raw candidate + social data into a ranked, explained score.

Three sub-scores on a 0-100 scale:
  * fundamental — is this the right *kind* of stock (cheap, small, liquid)?
  * momentum    — is it grinding up on rising volume (the SLS pattern)?
  * social      — is retail attention building on the tracked subreddits?

The composite is a weighted blend. Crucially, ``flags`` surface *risks*
(coordinated-pump signatures, sub-penny delisting risk, already-parabolic) so a
high score is never read uncritically.
"""

from __future__ import annotations

import math
from typing import Dict, Optional

from .config import Config
from .models import RedditSignal, ScoredCandidate, StockCandidate


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _scale_log(value: float, full_at: float) -> float:
    """Map ``value`` to 0-100 on a log curve, reaching ~100 near ``full_at``."""
    if value <= 0:
        return 0.0
    return _clamp(100.0 * math.log1p(value) / math.log1p(full_at))


def score_fundamental(stock: StockCandidate, cfg: Config) -> tuple[float, list[str]]:
    t = cfg.thresholds
    reasons: list[str] = []
    score = 0.0

    # Lower price within the band => more call leverage potential. Linear from
    # 40 pts at price_max down-weight to 100 pts at price_min.
    span = max(t.price_max - t.price_min, 1e-9)
    price_pos = (t.price_max - stock.price) / span  # 1 at the cheap end
    price_pts = 40 + 60 * _clamp(price_pos, 0, 1)
    score += 0.5 * price_pts
    if stock.price <= (t.price_min + span * 0.4):
        reasons.append(f"low price ${stock.price:.2f} → high option leverage")

    # Liquidity: reward volume well above the floor (log up to ~10x floor).
    liq = _scale_log(stock.avg_volume, t.avg_volume_min * 10)
    score += 0.3 * liq
    if stock.avg_volume >= t.avg_volume_min * 3:
        reasons.append(f"liquid: {stock.avg_volume/1e6:.1f}M avg vol")

    # Market cap sweet spot: avoid the very bottom (junk) and the very top.
    if t.market_cap_max > t.market_cap_min:
        mc_pos = (stock.market_cap - t.market_cap_min) / (
            t.market_cap_max - t.market_cap_min
        )
        # peak reward around the lower-middle of the band
        mc_pts = 100 * math.exp(-((_clamp(mc_pos, 0, 1) - 0.25) ** 2) / 0.08)
        score += 0.2 * mc_pts

    return _clamp(score), reasons


def score_momentum(stock: StockCandidate) -> tuple[float, list[str]]:
    """0-100 across four families of evidence (max points in parens):

      trend vs moving averages (35) — quote data, the original snapshot check
      grind-up pattern (35)         — EOD history: multi-month returns plus
                                       week-over-week consistency, the actual
                                       SLS shape; a one-day spike earns the
                                       return points but not the consistency
      volume behaviour (20)         — volume *building* over weeks, plus
                                       today's surge vs a true trailing avg
      52w-range position (10)       — off the lows with room to the highs

    History-based parts contribute 0 when history wasn't fetched (candidate
    outside FMP_HISTORY_LIMIT, or the API call failed) — the quote-based
    parts still work, so scores degrade gracefully rather than vanish.
    Continuous scaling (not fixed steps) also breaks the score ties that made
    earlier stage-1 lists read as big blocks of identical scores.
    """
    reasons: list[str] = []
    if (
        stock.price_avg_50 is None
        and stock.price_avg_200 is None
        and stock.history_days == 0
    ):
        return 0.0, reasons

    score = 0.0

    # --- trend vs moving averages (quote data) ---
    if stock.price_avg_50 and stock.price > stock.price_avg_50:
        score += 15
        reasons.append("above 50d avg")
    if stock.price_avg_200 and stock.price > stock.price_avg_200:
        score += 10
        reasons.append("above 200d avg")
    if (
        stock.price_avg_50
        and stock.price_avg_200
        and stock.price_avg_50 > stock.price_avg_200
    ):
        score += 10
        reasons.append("50d > 200d (uptrend)")

    # --- grind-up pattern (EOD history) ---
    if stock.ret_3m is not None and stock.ret_3m > 0:
        score += 15 * _clamp(stock.ret_3m / 0.5, 0, 1)
        reasons.append(f"+{stock.ret_3m * 100:.0f}% over 3 months")
    if stock.ret_6m is not None and stock.ret_6m > 0:
        score += 10 * _clamp(stock.ret_6m / 1.0, 0, 1)
        reasons.append(f"+{stock.ret_6m * 100:.0f}% over 6 months")
    if stock.up_week_ratio is not None and stock.up_week_ratio > 0.5:
        score += 10 * _clamp((stock.up_week_ratio - 0.5) / 0.3, 0, 1)
        if stock.up_week_ratio >= 0.6:
            reasons.append(
                f"{stock.up_week_ratio * 100:.0f}% of weeks closed up (steady climb)"
            )

    # --- volume behaviour ---
    if stock.volume_trend is not None and stock.volume_trend > 1.1:
        score += 10 * _clamp((stock.volume_trend - 1.0) / 1.0, 0, 1)
        reasons.append(f"volume building: {stock.volume_trend:.1f}x its baseline")
    surge = stock.volume_surge
    if surge and surge > 1.2:
        score += _clamp(10 * math.log1p(surge - 1) / math.log1p(4), 0, 10)
        reasons.append(f"volume {surge:.1f}x average today")

    # --- off the lows but with room left to the highs == early in the move ---
    above_low = stock.pct_above_year_low
    below_high = stock.pct_below_year_high
    if above_low is not None and below_high is not None:
        if above_low > 20 and below_high > 25:
            score += 10
            reasons.append(
                f"+{above_low:.0f}% off 52w low, still {below_high:.0f}% below high"
            )

    return _clamp(score), reasons


def score_social(reddit: Optional[RedditSignal]) -> tuple[float, list[str]]:
    if not reddit or reddit.mentions_total == 0:
        return 0.0, []
    reasons: list[str] = []
    score = 0.0

    # Recent mention volume (log, ~saturates around 25 recent mentions).
    score += 0.5 * _scale_log(reddit.mentions_recent, 25)
    if reddit.mentions_recent >= 3:
        reasons.append(f"{reddit.mentions_recent} recent mentions")

    # Cross-subreddit spread is a stronger organic signal than one echo chamber.
    if len(reddit.subreddits) >= 2:
        score += 15
        reasons.append(f"seen in {len(reddit.subreddits)} subreddits")

    # Organic discussion (many distinct authors) beats one person spamming.
    # When author data isn't available (ApeWisdom), author_diversity reads as
    # a neutral 1.0 — the full bonus applies rather than penalizing a ticker
    # just because that source doesn't expose post-level authorship.
    score += 20 * _clamp(reddit.author_diversity, 0, 1)

    # Engagement.
    score += 0.15 * _scale_log(reddit.upvotes_sum, 500)

    # Cross-scan persistence (set by trend.annotate_signals when saved scans
    # exist). Showing up day after day is the "talked about for months"
    # signal — worth more than any single-day mention count.
    if reddit.streak_days >= 2:
        score += _clamp(4.0 * (reddit.streak_days - 1), 0, 12)
        reasons.append(f"trending {reddit.streak_days} scan-days in a row")
    if (
        reddit.mention_growth is not None
        and reddit.mention_growth >= 1.5
        and reddit.days_seen >= 2
    ):
        score += 3
        reasons.append(f"mentions {reddit.mention_growth:.1f}x prior-day average")

    return _clamp(score), reasons


def risk_flags(
    stock: StockCandidate, reddit: Optional[RedditSignal], cfg: Config
) -> list[str]:
    flags: list[str] = []
    t = cfg.thresholds

    if stock.price < 1.0:
        flags.append("SUB_$1 (delisting/illiquid-options risk)")
    if stock.avg_volume < t.avg_volume_min:
        flags.append("THIN_VOLUME")
    if stock.change_pct is not None and stock.change_pct > 25:
        flags.append("ALREADY_PARABOLIC_TODAY (chasing risk)")

    # Relevant for candidates sourced outside the fundamental screen (stage 3:
    # social-discovered tickers looked up directly via FMP quote) — flags
    # rather than silently drops them, so a popular but mega-cap name like
    # AMC still shows up with full context instead of vanishing.
    if not (t.price_min <= stock.price <= t.price_max):
        flags.append("OUTSIDE_PRICE_RANGE")
    if not (t.market_cap_min <= stock.market_cap <= t.market_cap_max):
        flags.append("OUTSIDE_MARKET_CAP_RANGE")

    # Author-diversity checks only mean something for providers that expose
    # per-post authorship (RSS, PRAW) — aggregate-only sources like ApeWisdom
    # don't carry the data needed to tell organic buzz from one spammer.
    if reddit and reddit.author_diversity_known and reddit.mentions_total >= 4:
        if reddit.author_diversity < 0.4:
            flags.append("LOW_AUTHOR_DIVERSITY (possible coordinated pump)")
        # A burst that is almost entirely "recent" with few authors looks seeded.
        if (
            reddit.mentions_recent == reddit.mentions_total
            and reddit.unique_authors <= 2
        ):
            flags.append("SUDDEN_SEEDED_SPIKE")

    return flags


def score_candidate(
    stock: StockCandidate, reddit: Optional[RedditSignal], cfg: Config
) -> ScoredCandidate:
    f_score, f_reasons = score_fundamental(stock, cfg)
    m_score, m_reasons = score_momentum(stock)
    s_score, s_reasons = score_social(reddit)

    wsum = cfg.weight_fundamental + cfg.weight_momentum + cfg.weight_social
    wsum = wsum or 1.0
    composite = (
        cfg.weight_fundamental * f_score
        + cfg.weight_momentum * m_score
        + cfg.weight_social * s_score
    ) / wsum

    return ScoredCandidate(
        symbol=stock.symbol,
        stock=stock,
        reddit=reddit,
        fundamental_score=f_score,
        momentum_score=m_score,
        social_score=s_score,
        composite_score=composite,
        reasons=f_reasons + m_reasons + s_reasons,
        flags=risk_flags(stock, reddit, cfg),
    )


def rank(
    stocks: Dict[str, StockCandidate],
    reddit: Dict[str, RedditSignal],
    cfg: Config,
    require_social: bool = False,
) -> list[ScoredCandidate]:
    """Score every stock and return them sorted by composite score, desc.

    If ``require_social`` is set, only stocks with at least one Reddit mention
    are returned (the "what is retail actually talking about" view)."""
    out: list[ScoredCandidate] = []
    for sym, stock in stocks.items():
        sig = reddit.get(sym)
        if require_social and not sig:
            continue
        out.append(score_candidate(stock, sig, cfg))
    out.sort(key=lambda c: c.composite_score, reverse=True)
    return out


def score_candidate_fmp_only(stock: StockCandidate, cfg: Config) -> ScoredCandidate:
    """Score a candidate on fundamentals + momentum only — no social input.

    Used for the standalone "FMP prospects" list: the composite here is
    re-weighted across just fundamental/momentum (rather than reusing
    ``score_candidate`` with a zero social score, which would silently dilute
    the composite by averaging in a phantom zero for the unused weight).
    """
    f_score, f_reasons = score_fundamental(stock, cfg)
    m_score, m_reasons = score_momentum(stock)

    wsum = cfg.weight_fundamental + cfg.weight_momentum
    wsum = wsum or 1.0
    composite = (cfg.weight_fundamental * f_score + cfg.weight_momentum * m_score) / wsum

    return ScoredCandidate(
        symbol=stock.symbol,
        stock=stock,
        reddit=None,
        fundamental_score=f_score,
        momentum_score=m_score,
        social_score=0.0,
        composite_score=composite,
        reasons=f_reasons + m_reasons,
        flags=risk_flags(stock, None, cfg),
    )


def rank_fmp_only(
    stocks: Dict[str, StockCandidate], cfg: Config
) -> list[ScoredCandidate]:
    """Fundamentals+momentum-only ranking — the standalone FMP prospects list."""
    out = [score_candidate_fmp_only(stock, cfg) for stock in stocks.values()]
    out.sort(key=lambda c: c.composite_score, reverse=True)
    return out

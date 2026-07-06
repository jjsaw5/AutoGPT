"""Stage 1 — Universe & idea generation (spec §3, two-tier Option B).

Tier A: curated core watch from config, scanned every cycle.
Tier B: opportunistic pull-ins surfaced by UW market-wide feeds (flow alerts,
hottest chains, movers, OI change, vol anomalies). On the base API tier several
feeds are gated; those simply yield nothing and the scan proceeds on Tier A
plus whatever feeds are reachable.

Enrichment then hydrates each candidate's signal snapshot from FMP (backbone)
and UW (edge), caching per-ticker per-scan.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from ..clients import FMPClient, UnusualWhalesClient
from ..config import Config
from ..models import Candidate, CapTier, Tier

logger = logging.getLogger(__name__)


def _days_to_next_earnings(
    earnings: list[dict[str, Any]], today: date
) -> int | None:
    """Days until the nearest upcoming earnings date (>= today), else None."""
    best: int | None = None
    for row in earnings:
        raw = row.get("date") or row.get("earningsDate")
        if not raw:
            continue
        try:
            d = datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        delta = (d - today).days
        if delta >= 0 and (best is None or delta < best):
            best = delta
    return best


def build_universe(
    config: Config,
    uw: UnusualWhalesClient | None,
    *,
    tier_b_limit: int = 25,
) -> list[Candidate]:
    """Assemble Tier A (curated) + Tier B (feed-driven) candidate tickers."""
    seen: dict[str, Candidate] = {}

    # --- Tier A ---------------------------------------------------------------
    for ticker in config.universe.get("tier_a", []):
        sym = ticker.upper()
        seen[sym] = Candidate(ticker=sym, tier=Tier.A, source_feeds=["tier_a"])

    # --- Tier B (feed-driven) -------------------------------------------------
    if uw is not None:
        feeds = config.universe.get("tier_b_feeds", [])
        for sym, feed in _tier_b_nominees(uw, feeds, tier_b_limit):
            if sym in seen:
                if feed not in seen[sym].source_feeds:
                    seen[sym].source_feeds.append(feed)
                continue
            seen[sym] = Candidate(ticker=sym, tier=Tier.B, source_feeds=[feed])

    return list(seen.values())


def _tier_b_nominees(
    uw: UnusualWhalesClient, feeds: list[str], limit: int
) -> list[tuple[str, str]]:
    nominees: list[tuple[str, str]] = []

    def _pull(rows: list[dict[str, Any]], feed: str) -> None:
        for row in rows:
            sym = row.get("ticker") or row.get("symbol") or row.get("underlying_symbol")
            if isinstance(sym, str) and sym.isalpha():
                nominees.append((sym.upper(), feed))

    if "flow_alerts" in feeds:
        _pull(uw.market_flow_alerts(limit=limit), "flow_alerts")
    if "hottest_chains" in feeds:
        _pull(uw.hottest_chains(limit=limit), "hottest_chains")
    if "movers" in feeds:
        _pull(uw.movers(), "movers")
    if "oi_change" in feeds:
        _pull(uw.oi_change(limit=limit), "oi_change")
    if "vol_anomaly" in feeds:
        _pull(uw.vol_anomaly_top(limit=limit), "vol_anomaly")

    return nominees[: limit * 2]


def enrich_candidate(
    candidate: Candidate,
    fmp: FMPClient | None,
    uw: UnusualWhalesClient | None,
    config: Config,
) -> Candidate:
    """Hydrate a candidate's signal snapshot from FMP + UW."""
    signals: dict[str, Any] = {}

    if fmp is not None:
        snap = fmp.snapshot(candidate.ticker)
        signals.update(snap)
        candidate.market_cap = snap.get("market_cap")
        candidate.sector = snap.get("sector")
        candidate.price = snap.get("price")
        candidate.cap_tier = CapTier.from_market_cap(snap.get("market_cap"))
        earnings = fmp.earnings_calendar(candidate.ticker, limit=12)
        today = datetime.now(timezone.utc).date()
        signals["days_to_earnings"] = _days_to_next_earnings(earnings, today)
        # Past earnings dates + dated closes → independent expected-move model.
        signals["earnings_past"] = [
            str(r.get("date"))[:10] for r in earnings
            if r.get("date") and str(r.get("date"))[:10] < today.isoformat()
        ]
        series = fmp.historical_series(candidate.ticker, limit=120)
        signals["closes_dated"] = series
        signals["closes"] = [r["close"] for r in series]

    if uw is not None:
        ivr = uw.iv_rank(candidate.ticker)
        rvol = uw.realized_vol(candidate.ticker)
        signals["iv_rank"] = ivr.get("iv_rank")
        signals["iv"] = ivr.get("iv") or rvol.get("iv")
        signals["rv"] = rvol.get("rv")
        signals["net_prem"] = uw.net_prem_ticks(candidate.ticker)
        signals["flow_alerts"] = uw.flow_alerts(candidate.ticker, limit=20)
        signals["darkpool"] = uw.darkpool(candidate.ticker, limit=50)
        signals["term_structure"] = uw.term_structure(candidate.ticker)
        mp = uw.max_pain(candidate.ticker)
        signals["max_pain"] = mp.get("max_pain")

    candidate.signals = signals
    return candidate

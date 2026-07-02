"""Cross-scan persistence: which tickers keep showing up, day after day?

The original SLS example wasn't a one-day spike — it was "talked about on
Reddit for six months." A single scan can't see that; a stack of saved scans
can. This module reads the JSON files the CLI already writes into the scans
directory (``all --out`` payloads and ``social --out`` lists), groups them by
calendar day, and measures per-ticker persistence:

  days_seen       distinct scan-days the ticker appeared (within lookback)
  streak_days     consecutive scan-days ending at the most recent one
  mention_growth  latest mentions vs. the average of prior appearances

Streaks are counted over *scan-days* (days a scan file exists), not calendar
days, so weekends and skipped days don't break a streak unfairly.

Coverage note: saved social lists are truncated to the CLI's display top-N,
so persistence is measured among each day's top trending names — exactly the
population we care about.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .models import RedditSignal

log = logging.getLogger(__name__)

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass
class TrendRow:
    """Per-ticker persistence summary for the standalone trend report."""

    symbol: str
    days_seen: int
    days_total: int  # scan-days available in the window
    streak_days: int
    latest_mentions: int
    prior_avg_mentions: Optional[float]
    growth: Optional[float]
    subreddits: str  # from the most recent appearance

    def to_row(self) -> dict:
        return {
            "symbol": self.symbol,
            "days_seen": self.days_seen,
            "days_total": self.days_total,
            "streak_days": self.streak_days,
            "latest_mentions": self.latest_mentions,
            "prior_avg_mentions": round(self.prior_avg_mentions, 1)
            if self.prior_avg_mentions is not None
            else None,
            "growth": round(self.growth, 2) if self.growth is not None else None,
            "subreddits": self.subreddits,
        }


def _extract_social_rows(payload: object) -> Optional[List[dict]]:
    """Pull social-list rows out of a saved scan file, whatever its shape."""
    if isinstance(payload, dict) and isinstance(payload.get("social"), list):
        rows = payload["social"]
    elif isinstance(payload, list):
        rows = payload
    else:
        return None
    good = [r for r in rows if isinstance(r, dict) and "mentions_total" in r and "symbol" in r]
    return good if good else None


def load_social_snapshots(scans_dir: str) -> Dict[date, Dict[str, dict]]:
    """Read every scan file and return {scan_date: {symbol: social_row}}.

    The file's date comes from a YYYY-MM-DD in its name, falling back to the
    file's mtime. When several files land on the same date (e.g. a morning
    and an EOD run), rows are merged with the later file winning per symbol —
    a ticker present in either scan counts as present that day.
    """
    root = Path(scans_dir)
    if not root.is_dir():
        return {}

    dated_files: List[tuple] = []
    for path in sorted(root.glob("*.json")):
        m = _DATE_RE.search(path.name)
        if m:
            try:
                d = date.fromisoformat(m.group(1))
            except ValueError:
                d = datetime.fromtimestamp(path.stat().st_mtime).date()
        else:
            d = datetime.fromtimestamp(path.stat().st_mtime).date()
        dated_files.append((d, path.stat().st_mtime, path))

    snapshots: Dict[date, Dict[str, dict]] = {}
    for d, _mtime, path in sorted(dated_files, key=lambda t: (t[0], t[1])):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            log.debug("skipping unreadable scan file %s: %s", path, exc)
            continue
        rows = _extract_social_rows(payload)
        if rows is None:
            continue
        day = snapshots.setdefault(d, {})
        for row in rows:
            day[str(row["symbol"]).upper()] = row
    return snapshots


def _presence_stats(
    symbol: str,
    snapshots: Dict[date, Dict[str, dict]],
    scan_days: List[date],  # descending, most recent first
    present_today: bool,
    today: date,
) -> tuple:
    """(days_seen, streak_days, prior_mentions list) for one symbol."""
    days_seen = 1 if present_today else 0
    prior_mentions: List[float] = []
    for d in scan_days:
        if d == today:
            continue
        row = snapshots.get(d, {}).get(symbol)
        if row:
            days_seen += 1
            prior_mentions.append(float(row.get("mentions_total", 0) or 0))

    streak = 0
    for i, d in enumerate(scan_days):
        if d == today:
            present = present_today
        else:
            present = symbol in snapshots.get(d, {})
        if present:
            streak += 1
        else:
            break
    return days_seen, streak, prior_mentions


def annotate_signals(
    signals: Iterable[RedditSignal],
    scans_dir: str,
    lookback_days: int = 14,
    today: Optional[date] = None,
) -> int:
    """Set days_seen / streak_days / mention_growth on live signals in place.

    Today's live scan counts as a presence even before its file is written
    (same-day files merge into the same scan-day, so nothing double-counts).
    Returns how many signals had any prior-day history, so callers can log it.
    """
    snapshots = load_social_snapshots(scans_dir)
    today = today or date.today()
    cutoff = today.toordinal() - lookback_days
    window = {d: rows for d, rows in snapshots.items() if d.toordinal() >= cutoff}

    scan_days = sorted(set(window) | {today}, reverse=True)
    annotated = 0
    for sig in signals:
        days_seen, streak, prior = _presence_stats(
            sig.symbol, window, scan_days, present_today=True, today=today
        )
        sig.days_seen = days_seen
        sig.streak_days = streak
        if prior:
            avg_prior = sum(prior) / len(prior)
            if avg_prior > 0:
                sig.mention_growth = sig.mentions_total / avg_prior
            annotated += 1
    return annotated


def trend_report(
    scans_dir: str, lookback_days: int = 14, min_days: int = 2
) -> List[TrendRow]:
    """Standalone persistence report over saved scans (no live scan needed).

    Ranks by streak, then days seen, then mention growth — the top of this
    list is "what has retail been consistently talking about lately."
    """
    snapshots = load_social_snapshots(scans_dir)
    if not snapshots:
        return []
    latest_day = max(snapshots)
    cutoff = latest_day.toordinal() - lookback_days
    window = {d: rows for d, rows in snapshots.items() if d.toordinal() >= cutoff}
    scan_days = sorted(window, reverse=True)

    symbols = {sym for rows in window.values() for sym in rows}
    out: List[TrendRow] = []
    for sym in symbols:
        latest_row = window[latest_day].get(sym)
        days_seen, streak, prior = _presence_stats(
            sym, window, scan_days,
            present_today=latest_row is not None, today=latest_day,
        )
        if days_seen < min_days:
            continue
        latest_mentions = int(latest_row.get("mentions_total", 0)) if latest_row else 0
        avg_prior = sum(prior) / len(prior) if prior else None
        growth = (
            latest_mentions / avg_prior
            if latest_row and avg_prior and avg_prior > 0
            else None
        )
        raw_subs = latest_row.get("subreddits", "") if latest_row else ""
        subs = ",".join(raw_subs) if isinstance(raw_subs, list) else str(raw_subs)
        out.append(
            TrendRow(
                symbol=sym,
                days_seen=days_seen,
                days_total=len(scan_days),
                streak_days=streak,
                latest_mentions=latest_mentions,
                prior_avg_mentions=avg_prior,
                growth=growth,
                subreddits=subs,
            )
        )
    out.sort(
        key=lambda r: (r.streak_days, r.days_seen, r.growth or 0.0),
        reverse=True,
    )
    return out

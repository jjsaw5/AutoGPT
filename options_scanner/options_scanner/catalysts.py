"""Catalyst engine — the event-trigger overlay to the cadence (SESSION.md).

Surfaces a forward view of scheduled catalysts so a session is never blind to
what's coming. Three sources, no extra API calls:

* **Earnings** — reused from each scanned candidate's ``days_to_earnings`` (the
  scan already computes it for held + watched + universe names).
* **Macro** — FOMC / CPI / NFP from a *curated* config (``macro_calendar.yaml``),
  maintained each quarter from the Fed/BLS schedules. Reliable, no network.
* **OPEX** — monthly options expiration (3rd Friday), computed, not fetched.
* **Ex-dividend** — optional hook; wired later (needs a dividend feed).

The output is a "CATALYST RADAR" block in the readout. This is also the concrete
payoff of the SPY analysis: a macro print entering the window is exactly what
lifts a flow-only name's catalyst pillar toward GO, and now the readout says so.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


# Per-kind implication shown in the radar.
_MACRO_NOTE = {
    "fomc": "rate decision — market-wide vol; lifts flow-only catalyst pillars",
    "cpi": "inflation print — market-wide move risk",
    "nfp": "jobs report — market-wide move risk",
}


@dataclass
class CatalystEvent:
    date: str            # ISO YYYY-MM-DD
    days_out: int
    kind: str            # earnings | fomc | cpi | nfp | opex | exdiv
    scope: str           # ticker symbol, or "MARKET"
    label: str
    note: str = ""

    @property
    def is_market(self) -> bool:
        return self.scope == "MARKET"


def load_macro_calendar(path: str | Path) -> list[dict[str, Any]]:
    """Load curated macro events from YAML. Missing file / no yaml → empty."""
    p = Path(path)
    if yaml is None or not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data.get("events", []) if isinstance(data, dict) else []


def _third_friday(year: int, month: int) -> datetime.date:
    """Monthly options expiration — the 3rd Friday of the month."""
    d = datetime.date(year, month, 1)
    # weekday(): Mon=0 .. Fri=4. First Friday, then +14 days.
    first_friday = d + datetime.timedelta(days=(4 - d.weekday()) % 7)
    return first_friday + datetime.timedelta(days=14)


def opex_dates(start: datetime.date, end: datetime.date) -> list[datetime.date]:
    """OPEX dates (3rd Fridays) with start <= date <= end."""
    out: list[datetime.date] = []
    y, m = start.year, start.month
    while datetime.date(y, m, 1) <= end:
        opex = _third_friday(y, m)
        if start <= opex <= end:
            out.append(opex)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def build_radar(
    evaluated: Iterable[Any],
    *,
    now: datetime.datetime,
    horizon_days: int = 14,
    macro_events: Optional[list[dict[str, Any]]] = None,
    held_tickers: Optional[set[str]] = None,
) -> list[CatalystEvent]:
    """Assemble upcoming catalysts within the horizon, soonest first.

    ``evaluated`` are the scan's candidates (their theses carry days_to_earnings).
    ``held_tickers`` marks earnings on *held* names as risk vs. opportunity.
    """
    today = now.date()
    end = today + datetime.timedelta(days=horizon_days)
    held = held_tickers or set()
    events: list[CatalystEvent] = []

    # --- earnings (reused from the scan; dedupe per ticker) ---
    seen: set[str] = set()
    for ec in evaluated:
        t = getattr(ec, "thesis", None)
        d2e = getattr(t, "days_to_earnings", None) if t else None
        tkr = getattr(ec, "ticker", None)
        if d2e is None or tkr is None or tkr in seen:
            continue
        if 0 <= d2e <= horizon_days:
            seen.add(tkr)
            date = today + datetime.timedelta(days=d2e)
            is_held = tkr in held
            note = ("IV-crush risk on long premium — review before it reports"
                    if is_held else "earnings catalyst going live")
            events.append(CatalystEvent(
                date=date.isoformat(), days_out=d2e, kind="earnings",
                scope=tkr, label=f"{tkr} earnings" + (" [HELD]" if is_held else ""),
                note=note,
            ))

    # --- macro (curated) ---
    for ev in (macro_events or []):
        try:
            d = datetime.date.fromisoformat(str(ev["date"]))
        except (KeyError, ValueError):
            continue
        if today <= d <= end:
            kind = str(ev.get("kind", "macro")).lower()
            events.append(CatalystEvent(
                date=d.isoformat(), days_out=(d - today).days, kind=kind,
                scope="MARKET", label=ev.get("label", kind.upper()),
                note=_MACRO_NOTE.get(kind, "market-wide event"),
            ))

    # --- OPEX (computed) ---
    for d in opex_dates(today, end):
        events.append(CatalystEvent(
            date=d.isoformat(), days_out=(d - today).days, kind="opex",
            scope="MARKET", label="Monthly OPEX",
            note="options expiration — pin/assignment risk near short strikes",
        ))

    events.sort(key=lambda e: (e.days_out, e.scope))
    return events


def render_radar(events: list[CatalystEvent], *, horizon_days: int = 14) -> str:
    """One-line-per-event radar block, soonest first."""
    lines = [f"[0] CATALYST RADAR  (next {horizon_days}d — earnings · macro · OPEX)"]
    if not events:
        lines.append("  (no scheduled catalysts in the window)")
        return "\n".join(lines) + "\n"
    for e in events:
        when = "today" if e.days_out == 0 else f"{e.days_out}d"
        lines.append(
            f"  {e.date} ({when:>5})  {e.kind.upper():<8} {e.scope:<8} "
            f"{e.label:<22} — {e.note}"
        )
    return "\n".join(lines) + "\n"

#!/usr/bin/env python3
"""
Pre-earnings TIME-STOP planner.

Replaces the old gate ("block any expiry that crosses earnings") with:
  buy the LIQUID monthly expiry in the DTE window, but AUTO-EXIT a couple days
  BEFORE earnings. This decouples expiry (chosen for liquidity) from the holding
  period (kept earnings-free), so liquid monthlies become usable without ever
  holding a long option through an IV-crush event.

Knobs:
  DTE_MIN/MAX   target expiry window (liquidity).
  EXIT_LEAD     exit this many days BEFORE the earnings date (the time-stop).
  MIN_RUNWAY    require at least this many days from today to the exit, else the
                thesis has too little room -> block. This is the key tuning knob:
                higher = more thesis room but fewer names; lower = more names,
                shorter holds.
  ENTRY_BUFFER  never enter within this many days before earnings (pre-ER IV ramp).
"""
import os, sys, json, urllib.request, urllib.parse
from datetime import timedelta, date

KEY = os.environ["FMP_API_KEY"]; BASE = "https://financialmodelingprep.com/stable"
DTE_MIN, DTE_MAX = 30, 60
EXIT_LEAD   = 2     # days before earnings to close (time-stop)
MIN_RUNWAY  = 21    # min days from today to the pre-ER exit (raised from 14 for more thesis room)
ENTRY_BUFFER = 5    # no entry within this many days before earnings

def get(path, **p):
    p["apikey"] = KEY
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(p)
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in (402, 429, 500, 502, 503): raise
    return []

def parse(d):
    y, m, dd = map(int, d.split("-")); return date(y, m, dd)

def next_earnings(sym, today):
    e = get("earnings", symbol=sym)
    fut = sorted(r["date"] for r in e if r.get("date", "") >= str(today))
    return parse(fut[0]) if fut else None

def plan(today, er):
    """Deterministic time-stop verdict for one name."""
    win_hi = today + timedelta(DTE_MAX)
    if er is None:
        return dict(verdict="BLOCK", exit=None, runway=None, note="no earnings date (never guess)")
    if er <= today + timedelta(ENTRY_BUFFER):
        return dict(verdict="BLOCK", exit=None, runway=(er - today).days,
                    note=f"ER in {(er-today).days}d — inside entry buffer")
    if er > win_hi:
        return dict(verdict="CLEAN", exit=None, runway=(win_hi - today).days,
                    note="ER after 30-60 DTE window — no time-stop needed")
    exit_d = er - timedelta(EXIT_LEAD)
    runway = (exit_d - today).days
    if runway < MIN_RUNWAY:
        return dict(verdict="BLOCK", exit=exit_d, runway=runway,
                    note=f"only {runway}d runway to pre-ER exit (<{MIN_RUNWAY}) — too little thesis time")
    return dict(verdict="TIME-STOP", exit=exit_d, runway=runway,
                note=f"buy liquid monthly 30-60 DTE; AUTO-EXIT {exit_d} ({EXIT_LEAD}d before ER {er})")

if __name__ == "__main__":
    today = date.today()
    syms = sys.argv[1:] or ["BILI","PFE","RIVN","AAL","SOFI","CCL","NKE","T","BAC","VZ","NOK","RIOT","KO","F","PYPL","RKT"]
    print(f"Today {today} | DTE {DTE_MIN}-{DTE_MAX} | time-stop {EXIT_LEAD}d pre-ER | min runway {MIN_RUNWAY}d | entry buffer {ENTRY_BUFFER}d\n")
    print(f"{'SYM':<6}{'NEXT_ER':<12}{'VERDICT':<11}{'EXIT':<12}{'RUNWAY':>7}  NOTE")
    for s in syms:
        er = next_earnings(s, today)
        p = plan(today, er)
        rw = str(p["runway"]) if p["runway"] is not None else "—"
        print(f"{s:<6}{str(er or '—'):<12}{p['verdict']:<11}{str(p['exit'] or '—'):<12}{rw:>7}  {p['note']}")

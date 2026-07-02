#!/usr/bin/env python3
"""Unusual Whales enrichment — Stage-2 (live-gate) CONFIRMATION layer.

Design principle (keeps the risk-first philosophy intact): UW does NOT drive
Stage-1 ranking. The FMP technical scan still SUGGESTS candidates over the full
120-name universe; UW is called only on the handful of live-gate survivors to
CONFIRM them. Two confirming signals:

  iv_rank(ticker)  -> REAL IV percentile at our 30-60 DTE horizon. This finally
                      makes the `IV-rank <= 70` rail enforceable — FMP has no
                      historical IV, so that rail was unverifiable and we were
                      hand-building iv_history.csv one quote at a time. Also
                      returns real IV (the HV proxy in scanner.py understates
                      it, e.g. MNST HV 16% vs real IV 28%) and the implied move.

  flow(ticker)     -> net options-flow sentiment for the session (net call/put
                      premium, bullish vs bearish premium, put/call vol ratio).
                      Does smart money AGREE with our directional thesis? A
                      technical signal the flow contradicts = CAUTION, not a veto.

  confirm(ticker, direction) -> combines both into a compact verdict for the
                      live-gate step. Never a primary trigger; a confirming gate.

Usage:  python3 uw.py TICKER [put|call]     (default: both directions shown)
Key:    env var UW_API_KEY (never hardcode — the repo must stay secret-free).
"""
import os, sys, json, urllib.request, urllib.parse, urllib.error

KEY = os.environ.get("UW_API_KEY")
BASE = "https://api.unusualwhales.com"
# User-Agent is required: the UW WAF 403s the default Python-urllib UA.
HEADERS = {"Authorization": f"Bearer {KEY}", "UW-CLIENT-API-ID": "100001",
           "User-Agent": "options-scanner/1.0"}
IV_RANK_MAX = 70          # mirrors the scanner rail — now backed by REAL data


def get(path, **params):
    if not KEY:
        raise RuntimeError("UW_API_KEY not set in environment")
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    last = None
    for _ in range(3):                       # retry transient blips
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503):
                raise
    raise last


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def iv_rank(ticker, dte=45):
    """Real IV percentile at ~dte horizon (linear-interpolated between the two
    bracketing points of the UW term structure). Returns dict or None."""
    try:
        rows = get(f"/api/stock/{ticker}/interpolated-iv")["data"]
    except Exception:
        return None
    pts = sorted(((int(r["days"]), _f(r["percentile"]), _f(r["volatility"]),
                   _f(r["implied_move_perc"])) for r in rows), key=lambda x: x[0])
    if not pts:
        return None
    lo = max((p for p in pts if p[0] <= dte), default=pts[0], key=lambda x: x[0])
    hi = min((p for p in pts if p[0] >= dte), default=pts[-1], key=lambda x: x[0])
    if lo[0] == hi[0]:
        pct, vol, move = lo[1], lo[2], lo[3]
    else:
        w = (dte - lo[0]) / (hi[0] - lo[0])
        pct = lo[1] + w * (hi[1] - lo[1])
        vol = lo[2] + w * (hi[2] - lo[2])
        move = lo[3] + w * (hi[3] - lo[3])
    return {"iv_rank": round(pct * 100), "iv_pct": round(vol * 100, 1),
            "implied_move_pct": round(move * 100, 1), "dte": dte}


_OV_CACHE = {}
def _options_volume(ticker):
    """options-volume row for a ticker, memoized per run (flow() and
    flow_persistence() both need it — one fetch, not two)."""
    if ticker not in _OV_CACHE:
        try:
            _OV_CACHE[ticker] = get(f"/api/stock/{ticker}/options-volume")["data"][0]
        except Exception:
            _OV_CACHE[ticker] = None
    return _OV_CACHE[ticker]


def flow(ticker):
    """Net options-flow sentiment for the current session. Returns dict or None.
    Primary bias = net_call_premium - net_put_premium (calls bought & puts sold
    -> bullish); cross-checked against bullish vs bearish premium."""
    d = _options_volume(ticker)
    if not d:
        return None
    cv, pv = _f(d.get("call_volume")), _f(d.get("put_volume"))
    bull, bear = _f(d.get("bullish_premium")), _f(d.get("bearish_premium"))
    ncp, npp = _f(d.get("net_call_premium")), _f(d.get("net_put_premium"))
    pc = round(pv / cv, 2) if cv else None
    net_dir = ((ncp or 0) - (npp or 0))           # >0 bullish, <0 bearish
    prem_dir = ((bull or 0) - (bear or 0))
    bias = "bullish" if net_dir > 0 else ("bearish" if net_dir < 0 else "neutral")
    # flag when the two independent reads disagree (mixed/uncertain flow)
    mixed = (net_dir > 0) != (prem_dir > 0)
    return {"pc_ratio": pc, "net_dir": round(net_dir), "prem_dir": round(prem_dir),
            "bullish_prem": bull, "bearish_prem": bear, "bias": bias, "mixed": mixed}


def flow_persistence(ticker, direction, days=5, min_dte=14, min_prem=30000):
    """Multi-day flow: is smart money BUILDING a position in our direction, or is
    today a blip? A one-day snapshot (flow()) can't tell — but our holds run weeks.
    Two independent reads, no reliance on the container clock (dates come from the
    data itself):
      A) volume TREND from options-volume 3d/7d/30d averages — is the thesis-
         direction's share of volume above its 30d baseline, and is total volume
         surging vs cooling?
      B) multi-day OPENING prints from flow-alerts — net ask-side premium put on
         in our direction over the last `days` sessions, expiry >= min_dte out
         (skip 0DTE/weekly scalps that don't reflect multi-week positioning).
    Verdict: ACCUMULATION / CONTRA / BUILDING / NEUTRAL."""
    want_call = (direction == "call")

    # ---- Part A: volume trend (reuses the cached options-volume row) ----
    d = _options_volume(ticker)
    partA = None
    if d:
        def dshare(cv, pv):
            cv, pv = _f(cv) or 0, _f(pv) or 0
            t = cv + pv
            if not t:
                return None
            return (cv / t) if want_call else (pv / t)
        today = dshare(d.get("call_volume"), d.get("put_volume"))
        d3 = dshare(d.get("avg_3_day_call_volume"), d.get("avg_3_day_put_volume"))
        d30 = dshare(d.get("avg_30_day_call_volume"), d.get("avg_30_day_put_volume"))
        tot_today = (_f(d.get("call_volume")) or 0) + (_f(d.get("put_volume")) or 0)
        tot_30 = (_f(d.get("avg_30_day_call_volume")) or 0) + (_f(d.get("avg_30_day_put_volume")) or 0)
        surge = round(tot_today / tot_30, 2) if tot_30 else None
        building = bool(today is not None and d30 is not None and d3 is not None
                        and today >= d30 and d3 >= d30)
        partA = {"dir_share_today": round(today * 100) if today else None,
                 "dir_share_3d": round(d3 * 100) if d3 else None,
                 "dir_share_30d": round(d30 * 100) if d30 else None,
                 "vol_surge": surge, "building": building}

    # ---- Part B: multi-day opening prints from flow-alerts ----
    partB = None
    try:
        rows = get("/api/option-trades/flow-alerts", ticker_symbol=ticker,
                   limit=200, min_premium=min_prem)["data"]
    except Exception:
        rows = None
    if rows is not None:
        import datetime as _dt

        def _keep(r):
            # single-leg only (unambiguous direction), skip near-dated scalps.
            # all_opening_trades is unusable (False on every row); volume_oi_ratio
            # instead flags likely NEW positioning (volume exceeding existing OI).
            if r.get("has_multileg") or not r.get("has_singleleg"):
                return False
            try:
                a = _dt.date.fromisoformat(r["created_at"][:10])
                e = _dt.date.fromisoformat(r["expiry"][:10])
            except Exception:
                return False
            return (e - a).days >= min_dte
        kept = [r for r in rows if _keep(r)]
        recent = sorted({r["created_at"][:10] for r in kept})[-days:]
        net_bull, n, used, new_pos = 0.0, 0, set(), 0
        for r in kept:
            dt0 = r["created_at"][:10]
            if dt0 not in recent:
                continue
            edge = (_f(r.get("total_ask_side_prem")) or 0) - (_f(r.get("total_bid_side_prem")) or 0)
            net_bull += edge if r.get("type") == "call" else -edge
            used.add(dt0); n += 1
            if (_f(r.get("volume_oi_ratio")) or 0) >= 1.0:      # volume > OI = new positioning
                new_pos += 1
        MIN_NET = 250000        # ignore near-zero net edge (noise, not positioning)
        opening_dir = ("bull" if net_bull > MIN_NET else
                       ("bear" if net_bull < -MIN_NET else "flat"))
        agree = (opening_dir == ("bull" if want_call else "bear")) and n >= 2
        contra = (opening_dir == ("bear" if want_call else "bull")) and n >= 2
        partB = {"net_bull_prem": round(net_bull), "days_active": len(used),
                 "n_alerts": n, "new_pos": new_pos, "agree": agree, "contra": contra}

    # ---- verdict ----
    building = bool(partA and partA["building"])
    agree = bool(partB and partB["agree"])
    contra = bool(partB and partB["contra"])
    if building and agree:
        verdict = "ACCUMULATION"          # sustained volume bias + opening prints agree
    elif contra:
        verdict = "CONTRA"                # opening size going the OTHER way
    elif building or agree:
        verdict = "BUILDING"              # one of the two reads supports it
    else:
        verdict = "NEUTRAL"
    return {"ticker": ticker, "direction": direction, "verdict": verdict,
            "partA": partA, "partB": partB}


def confirm(ticker, direction, dte=45):
    """Compact live-gate verdict. flow_confirms/iv_rank_ok are booleans the
    safety wrapper can read; nothing here places or blocks on its own."""
    iv = iv_rank(ticker, dte)
    fl = flow(ticker)
    persist = flow_persistence(ticker, direction)
    want = "bearish" if direction == "put" else "bullish"
    flow_confirms = bool(fl and fl["bias"] == want and not fl["mixed"])
    flow_contradicts = bool(fl and fl["bias"] != want and fl["bias"] != "neutral")
    iv_rank_ok = bool(iv and iv["iv_rank"] <= IV_RANK_MAX)
    return {"ticker": ticker, "direction": direction, "iv": iv, "flow": fl,
            "persist": persist,
            "flow_confirms": flow_confirms, "flow_contradicts": flow_contradicts,
            "iv_rank_ok": iv_rank_ok, "accumulation": persist["verdict"] == "ACCUMULATION",
            "distribution": persist["verdict"] == "CONTRA"}


def market_tide():
    """Whole-market options-flow sentiment TODAY (5-min net call/put premium).
    A FAST, forward-looking companion to the slow SPY-vs-MAs structural regime.
    Returns the latest cumulative read + intraday momentum, or None."""
    try:
        rows = get("/api/market/market-tide")["data"]
    except Exception:
        return None
    if not rows:
        return None

    def tide(b):                      # net directional premium: calls bought - puts bought
        return (_f(b.get("net_call_premium")) or 0) - (_f(b.get("net_put_premium")) or 0)

    now, openv = tide(rows[-1]), tide(rows[0])
    NEUTRAL = 50e6                     # market-wide $; below this = no clear lean
    bias = "bullish" if now > NEUTRAL else ("bearish" if now < -NEUTRAL else "neutral")
    return {"tide": round(now), "open_tide": round(openv), "momentum": round(now - openv),
            "net_volume": _f(rows[-1].get("net_volume")), "bias": bias,
            "trend": "improving" if now - openv > 0 else "deteriorating",
            "asof": rows[-1].get("timestamp")}


def regime_overlay(structural):
    """Combine the slow structural regime (SPY vs 50/200-DMA, from scanner.py)
    with today's fast market tide. SOFT overlay — informs sizing, never the sole
    gate. structural in {UPTREND, DOWNTREND, MIXED}. Returns dict incl. a note."""
    t = market_tide()
    if not t:
        return {"tide": None, "aligned": None, "diverge": None,
                "note": "tide n/a (set UW_API_KEY) — structural regime only"}
    aligned = ((structural == "UPTREND" and t["bias"] == "bullish") or
               (structural == "DOWNTREND" and t["bias"] == "bearish"))
    diverge = ((structural == "UPTREND" and t["bias"] == "bearish") or
               (structural == "DOWNTREND" and t["bias"] == "bullish"))
    if aligned:
        note = "ALIGNED — structure and today's flow agree; sleeve as normal."
    elif diverge:
        note = ("DIVERGENT — today's tape fights the structural trend. Treat NEW "
                "with-trend entries as marginal; hold counter-trend to zero today.")
    else:
        note = "NEUTRAL tide — no overlay adjustment."
    return {"tide": t, "aligned": aligned, "diverge": diverge, "note": note}


def fmt_tide(structural=None):
    ov = regime_overlay(structural) if structural else {"tide": market_tide(), "note": ""}
    t = ov["tide"]
    if not t:
        return "MARKET TIDE: n/a (set UW_API_KEY)"
    line = (f"MARKET TIDE {t['bias'].upper()}  (net ${t['tide']/1e6:+.0f}M, "
            f"{t['trend']} from ${t['open_tide']/1e6:+.0f}M open, "
            f"net_vol {t['net_volume']/1e3:+.0f}k)  as of {t['asof'][11:16]}")
    return line + (f"\n  OVERLAY: {ov['note']}" if ov.get("note") else "")


def _fmt(c):
    iv, fl = c["iv"], c["flow"]
    ivs = (f"IVr {iv['iv_rank']:>3}%  IV {iv['iv_pct']:>4}%  impl±{iv['implied_move_pct']:>4}%"
           if iv else "IV  n/a")
    fls = (f"flow {fl['bias']:>7} (P/C {fl['pc_ratio']}, net ${fl['net_dir']/1e6:+.1f}M)"
           + ("  MIXED" if fl and fl["mixed"] else "") if fl else "flow n/a")
    p = c.get("persist") or {}
    pA = p.get("partA") or {}
    pB = p.get("partB") or {}
    bp = (pB.get("net_bull_prem") or 0) / 1e6
    ps = ("persist n/a" if not (pA or pB) else
          f"persist {p.get('verdict','n/a'):<12} (dir-vol {pA.get('dir_share_today','?')}%"
          f" vs 30d {pA.get('dir_share_30d','?')}%, surge {pA.get('vol_surge','?')}x | "
          f"{pB.get('n_alerts','?')} prints/{pB.get('days_active','?')}d net ${bp:+.1f}M"
          f"{', '+str(pB.get('new_pos'))+' new' if pB.get('new_pos') else ''})")
    tags = []
    tags.append("IV-OK" if c["iv_rank_ok"] else "IV-HOT")
    if c["flow_confirms"]:
        tags.append("FLOW-CONFIRM")
    elif c["flow_contradicts"]:
        tags.append("FLOW-CONTRADICT")
    else:
        tags.append("flow-neutral")
    if c.get("accumulation"):
        tags.append("ACCUMULATION")
    elif c.get("distribution"):
        tags.append("DISTRIBUTION")
    return f"{c['ticker']:<6} {c['direction']:<4} | {ivs} | {fls}\n         {ps} | {'  '.join(tags)}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 uw.py TICKER [put|call]  |  python3 uw.py --tide [UPTREND|DOWNTREND|MIXED]")
        sys.exit(1)
    if sys.argv[1] in ("--tide", "-t", "tide"):
        print(fmt_tide(sys.argv[2].upper() if len(sys.argv) > 2 else None)); sys.exit(0)
    t = sys.argv[1].upper()
    dirs = [sys.argv[2].lower()] if len(sys.argv) > 2 else ["put", "call"]
    for d in dirs:
        print(_fmt(confirm(t, d)))

#!/usr/bin/env python3
"""
Directional options scanner — Stage 1 (weakness->PUTS / strength->CALLS).

Mirror architecture: a long put and a long call are defined-risk twins, so the
indicator engine is shared and only the direction-sensitive pieces flip:
  PUT  side ranks WEAKNESS  (buy puts on weak names)
  CALL side ranks STRENGTH  (buy calls on strong names)

Shared, direction-agnostic data (computed once per name):
  price, SMA50, SMA200, RSI14, 63d return, rel-strength vs SPY,
  20d low/high, 52wk low/high, MACD vs signal, ADX (trend quality).

Downstream (live, not here): earnings gate, delta band (sign flips by
direction), OI>=500, spread<=10% of mid, IV-rank<=70, safety wrapper.

Usage: python3 scanner.py [put|call|both]   (default: both)
"""
import os, sys, json, math, urllib.request, urllib.parse, concurrent.futures as cf

DTE_MID = 45          # midpoint of the 30-60 DTE window, used for premium estimate
TICKET_MAX = 350      # ~ RISK_PER_TRADE; a ticket is "affordable" at/under this

KEY = os.environ["FMP_API_KEY"]
BASE = "https://financialmodelingprep.com/stable"
DIRECTION = (sys.argv[1] if len(sys.argv) > 1 else "both").lower()

def get(path, **params):
    params["apikey"] = KEY
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(3):                      # retry transient proxy/quota blips
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (402, 429, 500, 502, 503):
                raise
    raise last

# Curated liquid, optionable universe (OI>=500 options exist) — used when the
# FMP screener is throttled (402) so the scanner never hard-fails on universe.
FALLBACK_UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AMD","NFLX","AVGO",
    "CRM","ADBE","ORCL","INTC","CSCO","QCOM","TXN","MU","PLTR","SMCI",
    "JPM","BAC","WFC","GS","MS","C","V","MA","AXP","PYPL","COIN","SOFI",
    "UNH","JNJ","PFE","MRK","ABBV","LLY","BMY","CVS","MRNA",
    "XOM","CVX","OXY","SLB","COP","WMT","COST","TGT","HD","LOW","NKE",
    "MCD","SBUX","DIS","BABA","BIDU","BILI","UBER","ABNB","DASH","SHOP",
    "T","VZ","KO","PEP","PG","BA","CAT","GE","F","GM","RIVN","DOCU","HOOD",
    "SNOW","CRWD","NET","DDOG","PANW","ZS","MARA","RIOT","SOUN","AI","DELL",
]

def series(symbol, n=320):
    """OHLC chronological (oldest->newest), capped to the most recent n bars."""
    d = get("historical-price-eod/full", symbol=symbol)
    rows = list(reversed(d[:n]))
    o = [float(x["open"]) for x in rows]
    h = [float(x["high"]) for x in rows]
    l = [float(x["low"]) for x in rows]
    c = [float(x["close"]) for x in rows]
    return o, h, l, c

# ---- indicator helpers (chronological input) ----
def sma(v, p):
    return sum(v[-p:]) / p if len(v) >= p else None

def ema_series(v, p):
    k = 2 / (p + 1); e = v[0]; out = [e]
    for x in v[1:]:
        e = x * k + e * (1 - k); out.append(e)
    return out

def rsi(v, p=14):
    if len(v) < p + 1: return None
    d = [v[i] - v[i - 1] for i in range(1, len(v))]
    ag = sum(x for x in d[:p] if x > 0) / p
    al = sum(-x for x in d[:p] if x < 0) / p
    for x in d[p:]:
        ag = (ag * (p - 1) + (x if x > 0 else 0)) / p
        al = (al * (p - 1) + (-x if x < 0 else 0)) / p
    if al == 0: return 100.0
    return 100 - 100 / (1 + ag / al)

def macd(v):
    if len(v) < 35: return None, None
    e12, e26 = ema_series(v, 12), ema_series(v, 26)
    line = [a - b for a, b in zip(e12, e26)]
    sig = ema_series(line, 9)
    return line[-1], sig[-1]

def adx(h, l, c, p=14):
    n = len(c)
    if n < 2 * p + 1: return None
    tr, pdm, mdm = [], [], []
    for i in range(1, n):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        mdm.append(dn if (dn > up and dn > 0) else 0.0)
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    def wilder(x):
        s = sum(x[:p]); out = [s]
        for v in x[p:]:
            s = s - s / p + v; out.append(s)
        return out
    atr, sp, sm = wilder(tr), wilder(pdm), wilder(mdm)
    pdi = [100 * sp[i] / atr[i] if atr[i] else 0 for i in range(len(atr))]
    mdi = [100 * sm[i] / atr[i] if atr[i] else 0 for i in range(len(atr))]
    dx = [100 * abs(pdi[i] - mdi[i]) / (pdi[i] + mdi[i]) if (pdi[i] + mdi[i]) else 0
          for i in range(len(atr))]
    if len(dx) < p: return None
    a = sum(dx[:p]) / p
    for v in dx[p:]:
        a = (a * (p - 1) + v) / p
    return a

def ret(v, p):
    return (v[-1] / v[-1 - p] - 1) * 100 if len(v) > p else None

def hv(v, p=20):
    """Annualized historical volatility from the last p daily log returns."""
    if len(v) < p + 1: return None
    r = [math.log(v[i] / v[i - 1]) for i in range(len(v) - p, len(v))]
    mu = sum(r) / len(r)
    var = sum((x - mu) ** 2 for x in r) / (len(r) - 1)
    return math.sqrt(var * 252)

def est_ticket(price, vol, dte=DTE_MID):
    """Est. cost (in $) of a near-the-money option: 0.4*S*sigma*sqrt(T), x100.
    Proxy for the +0.55-delta (or -0.55) single-contract debit. HV stands in for IV."""
    if not vol: return None
    return round(0.4 * price * vol * math.sqrt(dte / 365) * 100)

# ---- benchmark ----
_, _, _, spy_c = series("SPY")
spy_r63 = ret(spy_c, 63)

def metrics(sym):
    try:
        o, h, l, c = series(sym)
        if len(c) < 200: return None
        price = c[-1]
        s50, s200 = sma(c, 50), sma(c, 200)
        if not s50 or not s200: return None
        r = rsi(c); r63 = ret(c, 63)
        rel = (r63 - spy_r63) if r63 is not None else None
        ml, sgl = macd(c)
        adx_v = adx(h, l, c)
        hv_v = hv(c)
        return dict(
            sym=sym, price=price, s50=s50, s200=s200, rsi=r,
            pct50=(price / s50 - 1) * 100, pct200=(price / s200 - 1) * 100,
            rel=rel, golden=s50 > s200, death=s50 < s200,
            low20=min(l[-20:]), high20=max(h[-20:]),
            low52=min(l[-252:]), high52=max(h[-252:]),
            macd_bull=(ml is not None and sgl is not None and ml > sgl),
            adx=adx_v, hv=hv_v, est_ticket=est_ticket(price, hv_v))
    except Exception:
        return None

# ---- direction-sensitive scoring ----
def score_put(m):
    """WEAKNESS — higher = weaker = better put candidate."""
    p, s = 0.0, m
    below50, below200, death = s["price"] < s["s50"], s["price"] < s["s200"], s["death"]
    neg_rel = s["rel"] is not None and s["rel"] < 0
    support_break = s["price"] <= s["low20"] * 1.02
    rsi_weak = s["rsi"] is not None and s["rsi"] < 50
    p += 1.0*below50 + 1.0*below200 + 1.5*death + 1.0*neg_rel + 1.0*support_break + 1.0*rsi_weak
    p += min(2.0, max(0, -s["pct50"]) / 5)
    p += min(2.0, max(0, -s["pct200"]) / 10)
    if s["rel"] is not None: p += min(2.0, max(0, -s["rel"]) / 10)
    if s["rsi"] is not None and s["rsi"] < 30: p += 1.0
    if not s["macd_bull"]: p += 0.5                      # bearish momentum confirm
    flags = "".join(["D" if death else "-", "B" if support_break else "-"])
    return p, flags, False

def score_call(m):
    """STRENGTH — higher = stronger = better call candidate. Overbought = veto."""
    p, s = 0.0, m
    above50, above200, golden = s["price"] > s["s50"], s["price"] > s["s200"], s["golden"]
    pos_rel = s["rel"] is not None and s["rel"] > 0
    breakout = s["price"] >= s["high20"] * 0.98          # at/near 20d high
    rsi_strong = s["rsi"] is not None and s["rsi"] > 50
    p += 1.0*above50 + 1.0*above200 + 1.5*golden + 1.0*pos_rel + 1.0*breakout + 1.0*rsi_strong
    p += min(2.0, max(0, s["pct50"]) / 5)
    p += min(2.0, max(0, s["pct200"]) / 10)
    if s["rel"] is not None: p += min(2.0, max(0, s["rel"]) / 10)
    if s["macd_bull"]: p += 0.5                           # bullish momentum confirm
    if s["adx"] is not None and s["adx"] >= 20: p += 0.5  # trend quality
    overbought = s["rsi"] is not None and s["rsi"] > 80   # NEW guard, no put analog
    near_high = s["price"] >= s["high52"] * 0.98
    flags = "".join(["G" if golden else "-", "U" if breakout else "-",
                     "!" if overbought else "-"])
    return p, flags, overbought

# ---- universe (screener with curated fallback) ----
try:
    uni = get("company-screener", exchange="NASDAQ,NYSE",
              priceMoreThan=5, priceLowerThan=400, volumeMoreThan=2000000,
              marketCapMoreThan=2000000000, isActivelyTrading="true",
              isEtf="false", isFund="false", limit=250)
    syms = list(dict.fromkeys(r["symbol"] for r in uni if r["symbol"].isalpha()))[:120]
    src = "screener"
except urllib.error.HTTPError:
    syms = list(FALLBACK_UNIVERSE)
    src = "fallback list (screener 402)"
print(f"Universe: {len(syms)} liquid names [{src}] | SPY 63d = {spy_r63:+.1f}% | direction={DIRECTION}\n")

rows = []
with cf.ThreadPoolExecutor(max_workers=8) as ex:
    for m in ex.map(metrics, syms):
        if m: rows.append(m)

def table(title, scored, is_call):
    print(f"=== {title} (top 12) ===")
    hdr = (f"{'#':<3}{'SYM':<7}{'PRICE':>9}{'%v50':>7}{'%v200':>7}{'RSI':>5}"
           f"{'RELvSPY':>9}{'ADX':>6}{'HV%':>6}{'EST$':>6}{'FLAGS':>7}{'SCORE':>7}")
    print(hdr)
    for i, (m, sc, fl, veto) in enumerate(scored[:12], 1):
        tag = " OVERBOUGHT-VETO" if (is_call and veto) else ""
        print(f"{i:<3}{m['sym']:<7}{m['price']:>9.2f}{m['pct50']:>7.1f}{m['pct200']:>7.1f}"
              f"{(m['rsi'] or 0):>5.0f}{(m['rel'] or 0):>+9.1f}{(m['adx'] or 0):>6.0f}"
              f"{(m['hv'] or 0)*100:>6.0f}{(m['est_ticket'] or 0):>6}{fl:>7}{sc:>7.2f}{tag}")
    print()

def tickets(title, scored):
    """Prioritized view: candidates whose est. ~0.55-delta single-contract debit
    fits TICKET_MAX, sorted by signal strength. For eyeballing realistic tickets."""
    fit = [(m, sc) for (m, sc, fl, veto) in scored
           if not veto and m.get("est_ticket") and m["est_ticket"] <= TICKET_MAX]
    print(f"=== {title}: est. ticket <= ${TICKET_MAX} (HV-based, ~0.55delta ~ ATM) ===")
    if not fit:
        print("  (none fit the ticket from this universe)\n"); return
    print(f"{'SYM':<7}{'PRICE':>9}{'HV%':>6}{'EST_TICKET':>11}{'RSI':>5}{'ADX':>6}{'SCORE':>7}")
    for m, sc in fit[:10]:
        print(f"{m['sym']:<7}{m['price']:>9.2f}{(m['hv'] or 0)*100:>6.0f}"
              f"{'$'+str(m['est_ticket']):>11}{(m['rsi'] or 0):>5.0f}{(m['adx'] or 0):>6.0f}{sc:>7.2f}")
    print("  NOTE: estimate only — confirm live via OI>=500, spread<=10%, real delta/IV.\n")

out = {}
if DIRECTION in ("put", "both"):
    sp = sorted(((m,) + score_put(m) for m in rows), key=lambda x: -x[1])
    table("PUT candidates  — WEAKNESS  (flags: D=death-cross  B=support-break)", sp, False)
    tickets("PUT TICKETS (live-tradeable)", sp)
    out["puts"] = [{"sym": m["sym"], "score": round(s, 2), "est_ticket": m["est_ticket"]}
                   for m, s, _, _ in sp]
if DIRECTION in ("call", "both"):
    sc = sorted(((m,) + score_call(m) for m in rows), key=lambda x: -x[1])
    # actionable = strong but NOT overbought-vetoed
    actionable = [t for t in sc if not t[3]]
    table("CALL candidates — STRENGTH  (flags: G=golden-cross  U=20d-breakout  !=overbought)", sc, True)
    vetoed = [t[0]["sym"] for t in sc if t[3]][:8]
    if vetoed:
        print(f"  Overbought (RSI>80) vetoed from call list: {', '.join(vetoed)}\n")
    tickets("CALL TICKETS (scan-only)", sc)   # affordability-staged for eyeballing
    out["calls"] = [{"sym": m["sym"], "score": round(s, 2), "est_ticket": m["est_ticket"]}
                    for m, s, _, veto in actionable]

with open(os.path.join(os.path.dirname(__file__), "ranked_dir.json"), "w") as f:
    json.dump(out, f)
print("Saved ranked_dir.json")

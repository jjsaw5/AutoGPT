#!/usr/bin/env python3
"""
fmp.py -- Financial Modeling Prep data layer for Project Genesis + Exodus.

Reads the API key from state/fmp.env (FMP_API_KEY=...), never prints it, and
never invents a price/level: every number comes straight from the API response.
If a request fails, the command prints {"error": ...} and exits non-zero so the
skill can gate that candidate to WATCHLIST/NO TRADE instead of guessing.

Endpoint paths target FMP's "stable" API surface (see references/fmp-api-reference.md).
FMP periodically renames/relocates endpoints -- if a command starts erroring,
check that reference file and your plan's current docs before assuming the code
is wrong.

Daily response caching lives in state/cache/ to keep a paid plan's usage cheap;
each cache entry is keyed by endpoint+params+UTC date.
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("GENESIS_STATE_DIR") or (SCRIPT_DIR.parent / "state"))
ENV_FILE = STATE_DIR / "fmp.env"
CACHE_DIR = STATE_DIR / "cache"

BASE_URL = "https://financialmodelingprep.com/stable"
TIMEOUT_SECONDS = 20

BENCHMARKS = ["SPY", "QQQ", "IWM"]

# R:R formula constants (SKILL.md §7's "R:R >= 2:1" gate) -- CUSTOMIZE/backtest before changing.
# Mirrors SKILL.md §0's INITIAL_STOP (~10% below entry) as the risk leg. The reward leg has two
# regimes: a name still meaningfully below its 52-week high is measured against that prior high
# (the next real resistance); a name already at/near its high or breaking out has no overhead
# resistance to measure, so reward is instead projected as a multiple of ATR20 (a rough proxy for
# expected near-term continuation, not a promise).
RR_STOP_PCT = 10.0
RR_NEAR_HIGH_THRESHOLD_PCT = 3.0
RR_ATR_REWARD_MULTIPLE = 3.0
RR_MIN_RATIO = 2.0

# Universe filter defaults (SKILL.md §7 / playbooks.md "Universe rules") -- CUSTOMIZE/backtest.
# These used to be whatever CLI flags got typed in ad hoc each session; they're now real
# persisted defaults so a bare `fmp.py screener` call (what an actual scheduled scan runs)
# enforces the documented "quality, liquid universe" floor without the caller having to know
# to pass them. Still overridable via explicit --marketCapMoreThan etc. for a one-off query.
UNIVERSE_MARKET_CAP_FLOOR = 300_000_000       # $300M -- opens up quality small/mid-caps
UNIVERSE_PRICE_FLOOR = 5.0                    # matches the hard-scope penny-stock (<$5) exclusion
UNIVERSE_SHARE_VOLUME_FLOOR = 200_000         # coarse share-count pre-filter on the screener call
UNIVERSE_MIN_AVG_DOLLAR_VOL20 = 3_000_000     # the real liquidity gate -- checked post-screener,
                                               # since dollar volume (not share count) is what
                                               # actually matters for slippage/manipulation risk


def check_liquidity(avg_dollar_vol20, floor=UNIVERSE_MIN_AVG_DOLLAR_VOL20):
    """Pure function (no I/O) so it's unit-testable offline in selftest.py."""
    return avg_dollar_vol20 is not None and avg_dollar_vol20 >= floor


# "Ideal entry" (SKILL.md §7 "price <= 8% above ideal entry" gate) -- previously undefined prose.
ENTRY_MAX_PCT_ABOVE_IDEAL = 8.0


EARNINGS_GUARD_TRADING_DAYS = 7  # SKILL.md's "~5 trading days" guard, implemented as 7 here


def compute_ideal_entry(price, sma50, hi20, hi55, breakout20=False, breakout55=False,
                         max_pct_above=ENTRY_MAX_PCT_ABOVE_IDEAL):
    """Deterministic reference price for the SKILL.md §7 buy gate. Pure function (no I/O) so it's
    unit-testable offline in selftest.py.
    - Confirmed breaking out (new 55-day or 20-day high): ideal entry is the level just cleared --
      buying at/near the breakout, not chasing it days or weeks later.
    - Otherwise: ideal entry is the 50-day SMA -- the natural pullback/support level for "own the
      leader," which explicitly doesn't require a fresh breakout (SKILL.md §7 PRIMARY ENTRY).
    Returns None (gate fails) if there isn't enough data -- never guess a level.
    """
    if breakout55 and hi55 is not None:
        ideal_entry, method = hi55, "55-day breakout level"
    elif breakout20 and hi20 is not None:
        ideal_entry, method = hi20, "20-day breakout level"
    elif sma50 is not None:
        ideal_entry, method = sma50, "50-day SMA (pullback support)"
    else:
        return None

    if price is None or not ideal_entry:
        return None

    pct_above = round((price - ideal_entry) / ideal_entry * 100, 2)
    return {
        "ideal_entry": round(ideal_entry, 4),
        "pct_above_ideal_entry": pct_above,
        "entry_gate_pass": pct_above <= max_pct_above,
        "entry_method": method,
    }


# Confidence score (SKILL.md §7 "confidence >= 7" buy gate) -- previously ungraded prose ("Score
# 0-10 each") with no formula behind it. This scores MARGIN beyond the other independent hard
# gates -- it does NOT replace them. A candidate must pass trend_template_pass, rr_pass,
# liquidity_pass, entry_gate_pass, the earnings guard, AND the mandatory news check separately;
# confidence >= 7 is an ADDITIONAL requirement on top, not a substitute for any of them (e.g. NBIS
# scored 8/10 confidence on 2026-07-01 but was still correctly blocked by the news check).
CONFIDENCE_RS_STRONG = 50.0             # rs_vs_spy threshold for "clear leadership" (2 pts)
CONFIDENCE_RS_MODERATE = 15.0           # rs_vs_spy threshold for "real but modest" (1 pt)
CONFIDENCE_RR_STRONG = 3.0              # rr_ratio threshold for comfortably past the 2:1 minimum
CONFIDENCE_ENTRY_TIGHT_PCT = 2.0        # pct_above_ideal_entry threshold for "right at" the entry
CONFIDENCE_LIQUIDITY_STRONG_MULTIPLE = 3.0   # multiple of UNIVERSE_MIN_AVG_DOLLAR_VOL20
CONFIDENCE_EARNINGS_SAFE_DAYS = 15      # trading days out considered comfortably clear


def compute_confidence(trend_template_pass, rs_vs_spy, rr_ratio, pct_above_ideal_entry,
                        avg_dollar_vol20, earnings_trading_days_out):
    """0-10 confidence score. Pure function (no I/O) so it's unit-testable offline.

    trend_template_pass is a hard zero-out, not a scored dimension: a candidate that isn't a
    confirmed trend leader gets confidence=0 regardless of how good everything else looks --
    matching playbooks.md's original (never-implemented) "Trend template pass (hard requirement
    -- 0 if failed)" note. The remaining 5 dimensions (relative strength, R:R margin, entry
    quality, liquidity margin, earnings safety margin) each contribute 0-2 points on how far they
    clear their OWN separate hard gate's minimum, not just whether they clear it -- summing to a
    0-10 total. Missing data on any dimension scores that dimension 0 (fail closed), matching every
    other gate in this file.
    """
    if not trend_template_pass:
        return {
            "confidence": 0,
            "components": {
                "relative_strength": 0, "risk_reward": 0, "entry_quality": 0,
                "liquidity": 0, "earnings_safety": 0,
            },
            "reason": "trend_template_pass is false -- hard zero, not a partial score",
        }

    if rs_vs_spy is not None and rs_vs_spy >= CONFIDENCE_RS_STRONG:
        rs_pts = 2
    elif rs_vs_spy is not None and rs_vs_spy >= CONFIDENCE_RS_MODERATE:
        rs_pts = 1
    else:
        rs_pts = 0

    if rr_ratio is not None and rr_ratio >= CONFIDENCE_RR_STRONG:
        rr_pts = 2
    elif rr_ratio is not None and rr_ratio >= RR_MIN_RATIO:
        rr_pts = 1
    else:
        rr_pts = 0

    if pct_above_ideal_entry is not None and pct_above_ideal_entry <= CONFIDENCE_ENTRY_TIGHT_PCT:
        entry_pts = 2
    elif pct_above_ideal_entry is not None and pct_above_ideal_entry <= ENTRY_MAX_PCT_ABOVE_IDEAL:
        entry_pts = 1
    else:
        entry_pts = 0

    strong_liquidity_floor = UNIVERSE_MIN_AVG_DOLLAR_VOL20 * CONFIDENCE_LIQUIDITY_STRONG_MULTIPLE
    if avg_dollar_vol20 is not None and avg_dollar_vol20 >= strong_liquidity_floor:
        liq_pts = 2
    elif avg_dollar_vol20 is not None and avg_dollar_vol20 >= UNIVERSE_MIN_AVG_DOLLAR_VOL20:
        liq_pts = 1
    else:
        liq_pts = 0

    if earnings_trading_days_out is not None and earnings_trading_days_out >= CONFIDENCE_EARNINGS_SAFE_DAYS:
        earn_pts = 2
    elif earnings_trading_days_out is not None and earnings_trading_days_out > EARNINGS_GUARD_TRADING_DAYS:
        earn_pts = 1
    else:
        earn_pts = 0

    return {
        "confidence": rs_pts + rr_pts + entry_pts + liq_pts + earn_pts,
        "components": {
            "relative_strength": rs_pts,
            "risk_reward": rr_pts,
            "entry_quality": entry_pts,
            "liquidity": liq_pts,
            "earnings_safety": earn_pts,
        },
        "reason": None,
    }


def compute_reward_risk(price, high52, atr20, breakout20=False, breakout55=False,
                         stop_pct=RR_STOP_PCT,
                         near_high_threshold_pct=RR_NEAR_HIGH_THRESHOLD_PCT,
                         atr_multiple=RR_ATR_REWARD_MULTIPLE):
    """Deterministic reward:risk for the SKILL.md §7 buy gate. Pure function (no I/O) so it's
    unit-testable offline in selftest.py. Returns None if there isn't enough data to judge it --
    callers must treat that as a gate FAILURE (SKILL.md's honesty rule: never guess a level)."""
    if price is None or not price or high52 is None or not high52:
        return None

    pct_from_high = (price - high52) / high52 * 100  # <= 0; 0 means at/above the 52wk high
    near_high_or_breaking_out = pct_from_high >= -near_high_threshold_pct or breakout20 or breakout55

    if near_high_or_breaking_out:
        if atr20 is None:
            return None
        reward_pct = atr_multiple * (atr20 / price) * 100
        reward_method = f"{atr_multiple}x ATR20 (price at/near its 52wk high or breaking out)"
    else:
        reward_pct = -pct_from_high
        reward_method = "distance to prior 52wk high"

    rr_ratio = round(reward_pct / stop_pct, 2) if stop_pct else None
    return {
        "reward_pct": round(reward_pct, 2),
        "risk_pct": stop_pct,
        "rr_ratio": rr_ratio,
        "rr_pass": rr_ratio is not None and rr_ratio >= RR_MIN_RATIO,
        "reward_method": reward_method,
    }


def out(obj):
    print(json.dumps(obj, indent=2, sort_keys=True))


def fail(message, **extra):
    out({"error": message, **extra})
    sys.exit(1)


def load_api_key():
    key = os.environ.get("FMP_API_KEY")
    if key:
        return key
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "FMP_API_KEY":
                v = v.strip()
                if v:
                    return v
    return None


def _cache_path(endpoint, params):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key_src = endpoint + "?" + urllib.parse.urlencode(sorted(params.items()))
    digest = hashlib.sha256(key_src.encode()).hexdigest()[:24]
    safe_endpoint = endpoint.strip("/").replace("/", "_")
    return CACHE_DIR / f"{today}_{safe_endpoint}_{digest}.json"


def _get(endpoint, params=None, use_cache=True):
    params = dict(params or {})
    api_key = load_api_key()
    if not api_key:
        fail(
            "FMP_API_KEY not set. Create state/fmp.env with FMP_API_KEY=<your key> "
            "(see state/fmp.env.example)."
        )

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_path(endpoint, params)
    if use_cache and cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except json.JSONDecodeError:
            pass

    params["apikey"] = api_key
    url = f"{BASE_URL}/{endpoint.lstrip('/')}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "genesis-exodus-scanner/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        fail(f"FMP HTTP error {e.code} on {endpoint}", detail=e.reason)
    except urllib.error.URLError as e:
        fail(f"FMP network error on {endpoint}", detail=str(e.reason))
    except TimeoutError:
        fail(f"FMP request timed out on {endpoint}")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        fail(f"FMP returned non-JSON for {endpoint}", raw=body[:300])

    if isinstance(data, dict) and data.get("Error Message"):
        fail(f"FMP error on {endpoint}: {data['Error Message']}")

    if use_cache:
        try:
            cache_file.write_text(json.dumps(data))
        except OSError:
            pass
    return data


# ------------------------------------------------------------- indicators

def sma(values, period):
    if len(values) < period:
        return None
    window = values[:period]
    return round(sum(window) / period, 4)


def _closes(symbol, days=260):
    hist = _get("historical-price-eod/full", {"symbol": symbol}, use_cache=True)
    rows = hist.get("historical", hist) if isinstance(hist, dict) else hist
    if not isinstance(rows, list) or not rows:
        fail(f"no historical data for {symbol}")
    # FMP returns most-recent-first.
    closes = [r["close"] for r in rows[:days] if "close" in r]
    highs = [r["high"] for r in rows[:days] if "high" in r]
    lows = [r["low"] for r in rows[:days] if "low" in r]
    volumes = [r.get("volume", 0) for r in rows[:days] if "close" in r]
    dates = [r["date"] for r in rows[:days] if "date" in r]
    return {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes, "dates": dates}


def _atr(highs, lows, closes, period):
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(period):
        h, l, prev_c = highs[i], lows[i], closes[i + 1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    return round(sum(trs) / period, 4)


# ------------------------------------------------------------------ regime

def cmd_regime(args):
    signals = {}
    weak_count = 0
    for sym in BENCHMARKS:
        try:
            series = _closes(sym, days=260)
        except SystemExit:
            raise
        closes = series["closes"]
        price = closes[0]
        sma50 = sma(closes, 50)
        sma200 = sma(closes, 200)
        above50 = sma50 is not None and price > sma50
        above200 = sma200 is not None and price > sma200
        signals[sym] = {
            "price": price,
            "sma50": sma50,
            "sma200": sma200,
            "above_sma50": above50,
            "above_sma200": above200,
        }
        if not above50 and not above200:
            weak_count += 1

    try:
        vix = _get("quote", {"symbol": "^VIX"})
        vix_level = vix[0]["price"] if isinstance(vix, list) and vix else None
    except SystemExit:
        vix_level = None

    if vix_level is not None and vix_level >= 30 and weak_count >= 2:
        regime = "crash"
    elif weak_count >= 2 or (vix_level is not None and vix_level >= 25):
        regime = "defensive"
    elif weak_count == 1 or (vix_level is not None and vix_level >= 20):
        regime = "cautious"
    else:
        regime = "normal"

    out({"regime": regime, "vix": vix_level, "benchmarks": signals})


# ---------------------------------------------------------------- screener

def cmd_screener(args):
    params = {"isEtf": "false", "isFund": "false", "isActivelyTrading": "true"}
    if args.marketCapMoreThan:
        params["marketCapMoreThan"] = args.marketCapMoreThan
    if args.marketCapLowerThan:
        params["marketCapLowerThan"] = args.marketCapLowerThan
    if args.priceMoreThan:
        params["priceMoreThan"] = args.priceMoreThan
    if args.volumeMoreThan:
        params["volumeMoreThan"] = args.volumeMoreThan
    if args.exchange:
        params["exchange"] = args.exchange
    if args.sector:
        params["sector"] = args.sector
    params["limit"] = args.limit
    data = _get("company-screener", params, use_cache=True)
    out(data)


# ------------------------------------------------------------------ movers

def cmd_movers(args):
    gainers = _get("biggest-gainers", {}, use_cache=True)
    losers = _get("biggest-losers", {}, use_cache=True)
    actives = _get("most-actives", {}, use_cache=True)
    out({"gainers": gainers, "losers": losers, "most_actives": actives})


# -------------------------------------------------------------- indicators

def gather_indicators(symbol):
    """Does the actual work for `indicators` -- factored out so `confidence` (which also needs
    earnings data from a separate endpoint) can reuse it without a second network round-trip
    for the same series."""
    series = _closes(symbol, days=260)
    closes, highs, lows, volumes = series["closes"], series["highs"], series["lows"], series["volumes"]
    price = closes[0]

    sma50, sma150, sma200 = sma(closes, 50), sma(closes, 150), sma(closes, 200)
    sma200_prev = sma(closes[20:], 200) if len(closes) >= 220 else None
    sma200_rising = sma200 is not None and sma200_prev is not None and sma200 > sma200_prev

    hi52 = max(highs[:252]) if highs else None
    lo52 = min(lows[:252]) if lows else None
    pct_from_hi = round((price - hi52) / hi52 * 100, 2) if hi52 else None
    pct_from_lo = round((price - lo52) / lo52 * 100, 2) if lo52 else None

    hi20 = max(highs[1:21]) if len(highs) > 21 else None
    hi55 = max(highs[1:56]) if len(highs) > 56 else None
    breakout20 = hi20 is not None and price > hi20
    breakout55 = hi55 is not None and price > hi55

    atr20 = _atr(highs, lows, closes, 20)
    atr14 = _atr(highs, lows, closes, 14)

    ret63d = round((price / closes[63] - 1) * 100, 2) if len(closes) > 63 else None

    rs_vs_spy = None
    try:
        spy = _closes("SPY", days=260)
        if len(spy["closes"]) > 63 and len(closes) > 63:
            spy_ret = spy["closes"][0] / spy["closes"][63] - 1
            sym_ret = closes[0] / closes[63] - 1
            rs_vs_spy = round((sym_ret - spy_ret) * 100, 2)
    except SystemExit:
        pass

    trend_template_pass = bool(
        sma50 and sma150 and sma200
        and price > sma150 and price > sma200
        and sma150 > sma200
        and sma200_rising
        and price > sma50
        and (pct_from_lo is None or pct_from_lo >= 30)
        and (pct_from_hi is None or pct_from_hi >= -25)
    )

    avg_dollar_vol20 = None
    if len(volumes) >= 20 and len(closes) >= 20:
        avg_dollar_vol20 = round(
            sum(v * c for v, c in zip(volumes[:20], closes[:20])) / 20, 2
        )
    liquidity_pass = check_liquidity(avg_dollar_vol20)

    fundamentals = {}
    try:
        prof = _get("profile", {"symbol": symbol})
        if isinstance(prof, list) and prof:
            fundamentals["marketCap"] = prof[0].get("marketCap")
    except SystemExit:
        pass

    rr = compute_reward_risk(price, hi52, atr20, breakout20, breakout55)
    entry = compute_ideal_entry(price, sma50, hi20, hi55, breakout20, breakout55)

    return {
        "symbol": symbol,
        "price": price,
        "sma50": sma50,
        "sma150": sma150,
        "sma200": sma200,
        "sma200_rising": sma200_rising,
        "52wk_high": hi52,
        "52wk_low": lo52,
        "pct_from_52wk_high": pct_from_hi,
        "pct_from_52wk_low": pct_from_lo,
        "20d_high": hi20,
        "55d_high": hi55,
        "breakout20": breakout20,
        "breakout55": breakout55,
        "ideal_entry": entry["ideal_entry"] if entry else None,
        "pct_above_ideal_entry": entry["pct_above_ideal_entry"] if entry else None,
        "entry_gate_pass": entry["entry_gate_pass"] if entry else False,
        "entry_method": entry["entry_method"] if entry else None,
        "reward_pct": rr["reward_pct"] if rr else None,
        "risk_pct": rr["risk_pct"] if rr else None,
        "rr_ratio": rr["rr_ratio"] if rr else None,
        "rr_pass": rr["rr_pass"] if rr else False,
        "reward_method": rr["reward_method"] if rr else None,
        "atr20": atr20,
        "atr14": atr14,
        "ret63d": ret63d,
        "rs_vs_spy": rs_vs_spy,
        "trend_template_pass": trend_template_pass,
        "avgDollarVol20": avg_dollar_vol20,
        "liquidity_pass": liquidity_pass,
        "marketCap": fundamentals.get("marketCap"),
    }


def cmd_indicators(args):
    out(gather_indicators(args.symbol.upper()))


def cmd_confidence(args):
    symbol = args.symbol.upper()
    ind = gather_indicators(symbol)
    earn = _next_earnings(symbol)
    trading_days_out = earn["trading_days_out_approx"] if earn else None

    conf = compute_confidence(
        ind["trend_template_pass"], ind["rs_vs_spy"], ind["rr_ratio"],
        ind["pct_above_ideal_entry"], ind["avgDollarVol20"], trading_days_out,
    )

    out({
        "symbol": symbol,
        "confidence": conf["confidence"],
        "confidence_pass": conf["confidence"] >= 7,
        "components": conf["components"],
        "reason": conf["reason"],
        "underlying": {
            "trend_template_pass": ind["trend_template_pass"],
            "rs_vs_spy": ind["rs_vs_spy"],
            "rr_ratio": ind["rr_ratio"],
            "rr_pass": ind["rr_pass"],
            "pct_above_ideal_entry": ind["pct_above_ideal_entry"],
            "entry_gate_pass": ind["entry_gate_pass"],
            "avgDollarVol20": ind["avgDollarVol20"],
            "liquidity_pass": ind["liquidity_pass"],
            "next_earnings": earn,
        },
    })


# --------------------------------------------------------------- earnings

def _next_earnings(symbol):
    data = _get("earnings", {"symbol": symbol}, use_cache=True)
    rows = data if isinstance(data, list) else []
    today = datetime.now(timezone.utc).date()
    upcoming = None
    for r in rows:
        d = r.get("date")
        if not d:
            continue
        try:
            rd = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            continue
        if rd >= today and (upcoming is None or rd < upcoming["date"]):
            upcoming = {"date": rd, "raw": r}
    if not upcoming:
        return None
    days_out = (upcoming["date"] - today).days
    return {"date": str(upcoming["date"]), "trading_days_out_approx": days_out}


def cmd_earnings(args):
    symbol = args.symbol.upper()
    upcoming = _next_earnings(symbol)
    within_guard = upcoming is not None and upcoming["trading_days_out_approx"] <= EARNINGS_GUARD_TRADING_DAYS
    out({"symbol": symbol, "next_earnings": upcoming, "earnings_guard_block": within_guard})


# --------------------------------------------------------- biotech binary-event risk

# SKILL.md §7 hard-scopes "biotech binary-event gambles" out, but there's no clean automatable
# signal for it -- `industry == "Biotechnology"` alone is NOT enough (REGN and VRTX are massively
# profitable, diversified, not remotely a single-catalyst bet, yet FMP tags them "Biotechnology"
# same as a pre-revenue clinical-stage name). Revenue/profitability narrows it considerably but
# isn't bulletproof either -- verified on 2026-07-01 that FMP's revenue figure for ONTX (Onconova,
# a genuine small clinical-stage name) came back as $2.79B, which is obviously wrong for a $625M
# market-cap company (almost certainly a data/ticker-reuse artifact) and would have caused this
# heuristic to wrongly clear it. This is why the flag is a MANDATORY judgment prompt (like the news
# keyword scan), never an automatic block -- read the actual company, don't trust the flag alone.
BIOTECH_INDUSTRY_MARKER = "biotechnology"
BIOTECH_REVENUE_FLOOR = 500_000_000  # below this + biotech industry -> likely still pipeline-dependent


def assess_biotech_binary_risk(industry, revenue, net_income, revenue_floor=BIOTECH_REVENUE_FLOOR):
    """Pure function (no I/O) so it's unit-testable offline. Flags a candidate for a MANDATORY
    human/LLM read before buying -- it does not itself disqualify anything. See the module
    comment above for why this can't be a clean automatic gate (industry alone false-negatives on
    profitable biotechs like REGN/VRTX; revenue data can be simply wrong for thinly-covered names).
    """
    is_biotech_industry = bool(industry) and BIOTECH_INDUSTRY_MARKER in industry.lower()
    if not is_biotech_industry:
        return {"flagged": False, "reason": "not classified as Biotechnology industry"}

    if revenue is None:
        return {"flagged": True, "reason": "Biotechnology industry with no revenue data available"}
    if revenue < revenue_floor:
        return {
            "flagged": True,
            "reason": f"Biotechnology industry with revenue (${revenue:,.0f}) below the "
                      f"${revenue_floor:,.0f} floor -- likely still substantially pipeline-dependent",
        }
    if net_income is not None and net_income < 0 and abs(net_income) > revenue:
        return {
            "flagged": True,
            "reason": f"Biotechnology industry, revenue (${revenue:,.0f}) clears the floor but net "
                      f"loss (${net_income:,.0f}) exceeds total revenue -- still burning more on the "
                      f"pipeline than the commercial business brings in",
        }
    return {"flagged": False, "reason": "Biotechnology industry but revenue/profitability look established"}


def cmd_biotech_check(args):
    symbol = args.symbol.upper()
    industry = None
    revenue = None
    net_income = None
    try:
        prof = _get("profile", {"symbol": symbol})
        if isinstance(prof, list) and prof:
            industry = prof[0].get("industry")
    except SystemExit:
        pass
    try:
        income = _get("income-statement", {"symbol": symbol, "period": "annual", "limit": 1}, use_cache=True)
        if isinstance(income, list) and income:
            revenue = income[0].get("revenue")
            net_income = income[0].get("netIncome")
    except SystemExit:
        pass

    assessment = assess_biotech_binary_risk(industry, revenue, net_income)
    out({
        "symbol": symbol,
        "industry": industry,
        "revenue": revenue,
        "net_income": net_income,
        "flagged": assessment["flagged"],
        "reason": assessment["reason"],
    })


def cmd_earnings_multi(args):
    results = {}
    for symbol in args.symbols:
        symbol = symbol.upper()
        try:
            upcoming = _next_earnings(symbol)
            within_guard = upcoming is not None and upcoming["trading_days_out_approx"] <= EARNINGS_GUARD_TRADING_DAYS
            results[symbol] = {"next_earnings": upcoming, "earnings_guard_block": within_guard}
        except SystemExit:
            results[symbol] = {"error": "lookup failed"}
    out(results)


# --------------------------------------------------------- advisory sensors

# Keyword-flag assist for the SKILL.md §7 mandatory news check. This is deliberately NOT a verdict:
# it's a cheap, deterministic first pass that flags articles worth reading closely. It can both
# false-positive (a keyword appearing in an unrelated or even positive context) and false-negative
# (real bad news phrased without any listed word) -- the LLM must still read the actual headlines
# and make the final pass/fail call. CUSTOMIZE/extend this list as real scans surface misses.
NEWS_NEGATIVE_KEYWORDS = [
    "lawsuit", "investigation", "probe", "downgrade", "guidance cut", "cuts guidance",
    "cut its forecast", "misses estimates", "miss estimates", "recall", "fraud", "resigns",
    "resignation", "scandal", "competitor", "competition", "threat", "layoffs", "bankruptcy",
    "delisting", "restatement", "warns", "warning", "plunge", "crash", "crashing", "tumble",
    "tumbles", "sinks", "slashed", "slumps", "slump", "loses customer", "customer loss",
    "antitrust", "regulatory action", "class action", "short seller", "short-seller",
    "accounting issue", "data breach", "recession",
]


def scan_news_for_negative_catalysts(articles, keywords=NEWS_NEGATIVE_KEYWORDS):
    """Pure function (no I/O) so it's unit-testable offline in selftest.py. `articles` is the raw
    list of {"title":..., "text":...} dicts as returned by the FMP news endpoint."""
    matched_articles = []
    all_matched_keywords = set()
    for article in articles or []:
        haystack = f"{article.get('title', '')} {article.get('text', '')}".lower()
        hits = sorted({kw for kw in keywords if kw in haystack})
        if hits:
            matched_articles.append({"title": article.get("title"), "matched_keywords": hits})
            all_matched_keywords.update(hits)
    return {
        "flagged": bool(matched_articles),
        "matched_keywords": sorted(all_matched_keywords),
        "matched_articles": matched_articles,
    }


def cmd_news(args):
    results = {}
    for symbol in args.symbols:
        symbol = symbol.upper()
        articles = _get("news/stock", {"symbols": symbol, "limit": 10}, use_cache=True)
        articles_list = articles if isinstance(articles, list) else []
        results[symbol] = {
            "articles": articles,
            "negative_keyword_scan": scan_news_for_negative_catalysts(articles_list),
        }
    out(results)


def cmd_rs(args):
    symbol = args.symbol.upper()
    series = _closes(symbol, days=260)
    closes = series["closes"]
    spy = _closes("SPY", days=260)["closes"]
    windows = {"21d": 21, "63d": 63, "126d": 126, "252d": 252}
    blended = []
    detail = {}
    for label, n in windows.items():
        if len(closes) > n and len(spy) > n:
            sym_ret = closes[0] / closes[n] - 1
            spy_ret = spy[0] / spy[n] - 1
            rel = round((sym_ret - spy_ret) * 100, 2)
            detail[label] = rel
            blended.append(rel)
    blended_score = round(sum(blended) / len(blended), 2) if blended else None
    out({"symbol": symbol, "relative_strength_by_window": detail, "blended_rs": blended_score})


def cmd_correlation(args):
    series = {}
    for symbol in args.symbols:
        symbol = symbol.upper()
        closes = _closes(symbol, days=90)["closes"]
        rets = [closes[i] / closes[i + 1] - 1 for i in range(len(closes) - 1)]
        series[symbol] = rets

    def pearson(a, b):
        n = min(len(a), len(b))
        if n < 2:
            return None
        a, b = a[:n], b[:n]
        mean_a, mean_b = sum(a) / n, sum(b) / n
        cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
        var_a = sum((x - mean_a) ** 2 for x in a)
        var_b = sum((y - mean_b) ** 2 for y in b)
        if var_a == 0 or var_b == 0:
            return None
        return round(cov / (var_a ** 0.5 * var_b ** 0.5), 3)

    symbols = list(series.keys())
    matrix = {}
    for i, s1 in enumerate(symbols):
        matrix[s1] = {}
        for s2 in symbols:
            matrix[s1][s2] = pearson(series[s1], series[s2])
    out({"correlation_matrix": matrix})


def cmd_breadth(args):
    sector_etfs = {
        "Technology": "XLK", "Financials": "XLF", "Health Care": "XLV",
        "Energy": "XLE", "Industrials": "XLI", "Consumer Discretionary": "XLY",
        "Consumer Staples": "XLP", "Utilities": "XLU", "Real Estate": "XLRE",
        "Materials": "XLB", "Communication Services": "XLC",
    }
    above = 0
    detail = {}
    for sector, etf in sector_etfs.items():
        try:
            closes = _closes(etf, days=210)["closes"]
            sma50v = sma(closes, 50)
            is_above = sma50v is not None and closes[0] > sma50v
            detail[sector] = {"etf": etf, "price": closes[0], "sma50": sma50v, "above_sma50": is_above}
            if is_above:
                above += 1
        except SystemExit:
            detail[sector] = {"etf": etf, "error": "lookup failed"}
    pct = round(above / len(sector_etfs) * 100, 1)
    out({"pct_sectors_above_sma50": pct, "detail": detail})


def cmd_rotation(args):
    ranks_file = STATE_DIR / "rs_ranks.json"
    history = {}
    if ranks_file.exists():
        try:
            history = json.loads(ranks_file.read_text())
        except json.JSONDecodeError:
            history = {}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snapshot = {}
    results = {}
    for symbol in args.symbols:
        symbol = symbol.upper()
        try:
            series = _closes(symbol, days=90)["closes"]
            ret21 = round((series[0] / series[21] - 1) * 100, 2) if len(series) > 21 else None
        except SystemExit:
            ret21 = None
        snapshot[symbol] = ret21
        prior = history.get(symbol, {}).get("ret21")
        rotation_candidate = (
            prior is not None and ret21 is not None and ret21 < prior and ret21 < 0
        )
        results[symbol] = {"ret21_pct": ret21, "prior_ret21_pct": prior, "rotation_candidate": rotation_candidate}

    history[today] = {sym: {"ret21": v} for sym, v in snapshot.items()}
    for sym, v in snapshot.items():
        history[sym] = {"ret21": v, "as_of": today}
    try:
        ranks_file.write_text(json.dumps(history, indent=2, sort_keys=True))
    except OSError:
        pass

    out(results)


def cmd_pricechange(args):
    results = {}
    for symbol in args.symbols:
        results[symbol.upper()] = _get("stock-price-change", {"symbol": symbol.upper()}, use_cache=True)
    out(results)


def cmd_scores(args):
    out(_get("scores", {"symbol": args.symbol.upper()}, use_cache=True))


def cmd_float(args):
    out(_get("shares-float", {"symbol": args.symbol.upper()}, use_cache=True))


def cmd_insider(args):
    out(_get("insider-trading/latest", {"symbol": args.symbol.upper(), "limit": 20}, use_cache=True))


def cmd_grades(args):
    out(_get("grades", {"symbol": args.symbol.upper()}, use_cache=True))


def cmd_sectors(args):
    out(_get("sector-performance-snapshot", {}, use_cache=True))


# ------------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(prog="fmp.py", description="Genesis + Exodus FMP data layer")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("regime", help="SPY/QQQ/IWM + VIX regime classification").set_defaults(func=cmd_regime)

    sp = sub.add_parser("screener", help="quality liquid US stock universe")
    sp.add_argument("--marketCapMoreThan", type=float, default=UNIVERSE_MARKET_CAP_FLOOR)
    sp.add_argument("--marketCapLowerThan", type=float)
    sp.add_argument("--priceMoreThan", type=float, default=UNIVERSE_PRICE_FLOOR)
    sp.add_argument("--volumeMoreThan", type=float, default=UNIVERSE_SHARE_VOLUME_FLOOR)
    sp.add_argument("--exchange")
    sp.add_argument("--sector")
    sp.add_argument("--limit", type=int, default=100)
    sp.set_defaults(func=cmd_screener)

    sub.add_parser("movers", help="gainers/losers/most-actives").set_defaults(func=cmd_movers)

    sp = sub.add_parser("indicators", help="full technical read on one symbol")
    sp.add_argument("symbol")
    sp.set_defaults(func=cmd_indicators)

    sp = sub.add_parser("confidence", help="0-10 confidence score for the SKILL.md buy gate")
    sp.add_argument("symbol")
    sp.set_defaults(func=cmd_confidence)

    sp = sub.add_parser("earnings", help="next-earnings guard for one symbol")
    sp.add_argument("symbol")
    sp.set_defaults(func=cmd_earnings)

    sp = sub.add_parser("biotech-check", help="biotech binary-event risk flag (mandatory prompt, not an auto-block)")
    sp.add_argument("symbol")
    sp.set_defaults(func=cmd_biotech_check)

    sp = sub.add_parser("earnings-multi", help="next-earnings guard for many symbols")
    sp.add_argument("symbols", nargs="+")
    sp.set_defaults(func=cmd_earnings_multi)

    sp = sub.add_parser("news", help="recent news for symbols")
    sp.add_argument("symbols", nargs="+")
    sp.set_defaults(func=cmd_news)

    sp = sub.add_parser("rs", help="blended relative strength vs SPY")
    sp.add_argument("symbol")
    sp.set_defaults(func=cmd_rs)

    sp = sub.add_parser("correlation", help="pairwise return correlation")
    sp.add_argument("symbols", nargs="+")
    sp.set_defaults(func=cmd_correlation)

    sub.add_parser("breadth", help="%% of sectors above 50-DMA").set_defaults(func=cmd_breadth)

    sp = sub.add_parser("rotation", help="leaderboard + rotation-out flags")
    sp.add_argument("symbols", nargs="+")
    sp.set_defaults(func=cmd_rotation)

    sp = sub.add_parser("pricechange", help="price change over standard windows")
    sp.add_argument("symbols", nargs="+")
    sp.set_defaults(func=cmd_pricechange)

    sp = sub.add_parser("scores", help="FMP composite scores")
    sp.add_argument("symbol")
    sp.set_defaults(func=cmd_scores)

    sp = sub.add_parser("float", help="shares float")
    sp.add_argument("symbol")
    sp.set_defaults(func=cmd_float)

    sp = sub.add_parser("insider", help="latest insider trading")
    sp.add_argument("symbol")
    sp.set_defaults(func=cmd_insider)

    sp = sub.add_parser("grades", help="analyst grades")
    sp.add_argument("symbol")
    sp.set_defaults(func=cmd_grades)

    sub.add_parser("sectors", help="sector performance snapshot").set_defaults(func=cmd_sectors)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

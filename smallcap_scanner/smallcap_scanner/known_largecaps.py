"""A maintained list of widely-known large/mega-cap tickers and index ETFs.

Purpose: ApeWisdom's raw mention rankings are dominated by a small set of
names (SPY, AMD, MSTR, NVDA, ...) that show up on every scan regardless of
day — they crowd out genuinely small-cap social activity sitting further
down the ranking before ``SOCIAL_FMP_LIMIT`` even gets to it. Excluding them
*before* spending the FMP lookup budget means that budget goes to names
actually worth checking.

This list is deliberately NOT exhaustive and will go stale (new mega-cap
IPOs, etc.) — that's fine. It's a cheap pre-filter, not the source of truth.
The real, accurate check is scoring.risk_flags()'s OUTSIDE_PRICE_RANGE /
OUTSIDE_MARKET_CAP_RANGE flags, computed from live FMP data after lookup,
which catch anything that slips past this list. Extend via the
EXTRA_LARGE_CAP_EXCLUSIONS env var rather than guessing at borderline names
(small/mid-caps belong in the dynamic check, not here).
"""

from __future__ import annotations

# Major index / leveraged / sector ETFs.
_ETFS = {
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "VEA", "VWO", "VXUS",
    "TQQQ", "SQQQ", "SOXL", "SOXS", "SPXL", "SPXS", "UPRO", "SPXU",
    "UVXY", "VXX", "SVXY", "ARKK", "ARKG", "ARKW",
    "XLF", "XLE", "XLK", "XLY", "XLP", "XLV", "XLI", "XLU", "XLB", "XLC", "XLRE",
    "SMH", "SOXX", "GDX", "GDXJ", "GLD", "SLV", "USO", "UNG",
    "HYG", "LQD", "TLT", "IEF", "SHY", "BND",
}

# Mega-cap tech / "Magnificent 7" and adjacent AI/semis/software names.
_TECH = {
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    "AMD", "AVGO", "ORCL", "CRM", "ADBE", "INTC", "QCOM", "TXN", "MU",
    "CSCO", "IBM", "NFLX", "PYPL", "UBER", "ABNB", "SNOW", "PLTR",
    "COIN", "SQ", "SHOP", "NOW", "INTU", "AMAT", "ASML", "ARM", "SMCI",
    "DELL", "HPQ", "MRVL", "NXPI", "ON", "LRCX", "KLAC", "PANW", "CRWD",
    "FTNT", "ANET", "WDAY", "TEAM", "DDOG", "NET", "ZS", "MDB",
}

# Large-cap financials.
_FINANCIALS = {
    "JPM", "BAC", "WFC", "C", "GS", "MS", "V", "MA", "AXP", "BLK",
    "SCHW", "COF", "USB", "PNC", "TFC", "BX", "KKR", "BRK.A", "BRK.B",
}

# Large-cap consumer, retail, industrial, healthcare, energy blue chips.
_BLUE_CHIPS = {
    "WMT", "COST", "HD", "LOW", "NKE", "MCD", "SBUX", "DIS", "TGT",
    "BABA", "PG", "KO", "PEP", "CL", "KMB", "JNJ", "PFE", "MRK", "ABBV",
    "LLY", "UNH", "CVS", "CI", "HUM", "XOM", "CVX", "COP", "OXY", "SLB",
    "CAT", "DE", "GE", "BA", "LMT", "RTX", "HON", "MMM", "UPS", "FDX",
    "T", "VZ", "TMUS", "CMCSA", "WBD", "ALL", "DTE", "IP", "ET", "BJ",
}

# Crypto-adjacent / frequently-meme'd large caps.
_OTHER = {
    "MSTR", "RIOT", "MARA", "HOOD", "SOFI", "SNDK", "BE", "GE", "ASML",
    "ALAB", "NBIS",
}

KNOWN_LARGE_CAP_TICKERS = _ETFS | _TECH | _FINANCIALS | _BLUE_CHIPS | _OTHER

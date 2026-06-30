"""Extract stock tickers from free-form Reddit text.

Two kinds of mentions:
  * cashtags  -> ``$SLS`` : high confidence, accepted even if unknown.
  * bare caps -> ``SLS``  : only accepted if the token is in a known-symbol set,
    because raw 1-5 letter uppercase tokens are mostly English/jargon noise.

A stopword list removes the common all-caps words (CEO, YOLO, DD, ...) that
would otherwise pollute bare-token matching.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Set

# Tokens that look like tickers but almost never are, in this context.
STOPWORDS: Set[str] = {
    # generic / web / finance jargon
    "A", "I", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "IF", "IN", "IS", "IT",
    "ME", "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US", "WE", "AM", "PM",
    "ALL", "AND", "ANY", "ARE", "BUY", "CAN", "DAY", "DID", "FOR", "GET", "GOT",
    "HAS", "HER", "HIM", "HIS", "HOW", "ITS", "LOW", "MAX", "MAY", "NEW", "NOT",
    "NOW", "OFF", "ONE", "OUR", "OUT", "OWN", "PER", "PUT", "RED", "SEE", "SET",
    "SHE", "THE", "TOO", "TOP", "TWO", "USE", "WAS", "WAY", "WHO", "WHY", "WIN",
    "YES", "YOU", "ATH", "ATL", "BTW", "CEO", "CFO", "COO", "DD", "EOD", "EPS",
    "ER", "EST", "ETF", "FDA", "FOMO", "FUD", "GDP", "HODL", "IMO", "IPO", "IRA",
    "IRS", "ITM", "IV", "LFG", "LMAO", "LOL", "OTC", "OTM", "PR", "PT", "RSI",
    "SEC", "TA", "TLDR", "TOS", "USA", "USD", "WSB", "YOLO", "YTD", "EV", "AI",
    "OK", "NSFW", "EDIT", "IMHO", "MOON", "BAGS", "CALLS", "PUTS", "SHARES",
    "HOLD", "SELL", "LONG", "GANG", "BUYS", "GAINS", "LOSS", "PUMP", "DUMP",
}

# $TICKER — 1 to 5 letters, optional .X share-class suffix.
_CASHTAG = re.compile(r"\$([A-Za-z]{1,5})(?:\.[A-Za-z])?\b")
# bare 1-5 capital letters as a standalone word.
_BARE = re.compile(r"\b([A-Z]{1,5})\b")


def extract_tickers(text: str, known_symbols: Set[str] | None = None) -> List[str]:
    """Return the list of distinct tickers found in ``text``.

    ``known_symbols`` should be the uppercase set of tradable symbols from the
    scan universe; when provided, bare-token matches are validated against it.
    """
    if not text:
        return []

    found: List[str] = []
    seen: Set[str] = set()

    def add(sym: str) -> None:
        sym = sym.upper()
        if sym not in seen:
            seen.add(sym)
            found.append(sym)

    for m in _CASHTAG.finditer(text):
        sym = m.group(1).upper()
        if sym not in STOPWORDS:
            add(sym)

    if known_symbols:
        for m in _BARE.finditer(text):
            sym = m.group(1)
            if sym in STOPWORDS:
                continue
            if sym in known_symbols:
                add(sym)

    return found


def extract_from_many(
    texts: Iterable[str], known_symbols: Set[str] | None = None
) -> List[str]:
    out: List[str] = []
    for t in texts:
        out.extend(extract_tickers(t, known_symbols))
    return out

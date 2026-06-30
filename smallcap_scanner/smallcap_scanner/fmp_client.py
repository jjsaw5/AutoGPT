"""Thin wrapper over the Financial Modeling Prep REST API.

Only the endpoints the scanner needs are implemented:
  * company screener -> defines the candidate universe
  * quote            -> enriches with 50/200d averages, 52w high/low, volume

Uses the current /stable endpoints; FMP retired the legacy /api/v3 endpoints
(including batch quote) in 2025, so quotes are fetched one symbol per request.

Docs: https://site.financialmodelingprep.com/developer/docs
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List

import requests

from .config import Config
from .models import StockCandidate

log = logging.getLogger(__name__)


class FMPError(RuntimeError):
    pass


class FMPClient:
    def __init__(self, config: Config, session: requests.Session | None = None):
        if not config.has_fmp:
            raise FMPError(
                "FMP_API_KEY is not set. Get a key at "
                "https://site.financialmodelingprep.com/developer/docs"
            )
        self.cfg = config
        self.session = session or requests.Session()

    def _get(self, path: str, params: Dict[str, object], retry_429: bool = True) -> object:
        params = {**params, "apikey": self.cfg.fmp_api_key}
        url = f"{self.cfg.fmp_base_url}/{path.lstrip('/')}"
        resp = self.session.get(url, params=params, timeout=30)
        if resp.status_code == 401:
            raise FMPError("FMP rejected the API key (401). Check FMP_API_KEY.")
        if resp.status_code == 403:
            raise FMPError(
                "FMP returned 403 — this endpoint likely needs a paid plan."
            )
        if resp.status_code == 429 and retry_429:
            log.warning("FMP rate limit hit, backing off 2s and retrying once")
            time.sleep(2)
            return self._get(path, params, retry_429=False)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("Error Message"):
            raise FMPError(str(data["Error Message"]))
        return data

    def screen(self) -> List[StockCandidate]:
        """Run the fundamental/price screen and return raw candidates."""
        t = self.cfg.thresholds
        params = {
            "priceMoreThan": t.price_min,
            "priceLowerThan": t.price_max,
            "marketCapMoreThan": t.market_cap_min,
            "marketCapLowerThan": t.market_cap_max,
            "volumeMoreThan": t.avg_volume_min,
            "isActivelyTrading": "true",
            "isEtf": "false",
            "isFund": "false",
            "exchange": ",".join(e.strip() for e in t.exchanges),
            "limit": 2000,
        }
        rows = self._get("company-screener", params)
        if not isinstance(rows, list):
            raise FMPError(f"Unexpected screener response: {type(rows)!r}")

        out: List[StockCandidate] = []
        for row in rows:
            try:
                out.append(
                    StockCandidate(
                        symbol=row["symbol"].upper(),
                        name=row.get("companyName", ""),
                        price=float(row.get("price") or 0),
                        market_cap=float(row.get("marketCap") or 0),
                        volume=float(row.get("volume") or 0),
                        avg_volume=float(row.get("volume") or 0),
                        exchange=row.get("exchangeShortName", ""),
                        sector=row.get("sector", ""),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                log.debug("skipping malformed screener row %r: %s", row, exc)
        log.info("FMP screener returned %d candidates", len(out))
        return out

    def enrich_quotes(self, candidates: List[StockCandidate]) -> None:
        """Populate 50/200d averages, 52w range and live volume in-place.

        /stable/quote only accepts one symbol per request on current plans, so
        this issues one call per candidate. To bound runtime on a broad screen,
        only the ``fmp_enrich_limit`` candidates with the smallest market cap
        are enriched (that's the part of the universe this tool cares about);
        the rest keep their screener-only data and simply score 0 on momentum.
        """
        ordered = sorted(candidates, key=lambda c: c.market_cap)
        limit = self.cfg.fmp_enrich_limit
        to_enrich, skipped = ordered[:limit], ordered[limit:]
        if skipped:
            log.warning(
                "FMP_ENRICH_LIMIT=%d reached — %d of %d candidates will not get "
                "momentum data (smallest-market-cap names were prioritized). "
                "Raise FMP_ENRICH_LIMIT or tighten MARKET_CAP_MAX/PRICE_MAX to "
                "cover the rest.",
                limit, len(skipped), len(candidates),
            )

        for i, c in enumerate(to_enrich):
            try:
                data = self._get("quote", {"symbol": c.symbol})
            except FMPError as exc:
                log.debug("quote enrichment failed for %s: %s", c.symbol, exc)
                continue
            if not isinstance(data, list) or not data:
                continue
            q = data[0]
            c.price = float(q.get("price") or c.price)
            c.volume = float(q.get("volume") or c.volume)
            c.year_high = _f(q.get("yearHigh"))
            c.year_low = _f(q.get("yearLow"))
            c.price_avg_50 = _f(q.get("priceAvg50"))
            c.price_avg_200 = _f(q.get("priceAvg200"))
            c.change_pct = _f(q.get("changePercentage"))
            if (i + 1) % 50 == 0:
                log.info("enriched %d/%d quotes", i + 1, len(to_enrich))


def _f(v: object):
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None

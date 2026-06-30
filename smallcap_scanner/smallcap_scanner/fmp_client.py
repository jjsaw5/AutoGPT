"""Thin wrapper over the Financial Modeling Prep REST API.

Only the endpoints the scanner needs are implemented:
  * stock screener  -> defines the candidate universe
  * batch quote     -> enriches with 50/200d averages, 52w high/low, volume

Docs: https://site.financialmodelingprep.com/developer/docs
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List

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

    def _get(self, path: str, params: Dict[str, object]) -> object:
        params = {**params, "apikey": self.cfg.fmp_api_key}
        url = f"{self.cfg.fmp_base_url}/{path.lstrip('/')}"
        resp = self.session.get(url, params=params, timeout=30)
        if resp.status_code == 401:
            raise FMPError("FMP rejected the API key (401). Check FMP_API_KEY.")
        if resp.status_code == 403:
            raise FMPError(
                "FMP returned 403 — this endpoint likely needs a paid plan."
            )
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
        rows = self._get("stock-screener", params)
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

        FMP's batch quote endpoint accepts comma-separated symbols. We chunk to
        keep URLs sane.
        """
        by_symbol = {c.symbol: c for c in candidates}
        for chunk in _chunks(list(by_symbol), 100):
            data = self._get(f"quote/{','.join(chunk)}", {})
            if not isinstance(data, list):
                continue
            for q in data:
                c = by_symbol.get(str(q.get("symbol", "")).upper())
                if not c:
                    continue
                c.price = float(q.get("price") or c.price)
                c.volume = float(q.get("volume") or c.volume)
                c.avg_volume = float(q.get("avgVolume") or c.avg_volume)
                c.year_high = _f(q.get("yearHigh"))
                c.year_low = _f(q.get("yearLow"))
                c.price_avg_50 = _f(q.get("priceAvg50"))
                c.price_avg_200 = _f(q.get("priceAvg200"))
                c.change_pct = _f(q.get("changesPercentage"))


def _f(v: object):
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _chunks(seq: List[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]

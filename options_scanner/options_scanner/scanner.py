"""Scanner orchestrator — wires the pipeline stages end to end (spec §1).

    [1 Universe] → enrich → [4 Thesis] → [4 Structure] → [2 Gate]
        → [3 Score] → [5 Rank/Decide] → [6 Readout] → [7 Log]

Execution mode is recommend_only: this class never places an order. It produces
a ranked readout and a candidate log; a human confirms every trade, and live
chain / buying-power / execution flow through the Robinhood MCP tools separately.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .clients import FMPClient, UnusualWhalesClient
from .config import Config, load_config
from .models import EvaluatedCandidate
from .pipeline import (
    append_scan,
    build_thesis,
    build_universe,
    enrich_candidate,
    evaluate_gates,
    rank_and_decide,
    render_readout,
    score_candidate,
    select_structure,
)
from .pipeline.chain import build_chain

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    scan_id: str
    timestamp: str
    evaluated: list[EvaluatedCandidate] = field(default_factory=list)
    readout: str = ""
    rows_logged: int = 0


class Scanner:
    def __init__(
        self,
        config: Config,
        *,
        fmp: FMPClient | None = None,
        uw: UnusualWhalesClient | None = None,
    ) -> None:
        self.config = config
        self.fmp = fmp
        self.uw = uw

    @classmethod
    def from_config(
        cls, config: Config | None = None, *, offline: bool = False
    ) -> "Scanner":
        """Build a scanner, wiring FMP/UW clients from credentials when present.

        ``offline=True`` (or missing keys) yields a scanner with no live clients —
        useful for tests and for running against pre-populated candidates.
        """
        config = config or load_config()
        data = config.data
        fmp = uw = None
        if not offline:
            ttl = float(data.get("cache_ttl_seconds", 300))
            timeout = float(data.get("request_timeout_seconds", 20))
            if config.credentials.has_fmp:
                fmp = FMPClient(
                    config.credentials.fmp_api_key,
                    base_url=data.get("fmp_base_url", "https://financialmodelingprep.com"),
                    timeout=timeout, cache_ttl=ttl,
                )
            else:
                logger.warning("No FMP_API_KEY — profile/quote signals degraded.")
            if config.credentials.has_uw:
                uw = UnusualWhalesClient(
                    config.credentials.uw_api_key,
                    base_url=data.get("uw_base_url", "https://api.unusualwhales.com"),
                    timeout=timeout, cache_ttl=ttl,
                )
            else:
                logger.warning("No UW_API_KEY — flow/vol edge signals degraded.")
        return cls(config, fmp=fmp, uw=uw)

    # --- main entry -----------------------------------------------------------
    def scan(
        self,
        *,
        tickers: list[str] | None = None,
        context: dict[str, Any] | None = None,
        log_path: str | None = None,
        now: datetime | None = None,
    ) -> ScanResult:
        now = now or datetime.now(timezone.utc)
        scan_id = now.strftime("scan_%Y%m%dT%H%M%SZ")
        timestamp = now.isoformat()

        # Fresh scan => drop caches so we never serve stale cross-scan data.
        if self.fmp:
            self.fmp.clear_cache()
        if self.uw:
            self.uw.clear_cache()

        candidates = self._universe(tickers)
        logger.info("Universe: %d candidates", len(candidates))

        evaluated: list[EvaluatedCandidate] = []
        for candidate in candidates:
            enrich_candidate(candidate, self.fmp, self.uw, self.config)
            thesis = build_thesis(candidate, self.config)
            chain = None
            if self.uw is not None:
                try:
                    chain = build_chain(
                        self.uw, candidate.ticker, thesis.horizon.value,
                        candidate.price, now=now,
                    )
                except Exception as exc:  # never let chain issues abort a scan
                    logger.warning("chain build failed for %s: %s", candidate.ticker, exc)
            structure = select_structure(candidate, thesis, self.config, chain=chain)
            gates = evaluate_gates(
                candidate, thesis, structure, self.config, context=context
            )
            score = score_candidate(candidate, thesis, structure, self.config)
            evaluated.append(
                EvaluatedCandidate(
                    candidate=candidate, thesis=thesis,
                    structure=structure, score=score, gates=gates,
                )
            )

        rank_and_decide(evaluated, self.config)
        readout = render_readout(evaluated, self.config, context=context)

        rows_logged = 0
        if log_path:
            rows_logged = append_scan(
                evaluated, scan_id=scan_id, timestamp=timestamp, log_path=log_path
            )

        return ScanResult(
            scan_id=scan_id, timestamp=timestamp,
            evaluated=evaluated, readout=readout, rows_logged=rows_logged,
        )

    def _universe(self, tickers: list[str] | None):
        if tickers:
            from .models import Candidate, Tier
            return [
                Candidate(ticker=t.upper(), tier=Tier.A, source_feeds=["manual"])
                for t in tickers
            ]
        return build_universe(self.config, self.uw)

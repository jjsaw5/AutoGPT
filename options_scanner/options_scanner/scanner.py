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
from .pipeline.logbook import candidate_to_row
from .market_context import build_market_regime
from .exits import build_exit_plan
from .history import HistoryStore, SqliteQueryDB, build_run_manifest

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    scan_id: str
    timestamp: str
    evaluated: list[EvaluatedCandidate] = field(default_factory=list)
    readout: str = ""
    rows_logged: int = 0
    shadows_recorded: int = 0
    history_rows: int = 0
    regime: Any = None


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
        journal_path: str | None = None,
        history_dir: str | None = None,
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

        # Market-wide regime — computed once per scan, shared across candidates.
        regime = None
        if self.config.market_context.get("enabled", True) and self.fmp is not None:
            regime = build_market_regime(self.fmp, now=now)

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
            exit_plan = build_exit_plan(structure, thesis)
            gate_ctx = {**(context or {}), "exit_plan": exit_plan}
            gates = evaluate_gates(
                candidate, thesis, structure, self.config, context=gate_ctx
            )
            score = score_candidate(candidate, thesis, structure, self.config)
            evaluated.append(
                EvaluatedCandidate(
                    candidate=candidate, thesis=thesis,
                    structure=structure, score=score, gates=gates,
                    exit_plan=exit_plan,
                )
            )

        rank_and_decide(evaluated, self.config, regime=regime)
        readout = render_readout(evaluated, self.config, context=context, regime=regime)

        rows_logged = 0
        if log_path:
            rows_logged = append_scan(
                evaluated, scan_id=scan_id, timestamp=timestamp, log_path=log_path
            )

        shadows_recorded = 0
        if journal_path:
            from .journal import Ledger, record_shadows
            ledger = Ledger.load(journal_path)
            shadows_recorded = record_shadows(
                ledger, evaluated, scan_id=scan_id, config=self.config, now=now
            )
            ledger.save()

        # Durable time-series history: append-only JSONL (committed to git) plus a
        # rebuildable SQLite mirror for queries. This is what lets us later ask
        # "how did SPY drift across runs, and was that GO on a real chain?".
        history_rows = 0
        if history_dir:
            rows = [
                candidate_to_row(ec, scan_id=scan_id, timestamp=timestamp)
                for ec in evaluated
            ]
            manifest = build_run_manifest(
                rows, scan_id=scan_id, timestamp=timestamp, regime=regime
            )
            store = HistoryStore(
                base_dir=history_dir,
                query_db=SqliteQueryDB(f"{history_dir}/scanner.sqlite"),
            )
            history_rows = store.record(rows, manifest=manifest)
            store.query_db.close()

            # Write-through to the hosted DB when configured. JSONL is already
            # persisted, so a Turso/network hiccup only costs this scan's remote
            # copy — never the scan itself; the next `history sync` catches up.
            creds = self.config.credentials
            if creds.has_turso:
                try:
                    from .history import TursoQueryDB
                    remote = TursoQueryDB.from_env(
                        creds.turso_database_url, creds.turso_auth_token
                    )
                    remote.apply_run(manifest)
                    remote.apply_candidates(rows)
                except Exception as exc:  # never abort a scan on remote-DB issues
                    logger.warning(
                        "Turso write-through failed (JSONL retains the scan): %s", exc
                    )

        return ScanResult(
            scan_id=scan_id, timestamp=timestamp,
            evaluated=evaluated, readout=readout, rows_logged=rows_logged,
            shadows_recorded=shadows_recorded, history_rows=history_rows,
            regime=regime,
        )

    def _universe(self, tickers: list[str] | None):
        if tickers:
            from .models import Candidate, Tier
            return [
                Candidate(ticker=t.upper(), tier=Tier.A, source_feeds=["manual"])
                for t in tickers
            ]
        return build_universe(self.config, self.uw)

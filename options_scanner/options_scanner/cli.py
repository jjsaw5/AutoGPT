"""Command-line entry point for the Options Opportunity Scanner.

    python -m options_scanner.cli scan --tickers AAPL,NVDA --log runs/scan.jsonl

Recommend-only: prints a ranked readout and (optionally) appends a candidate
log. Never places an order.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .scanner import Scanner


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="options_scanner",
        description="Options Opportunity Scanner — recommend-only decision support.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Run a scan and print the readout.")
    scan.add_argument("--config", default=None, help="Path to config.yaml")
    scan.add_argument(
        "--tickers", default=None,
        help="Comma-separated tickers to scan instead of the config universe.",
    )
    scan.add_argument("--log", default=None, help="Append candidate log to this JSONL path.")
    scan.add_argument(
        "--journal", default=None,
        help="Record GO / budget-blocked setups as shadow trades in this ledger (JSON).",
    )
    scan.add_argument(
        "--history", default=None,
        help="Durable run history dir (append-only JSONL + rebuildable SQLite). "
             "Commit this dir to keep a queryable cross-run time series.",
    )
    scan.add_argument(
        "--offline", action="store_true",
        help="Do not call live APIs (uses whatever signals are pre-populated).",
    )
    scan.add_argument("--open-risk", type=float, default=0.0, help="Current open risk ($).")
    scan.add_argument("--open-positions", type=int, default=0, help="Current open positions.")
    scan.add_argument("--zerodte-used", type=int, default=0, help="0DTE trades used this week.")
    scan.add_argument("-v", "--verbose", action="store_true")

    # journal subcommands
    jrnl = sub.add_parser("journal", help="Inspect / resolve the trade ledger.")
    jrnl.add_argument("action", choices=["report", "resolve", "annotate", "list"])
    jrnl.add_argument("--journal", required=True, help="Path to the ledger JSON.")
    jrnl.add_argument("--config", default=None)
    jrnl.add_argument("--force", action="store_true", help="resolve: ignore resolve_by date.")
    jrnl.add_argument("--key", default=None, help="annotate: setup_key to annotate.")
    jrnl.add_argument("--note", default=None, help="annotate: the note text.")
    jrnl.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.command == "scan":
        config = load_config(args.config)
        scanner = Scanner.from_config(config, offline=args.offline)
        tickers = (
            [t.strip() for t in args.tickers.split(",") if t.strip()]
            if args.tickers else None
        )
        context = {
            "open_risk": args.open_risk,
            "open_positions": args.open_positions,
            "zerodte_used": args.zerodte_used,
        }
        result = scanner.scan(
            tickers=tickers, context=context,
            log_path=args.log, journal_path=args.journal,
            history_dir=args.history,
        )
        print(result.readout)
        if args.log:
            print(f"\n[logged {result.rows_logged} candidate rows to {args.log}]")
        if args.journal:
            print(f"[recorded {result.shadows_recorded} new shadow trades in {args.journal}]")
        if args.history:
            print(f"[recorded {result.history_rows} rows to durable history at {args.history}]")
        return 0

    if args.command == "journal":
        return _journal_command(args)

    return 1


def _journal_command(args) -> int:
    from datetime import datetime, timezone
    from .journal import Ledger, annotate, resolve_open, uw_chain_provider
    from .calibration import report as calib_report

    ledger = Ledger.load(args.journal)
    now = datetime.now(timezone.utc)

    if args.action == "report":
        print(calib_report(ledger))
    elif args.action == "list":
        for e in ledger.entries.values():
            print(f"{e.status:6} {e.kind:6} {e.outcome:7} {e.ticker:6} {e.structure:16} "
                  f"comp={e.composite:<5} pop={e.pop_predicted:<5} pnl={e.pnl} key={e.setup_key}")
    elif args.action == "resolve":
        config = load_config(args.config)
        scanner = Scanner.from_config(config)
        if scanner.uw is None:
            print("Resolve needs a UW client (set UW_API_KEY).")
            return 1
        n = resolve_open(ledger, uw_chain_provider(scanner.uw), now=now, force=args.force)
        ledger.save()
        print(f"Resolved {n} entries.")
        print(calib_report(ledger))
    elif args.action == "annotate":
        if not args.key or not args.note:
            print("annotate requires --key and --note")
            return 1
        ok = annotate(ledger, args.key, args.note)
        ledger.save()
        print("annotated" if ok else "key not found")
    return 0


if __name__ == "__main__":
    sys.exit(main())

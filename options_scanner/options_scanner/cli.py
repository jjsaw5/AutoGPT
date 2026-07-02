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
        "--offline", action="store_true",
        help="Do not call live APIs (uses whatever signals are pre-populated).",
    )
    scan.add_argument("--open-risk", type=float, default=0.0, help="Current open risk ($).")
    scan.add_argument("--open-positions", type=int, default=0, help="Current open positions.")
    scan.add_argument("--zerodte-used", type=int, default=0, help="0DTE trades used this week.")
    scan.add_argument("-v", "--verbose", action="store_true")
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
        result = scanner.scan(tickers=tickers, context=context, log_path=args.log)
        print(result.readout)
        if args.log:
            print(f"\n[logged {result.rows_logged} candidate rows to {args.log}]")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())

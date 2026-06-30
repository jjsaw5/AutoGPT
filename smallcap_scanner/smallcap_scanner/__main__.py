"""Command-line entry point: ``python -m smallcap_scanner``."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import Config
from .pipeline import format_table, run_scan

BANNER = """\
============================================================
 Small-Cap Long-Call Scanner   (research tool — not advice)
============================================================
These are pre-screened *ideas*, ranked by a heuristic blend of
fundamentals, price momentum and Reddit attention. Reddit-driven
penny names are frequently pump-and-dumps: most go to zero. Read
the FLAGS column, do your own DD, and never risk more than you
can lose. This tool does not place trades.
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="smallcap_scanner",
        description="Scan for small-cap stocks with long-call (LEAPS) potential.",
    )
    p.add_argument("--mock", action="store_true",
                   help="Run on bundled offline sample data (no API keys needed).")
    p.add_argument("--require-social", action="store_true",
                   help="Only show names with at least one Reddit mention.")
    p.add_argument("--top", type=int, default=25, help="Max rows to show.")
    p.add_argument("--json", action="store_true",
                   help="Emit JSON instead of a table.")
    p.add_argument("--quiet", action="store_true", help="Suppress the banner.")
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    cfg = Config()
    if not args.mock and not cfg.has_fmp:
        print(
            "ERROR: FMP_API_KEY not set. Either export it (see .env.example) "
            "or run with --mock to try the tool on sample data.",
            file=sys.stderr,
        )
        return 2

    ranked = run_scan(
        cfg, mock=args.mock, require_social=args.require_social, top_n=args.top
    )

    if args.json:
        print(json.dumps([c.to_row() for c in ranked], indent=2))
        return 0

    if not args.quiet:
        print(BANNER)
    if not ranked:
        print("No candidates matched the current filters.")
        return 0
    print(format_table(ranked))
    print(
        f"\n{len(ranked)} candidates. Next step: validate option chains "
        "(LEAPS strikes, open interest, bid/ask) before considering any trade."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

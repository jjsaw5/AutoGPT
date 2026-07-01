"""Command-line entry point: ``python -m smallcap_scanner <stage> [options]``.

Three stages, each independently runnable and saveable:
  fundamentals  FMP-only scan -> the standalone prospects list
  social        ApeWisdom-only scan -> what's trending on the tracked subs
  combined      cross-reference a social list against FMP -> updated analysis
  all           runs all three in sequence in one process
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import Config
from .pipeline import (
    dump_social,
    format_social_table,
    format_table,
    load_social,
    scan_combined,
    scan_fundamentals,
    scan_social,
)

BANNER = """\
============================================================
 Small-Cap Long-Call Scanner   (research tool — not advice)
============================================================
These are pre-screened *ideas*, not recommendations. Reddit-driven
penny names are frequently pump-and-dumps: most go to zero. Read
the FLAGS column, do your own DD, and never risk more than you
can lose. This tool does not place trades.
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="smallcap_scanner",
        description="Scan for small-cap stocks with long-call (LEAPS) potential.",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--mock", action="store_true",
                         help="Run on bundled offline sample data (no API keys needed).")
    common.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    common.add_argument("--out", help="Also write the JSON result to this file.")
    common.add_argument("--quiet", action="store_true", help="Suppress the banner.")
    common.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")

    sub = p.add_subparsers(dest="stage", required=True)

    pf = sub.add_parser("fundamentals", parents=[common],
                         help="FMP-only scan: fundamentals + momentum, no social input.")
    pf.add_argument("--top", type=int, default=25, help="Max rows to show.")

    ps = sub.add_parser("social", parents=[common],
                         help="ApeWisdom-only scan: what's trending on the tracked subreddits.")
    ps.add_argument("--top", type=int, default=40, help="Max rows to show.")

    pc = sub.add_parser("combined", parents=[common],
                         help="Cross-reference a social list against FMP; full scoring.")
    pc.add_argument("--top", type=int, default=25, help="Max rows to show.")
    pc.add_argument("--from-file", help="Reuse a social list saved via `social --out FILE` "
                                         "instead of running a fresh social scan.")
    pc.add_argument("--social-limit", type=int, default=None,
                     help="How many top social tickers to cross-reference (default: "
                          "SOCIAL_FMP_LIMIT env, currently informs cfg default of 50).")
    pc.add_argument("--show-out-of-range", action="store_true",
                     help="Include tickers outside the configured price/market-cap band "
                          "(hidden by default) — e.g. mega-caps that are popular on Reddit "
                          "generally but don't fit the small-cap thesis.")

    pa = sub.add_parser("all", parents=[common],
                         help="Run fundamentals, social, and combined in sequence.")
    pa.add_argument("--top", type=int, default=25, help="Max rows to show per stage.")
    pa.add_argument("--social-limit", type=int, default=None,
                     help="How many top social tickers to cross-reference in the combined stage.")
    pa.add_argument("--show-out-of-range", action="store_true",
                     help="Include tickers outside the configured price/market-cap band "
                          "in the combined stage (hidden by default).")

    return p


def _check_fmp(cfg: Config, mock: bool) -> bool:
    if not mock and not cfg.has_fmp:
        print(
            "ERROR: FMP_API_KEY not set. Either export it (see .env.example) "
            "or run with --mock to try the tool on sample data.",
            file=sys.stderr,
        )
        return False
    return True


def _emit(rows, table_text: str, args, label: str) -> None:
    if args.json:
        payload = json.dumps(rows, indent=2)
        print(payload)
    else:
        if not args.quiet:
            print(BANNER)
        if not rows:
            print(f"No {label} to show.")
        else:
            print(table_text)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(rows, f, indent=2)
        print(f"\nSaved {len(rows)} {label} to {args.out}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    cfg = Config()

    if args.stage == "fundamentals":
        if not _check_fmp(cfg, args.mock):
            return 2
        ranked = scan_fundamentals(cfg, mock=args.mock, top_n=args.top)
        rows = [c.to_row() for c in ranked]
        _emit(rows, format_table(ranked), args, "fundamental prospects")
        return 0

    if args.stage == "social":
        signals = scan_social(cfg, mock=args.mock, top_n=args.top)
        rows = dump_social(signals)
        _emit(rows, format_social_table(signals), args, "trending tickers")
        return 0

    if args.stage == "combined":
        if not _check_fmp(cfg, args.mock):
            return 2
        social = None
        if args.from_file:
            with open(args.from_file) as f:
                social = load_social(json.load(f))
        ranked = scan_combined(
            cfg, social=social, mock=args.mock,
            social_limit=args.social_limit, top_n=args.top,
            show_out_of_range=args.show_out_of_range,
        )
        rows = [c.to_row() for c in ranked]
        _emit(rows, format_table(ranked), args, "combined analysis")
        return 0

    if args.stage == "all":
        if not _check_fmp(cfg, args.mock):
            return 2
        if not args.quiet:
            print(BANNER)

        print("=== STAGE 1: FMP fundamentals/momentum prospects ===")
        fund = scan_fundamentals(cfg, mock=args.mock, top_n=args.top)
        print(format_table(fund) if fund else "No prospects matched the current filters.")

        print("\n=== STAGE 2: trending on social media ===")
        # Fetch unranked-by-top_n so stage 3 (below) can pre-filter known
        # large-caps and still have a deep enough pool left to cross-reference
        # — capping here first would throw away everything past the display
        # limit before stage 3 ever sees it.
        social = scan_social(cfg, mock=args.mock, top_n=None)
        display_n = max(args.top, 40)
        print(format_social_table(social[:display_n]) if social else "No social mentions found.")

        print("\n=== STAGE 3: social tickers cross-referenced against FMP ===")
        combined = scan_combined(
            cfg, social=social, mock=args.mock,
            social_limit=args.social_limit, top_n=args.top,
            show_out_of_range=args.show_out_of_range,
        )
        print(format_table(combined) if combined else "No combined candidates.")

        if args.out:
            payload = {
                "fundamentals": [c.to_row() for c in fund],
                "social": dump_social(social[:display_n]),
                "combined": [c.to_row() for c in combined],
            }
            with open(args.out, "w") as f:
                json.dump(payload, f, indent=2)
            print(f"\nSaved all three lists to {args.out}", file=sys.stderr)
        return 0

    return 1  # unreachable: argparse enforces a valid subcommand


if __name__ == "__main__":
    raise SystemExit(main())

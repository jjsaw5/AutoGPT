"""Command-line entry: `python -m options_flow_screener "your prompt"`."""
from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .llm import filter_spec_from_prompt, trade_plan
from .screener import TickerSummary, aggregate, alert_premium, apply_filters
from .unusual_whales import UnusualWhalesClient


console = Console()


DEFAULT_PROMPT = (
    "Screen all institutional options flow from the last session. I only want "
    "mid-cap stocks between $1B and $10B market cap. Minimum $30K premium per order. "
    "IV rank above 80%. At least 70% of total flow has to be bullish. "
    "Volume/OI under 0.5. DTE between 15 and 60 days. Rank by bullish flow percent."
)


def _fmt_money(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.2f}M"
    if v >= 1e3:
        return f"${v/1e3:.1f}K"
    return f"${v:.0f}"


def _render_table(results: list[TickerSummary]) -> None:
    t = Table(title="Screen results", show_lines=False)
    for col in (
        "Ticker", "Sector", "Mkt Cap", "Bull $", "Bear $", "Bull %",
        "IV Rank", "Largest", "OI", "Vol/OI", "Alerts", "DTE",
    ):
        t.add_column(col)
    for r in results:
        t.add_row(
            r.ticker,
            (r.sector or "—")[:14],
            _fmt_money(r.market_cap),
            _fmt_money(r.bullish_premium),
            _fmt_money(r.bearish_premium),
            f"{r.bullish_flow_pct:.0f}%",
            f"{r.iv_rank:.0f}" if r.iv_rank is not None else "—",
            _fmt_money(r.largest_order),
            f"{r.open_interest:,}",
            f"{r.vol_oi:.2f}" if r.vol_oi is not None else "—",
            str(r.alert_count),
            str(r.largest_dte) if r.largest_dte is not None else "—",
        )
    console.print(t)


async def _run(prompt: str, plan_top: bool, model: str | None) -> int:
    console.print("[bold]Translating prompt into a screen spec via Claude…[/bold]")
    spec = filter_spec_from_prompt(prompt, model=model)
    console.print(f"[dim]Parsed spec:[/dim] {spec}")

    uw = UnusualWhalesClient.from_env()
    console.print("[bold]Pulling flow alerts from Unusual Whales…[/bold]")
    alerts = await uw.flow_alerts(
        min_premium=int(spec.premium_min_usd) if spec.premium_min_usd else None,
        min_dte=spec.dte_min,
        max_dte=spec.dte_max,
        max_vol_oi=spec.vol_oi_max,
        limit=1000,
    )
    if spec.premium_min_usd is not None:
        alerts = [a for a in alerts if alert_premium(a) >= spec.premium_min_usd]
    console.print(f"  fetched {len(alerts)} alerts after premium filter")

    summaries = aggregate(alerts)
    results = apply_filters(summaries, spec)

    if not results:
        console.print("[yellow]No tickers passed the filters today.[/yellow]")
        return 0

    _render_table(results)

    if plan_top:
        top = results[0]
        console.print(f"\n[bold]Fetching news + earnings for top pick {top.ticker}…[/bold]")
        news, earnings = await asyncio.gather(uw.news(top.ticker), uw.earnings(top.ticker))
        console.print("[bold]Asking Claude for a trade plan…[/bold]\n")
        plan = trade_plan(top, news, earnings, user_prompt=prompt, model=model)
        console.print(plan)
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(
        prog="options_flow_screener",
        description="AI-driven institutional options flow screener (Unusual Whales + Claude).",
    )
    p.add_argument(
        "prompt",
        nargs="?",
        default=DEFAULT_PROMPT,
        help="Plain-English screen request. Defaults to the canonical mid-cap screen.",
    )
    p.add_argument(
        "--plan",
        action="store_true",
        help="After screening, ask Claude for a trade plan on the top pick.",
    )
    p.add_argument("--model", default=None, help="Override Anthropic model.")
    args = p.parse_args(argv)
    try:
        return asyncio.run(_run(args.prompt, args.plan, args.model))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

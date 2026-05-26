"""Claude integration.

Two calls per run:
1. `filter_spec_from_prompt` — forces a tool call so Claude returns a structured FilterSpec.
2. `trade_plan` — plain-text completion that takes JSON context and writes the plan.
"""
from __future__ import annotations

import json
import os
from typing import Any

import anthropic

from .screener import FilterSpec, TickerSummary


DEFAULT_MODEL = "claude-sonnet-4-6"


SCREEN_TOOL = {
    "name": "run_screen",
    "description": (
        "Run an institutional options flow screen. Translate the user's plain-English "
        "request into these parameters. Only set fields the user explicitly mentioned; "
        "leave the rest unset so defaults apply. Always call this tool — do not write prose."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "market_cap_min_usd": {
                "type": "number",
                "description": "Min underlying market cap in USD. $1B = 1_000_000_000.",
            },
            "market_cap_max_usd": {
                "type": "number",
                "description": "Max underlying market cap in USD.",
            },
            "premium_min_usd": {
                "type": "number",
                "description": "Min premium per individual alert/order in USD.",
            },
            "iv_rank_min": {
                "type": "number",
                "description": "Min IV rank, 0-100.",
            },
            "bullish_flow_pct_min": {
                "type": "number",
                "description": "Min bullish premium as percent of total flow for the ticker, 0-100.",
            },
            "vol_oi_max": {
                "type": "number",
                "description": "Max volume / open interest ratio (e.g. 0.5).",
            },
            "dte_min": {"type": "integer", "description": "Min days to expiry."},
            "dte_max": {"type": "integer", "description": "Max days to expiry."},
            "side": {
                "type": "string",
                "enum": ["bullish", "bearish", "any"],
                "description": "Direction filter. Defaults to bullish.",
            },
            "rank_by": {
                "type": "string",
                "enum": [
                    "bullish_flow_pct",
                    "open_interest",
                    "premium",
                    "iv_rank",
                    "largest_order",
                ],
                "description": "How to sort the result list.",
            },
            "rank_direction": {
                "type": "string",
                "enum": ["asc", "desc"],
                "description": "Sort direction. Defaults to desc.",
            },
            "limit": {
                "type": "integer",
                "description": "Max candidates to return. Defaults to 10.",
            },
        },
    },
}


def _client(model: str | None) -> tuple[anthropic.Anthropic, str]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to .env or your shell.")
    return anthropic.Anthropic(), (model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL))


def filter_spec_from_prompt(prompt: str, model: str | None = None) -> FilterSpec:
    client, model_id = _client(model)
    msg = client.messages.create(
        model=model_id,
        max_tokens=1024,
        tools=[SCREEN_TOOL],
        tool_choice={"type": "tool", "name": "run_screen"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in msg.content:
        if block.type == "tool_use" and block.name == "run_screen":
            return _filter_spec_from_args(block.input)
    raise RuntimeError("Claude did not return a run_screen tool call.")


def _filter_spec_from_args(args: dict[str, Any]) -> FilterSpec:
    return FilterSpec(
        market_cap_min_usd=args.get("market_cap_min_usd"),
        market_cap_max_usd=args.get("market_cap_max_usd"),
        premium_min_usd=args.get("premium_min_usd"),
        iv_rank_min=args.get("iv_rank_min"),
        bullish_flow_pct_min=args.get("bullish_flow_pct_min"),
        vol_oi_max=args.get("vol_oi_max"),
        dte_min=args.get("dte_min"),
        dte_max=args.get("dte_max"),
        side=args.get("side", "bullish"),
        rank_by=args.get("rank_by", "bullish_flow_pct"),
        rank_direction=args.get("rank_direction", "desc"),
        limit=args.get("limit", 10),
    )


def trade_plan(
    candidate: TickerSummary,
    news: list[dict[str, Any]],
    earnings: list[dict[str, Any]],
    user_prompt: str,
    model: str | None = None,
) -> str:
    client, model_id = _client(model)
    context = {
        "ticker": candidate.ticker,
        "sector": candidate.sector,
        "market_cap": candidate.market_cap,
        "iv_rank": candidate.iv_rank,
        "bullish_flow_pct": candidate.bullish_flow_pct,
        "total_premium": candidate.total_premium,
        "largest_order_premium": candidate.largest_order,
        "open_interest": candidate.open_interest,
        "volume": candidate.volume,
        "vol_oi": candidate.vol_oi,
        "alert_count": candidate.alert_count,
        "dte_of_largest_order": candidate.largest_dte,
        "recent_news": [
            {k: n.get(k) for k in ("headline", "summary", "published_at", "source")}
            for n in news[:10]
        ],
        "earnings_calendar": earnings[:5],
    }
    prompt = (
        f"You're helping plan an equity (not options) trade based on institutional "
        f"options flow. The user's original ask:\n\n{user_prompt}\n\n"
        f"Candidate and supporting context as JSON:\n```json\n"
        f"{json.dumps(context, indent=2, default=str)}\n```\n\n"
        f"Produce a concise trade plan with:\n"
        f"1. Catalyst/news check — flag any binary events within 7 days; recommend skipping if found.\n"
        f"2. Entry, take-profit, and time-based exit rules. Default to: entry at next open, "
        f"TP at +7%, max hold 5 trading days.\n"
        f"3. One-line rationale tied to the flow signal.\n\n"
        f"Be specific. Don't hedge. This is research, not investment advice."
    )
    resp = client.messages.create(
        model=model_id,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")

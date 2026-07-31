"""Broker-feed adapters.

The Robinhood connection in this workspace is an MCP server, which means it
is callable by the agent but not by this process. Rather than pretend
otherwise, these functions parse the MCP tool payloads into the same `Bar`
and `Quote` types the FMP client produces.

The flow is: the agent (or a cron job) calls the MCP tool, writes the JSON
to a file, and the engine reads it. `odte.cli` accepts that file via
`--broker-data`. If you later add direct API credentials, swap in a client
that emits the same types and nothing downstream changes.

Robinhood specifics that matter here:
  * `get_equity_historicals` with bounds='extended' tags each bar with a
    `session` of "pre" / "reg" / "post" -- that tag is what makes premarket
    high/low computable.
  * `begins_at` is UTC and left-edge labelled.
  * Option chains expose `sellout_time_to_expiration` (1800s for SPY),
    i.e. the broker force-closes 0DTE positions 30 minutes before expiry.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .config import MARKET_TZ
from .models import Bar, OptionContract, Quote, Session

_SESSION_MAP = {
    "pre": Session.PRE,
    "reg": Session.REGULAR,
    "post": Session.POST,
}


def _unwrap(payload: dict, *keys: str):
    """MCP responses nest the useful part under `data`."""
    node = payload.get("data", payload)
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def parse_historicals(payload: dict) -> dict[str, list[Bar]]:
    """Parse `mcp__Robinhood__get_equity_historicals` output."""
    results = _unwrap(payload, "results") or []
    out: dict[str, list[Bar]] = {}
    for result in results:
        symbol = result.get("symbol")
        if not symbol:
            continue
        bars = [
            Bar(
                ts=_parse_utc(raw["begins_at"]),
                open=float(raw["open_price"]),
                high=float(raw["high_price"]),
                low=float(raw["low_price"]),
                close=float(raw["close_price"]),
                volume=float(raw.get("volume") or 0),
                session=_SESSION_MAP.get(raw.get("session", "reg"), Session.REGULAR),
            )
            for raw in result.get("bars", [])
            if not raw.get("interpolated")
        ]
        out[symbol] = sorted(bars, key=lambda b: b.ts)
    return out


def parse_quotes(payload: dict) -> dict[str, Quote]:
    """Parse `mcp__Robinhood__get_equity_quotes` output."""
    quotes = _unwrap(payload, "quotes") or []
    closes = {c.get("symbol"): c for c in (_unwrap(payload, "closes") or [])}
    out: dict[str, Quote] = {}
    for raw in quotes:
        symbol = raw.get("symbol")
        if not symbol:
            continue
        price = _first_float(
            raw, "last_extended_hours_trade_price", "last_trade_price", "price"
        )
        prev_close = _first_float(raw, "previous_close", "adjusted_previous_close")
        if prev_close is None:
            prev_close = _first_float(closes.get(symbol, {}), "close", "price")
        if price is None:
            continue
        prev_close = prev_close or price
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0.0
        out[symbol] = Quote(
            symbol=symbol,
            price=price,
            prev_close=prev_close,
            change_pct=change_pct,
        )
    return out


def parse_option_quotes(
    payload: dict,
    instruments: dict[str, dict] | None = None,
) -> list[OptionContract]:
    """Parse `mcp__Robinhood__get_option_quotes`, enriched with instrument metadata.

    `instruments` maps instrument UUID -> the record from
    `get_option_instruments` (strike, expiration, type), because the quote
    payload alone does not carry them.
    """
    instruments = instruments or {}
    rows = _unwrap(payload, "quotes") or []
    contracts: list[OptionContract] = []
    for raw in rows:
        instrument_id = raw.get("instrument_id") or raw.get("id")
        meta = instruments.get(instrument_id, {})
        bid = _first_float(raw, "bid_price") or 0.0
        ask = _first_float(raw, "ask_price") or 0.0
        contracts.append(
            OptionContract(
                symbol=meta.get("chain_symbol", ""),
                expiration=meta.get("expiration_date", ""),
                strike=float(meta.get("strike_price") or 0),
                option_type=(meta.get("type") or "").lower(),
                bid=bid,
                ask=ask,
                delta=_first_float(raw, "delta"),
                open_interest=int(float(raw.get("open_interest") or 0)),
                volume=int(float(raw.get("volume") or 0)),
                instrument_id=instrument_id,
            )
        )
    return contracts


def _parse_utc(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(MARKET_TZ)


def _first_float(row: dict, *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None

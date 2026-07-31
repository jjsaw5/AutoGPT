---
name: 0dte
description: Run the gated 0DTE SPY/QQQ process — pull premarket levels and quotes from Robinhood, score the tech regime from FMP, and produce a signal with a sized trade plan. TRIGGER when the user asks for a 0DTE read, a SPY/QQQ intraday signal, "what's the tape saying", or to check the 0DTE setup.
user-invocable: true
args: "[SPY|QQQ|both] — defaults to both."
metadata:
  author: jjsaw5
  version: "1.0.0"
---

# 0DTE SPY/QQQ signal run

Orchestrates `tools/0dte`. The engine is deterministic and lives in Python;
this skill's only job is to fetch the data the engine cannot reach itself
(Robinhood is an MCP server, not a Python-callable API) and to present the
result.

## Hard rules

1. **Never place an order without explicit, in-the-moment user
   confirmation.** Present the trade card and stop. `place_option_order` is
   real money. A prior "yes" on an earlier signal does not carry to a new
   one.
2. **Never override a gate.** If the engine says NO_TRADE, report NO_TRADE.
   Do not hand-wave a "close enough" setup — the gates existing and being
   respected is the entire point.
3. **Do not invent numbers.** Every price in your output comes from a tool
   result or the engine. If data is missing, say so.

## Steps

### 1. Establish the clock

Get the current time in ET. If the market is closed, say so and offer the
regime-only read (`python -m odte.cli regime`) — it still works, it just
describes the last session.

### 2. Pull premarket + intraday bars

```
mcp__Robinhood__get_equity_historicals
  symbols:    ["SPY", "QQQ"]
  start_time: <session date>T08:00:00Z
  interval:   5minute
  bounds:     extended
```

`bounds: extended` is required — it is what tags bars `pre` and makes
premarket high/low computable. FMP cannot supply this.

Write the raw JSON payload to `/tmp/odte_broker.json` verbatim. Do not
reformat or summarise it; `odte.brokers.parse_historicals` expects the
original shape.

### 3. Pull the live quote

```
mcp__Robinhood__get_equity_quotes  symbols: ["SPY", "QQQ"]
```

Merge this into the same JSON file under `data.quotes` if the historicals
payload lacks it, or pass it as a second file — the parser reads `quotes`
from whichever payload carries it.

### 4. Run the engine

```bash
cd tools/0dte
python -m odte.cli signal --symbol SPY --broker-data /tmp/odte_broker.json --use-uw
python -m odte.cli signal --symbol QQQ --broker-data /tmp/odte_broker.json --use-uw
```

Drop `--use-uw` if `UW_API_KEY` is not exported; it no-ops safely either
way. When it is on, report the `flow` line alongside the regime — a strong
sector tide with faded ticker flow is worth saying out loud rather than
letting it silently inflate conviction.

Add `--record` whenever the Turso credentials are set. It persists the
evaluation (no-trades included) and makes the risk-budget gate read today's
actual fills instead of trusting a flag. If the database is unreachable the
signal still prints — never treat a persistence warning as a failed run.

After a fill, record it so the gate and the report stay honest:

```bash
python -m odte.cli log-entry --symbol SPY --direction 1 --quantity 4 \
    --premium 2.00 --strike 742 --option-type call --conviction 90
python -m odte.cli log-exit --trade-id <id> --premium 2.60 --reason target
```

Add `--trades-taken N --losses N` if the user has already traded today; the
risk-budget gate depends on it. Ask if you don't know and it's after 10:00.

### 5. If — and only if — a signal fires

Pull the 0DTE chain and pick the contract with the engine, not by eye:

1. `mcp__Robinhood__get_option_chains` with `underlying_symbol` — confirm
   today's date is in `expiration_dates`. Note `sellout_time_to_expiration`
   (the broker auto-closes 0DTE that many seconds before expiry).
2. `mcp__Robinhood__get_option_instruments` for that chain, today's expiry,
   `type` matching the signal, strikes within ~1.5% of spot.
3. `mcp__Robinhood__get_option_quotes` for those instrument IDs.
4. Feed both through `odte.brokers.parse_option_quotes`, then
   `odte.contract.select_contract` and `odte.contract.size_position`.

Never skip the filters. A 0.40-delta contract with a 12% spread hands back a
third of the profit target on the round trip.

### 6. Present and stop

Show: decision, conviction, every gate line, the levels, the chosen
contract, the size, and the exits (+30% / −25% / 25-minute time stop / flat
by 15:30). Then stop and wait.

If the user confirms, use `mcp__Robinhood__review_option_order` before
`place_option_order`, and report back exactly what filled.

## Reporting a no-trade

State which gate blocked and why, in one line. A blocked day is a working
day — most days should be no-trade, and "neutral tech" in particular is a
result, not a failure to find something.

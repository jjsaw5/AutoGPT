# Validating the LEAPS call play with Robinhood (MCP)

The scanner ranks **underlying stocks**. The example trade (`SLS $1.5 Call,
1/15/27`) is a **long-dated call (LEAPS)** on the underlying. This step turns a
shortlisted ticker into an actual options idea — and, just as importantly,
*disqualifies* tickers whose options are untradeable.

This is best done interactively with Claude when the **Robinhood MCP** server is
connected, because FMP's free tier does not provide full option chains and many
micro-caps have no listed options at all.

## Why this step matters

A stock can be a perfect scanner hit and still be a terrible options play:

- **No options listed.** Lots of sub-$2 names simply have no chain.
- **No LEAPS.** Some only list near-dated weeklies — useless for a 1-year thesis.
- **No open interest.** A strike with 0–5 contracts of OI means you may not be
  able to exit.
- **Wide bid/ask.** A $0.40 / $0.95 market means you lose ~40% instantly on the
  round trip. The example's tight, liquid `$14.20` quote is the opposite case.

## The flow (Robinhood MCP tools)

For each shortlisted `SYMBOL`:

1. **Confirm it's optionable & get the chain**
   `get_option_chains(underlying_symbol="SYMBOL")` → note the available
   `expiration_dates`. If none, drop the ticker.

2. **Pick a LEAPS expiration** 9–18+ months out (the example used ~24 months).

3. **List low-strike calls for that expiration**
   `get_option_instruments(chain_symbol="SYMBOL",
   expiration_dates="YYYY-MM-DD", type="call")` → collect the contract
   `id`s for strikes at/below the current price (for leverage) and modestly
   above (for the "10x" upside).

4. **Quote the contracts**
   `get_option_quotes(instrument_ids=[...])` → check **open interest**, the
   **bid/ask spread**, and the implied **delta**. Reject anything with trivial OI
   or a spread wider than ~15–20% of the mid.

5. **Sanity-check the underlying** with `get_equity_fundamentals(["SYMBOL"])`
   (float, short interest, 52-week range) and `get_earnings_results("SYMBOL")`
   for upcoming catalysts/risk.

6. (Optional) Add survivors to a watchlist with `add_option_to_watchlist(...)`.

## A prompt you can hand to Claude

> Using the Robinhood MCP tools, for each of these tickers
> `[SLS, GRND, ...]`: confirm options exist, find a call expiration ~12–18
> months out, list call strikes from roughly 50% below to 50% above the current
> price, quote them, and tell me which have real open interest and a bid/ask
> spread under ~15% of mid. Flag any ticker with no chain or no LEAPS. Do **not**
> place any orders — just report.

## Server-side screening shortcut

Robinhood also exposes a saved-scanner API (`create_scan` / `run_scan`) with
filters like `FILTER_TYPE_VOLUME`, `FILTER_TYPE_RSI`, and `% change`, plus
presets (`DAILY_GAINERS`, `HIGH_OPTIONS_VOLUME_IV`). That's a useful *second*,
independent universe to cross-reference against this scanner's FMP-based one —
names that show up in both are higher-conviction.

## Guardrail

None of this is a recommendation. Validation tells you whether a trade is
*executable*, not whether it's *wise*. Position-size for total loss.

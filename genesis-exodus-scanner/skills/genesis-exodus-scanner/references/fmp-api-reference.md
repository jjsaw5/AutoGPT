# FMP API Reference — Endpoint Catalog

`scripts/fmp.py` wraps Financial Modeling Prep's "stable" API surface
(`https://financialmodelingprep.com/stable/...`). This file maps each CLI subcommand to the
endpoint(s) it calls, so you can verify/adjust paths against your own plan's current docs if FMP
renames or relocates something (this happens periodically — treat this table as a starting point,
not a permanent contract).

| `fmp.py` subcommand      | Endpoint(s) called                                             | Notes |
|--------------------------|-----------------------------------------------------------------|-------|
| `regime`                 | `historical-price-eod/full` (SPY, QQQ, IWM), `quote` (`^VIX`)   | SMA50/200 computed locally from closes |
| `screener [...]`         | `company-screener`                                              | Forces `isEtf=false`, `isFund=false`, `isActivelyTrading=true` |
| `movers`                 | `biggest-gainers`, `biggest-losers`, `most-actives`             | |
| `indicators SYM`         | `historical-price-eod/full`, `profile`                          | SMA/ATR/52wk/breakout/RS all computed locally |
| `earnings SYM`           | `earnings`                                                       | Filters to the next upcoming date, flags the ~5-trading-day guard |
| `earnings-multi SYM...`  | `earnings` (per symbol)                                          | Same as above, batched |
| `news SYM...`            | `news/stock`                                                     | Advisory only |
| `rs SYM`                 | `historical-price-eod/full` (symbol + SPY)                       | Blended return-vs-SPY across 21/63/126/252d windows |
| `correlation SYM...`     | `historical-price-eod/full` (per symbol)                         | Pearson correlation of daily returns, computed locally |
| `breadth`                | `historical-price-eod/full` (11 SPDR sector ETFs)                | % of sector ETFs above their own 50-DMA |
| `rotation SYM...`        | `historical-price-eod/full` (per symbol)                         | Compares today's 21d return to the prior snapshot in `state/rs_ranks.json` |
| `pricechange SYM...`     | `stock-price-change`                                             | |
| `scores SYM`             | `scores`                                                         | FMP composite quality/scores |
| `float SYM`              | `shares-float`                                                   | |
| `insider SYM`            | `insider-trading/latest`                                        | |
| `grades SYM`             | `grades`                                                         | Analyst grades |
| `sectors`                | `sector-performance-snapshot`                                    | |

## Plan requirements

The screener, full historical price series, and several of the advisory sensors (news, grades,
insider trading, scores, shares-float, sector snapshot) require a paid Premium/Stable FMP plan.
The free tier will 403/limit on most of these — if you see auth or rate-limit errors, check your
plan tier before assuming the code is wrong.

## Caching

Every `_get()` call in `fmp.py` caches its raw JSON response under `state/cache/`, keyed by
endpoint + params + the current UTC date, so re-running the same query within a day doesn't burn
extra API calls. Delete a cache file (or the whole `state/cache/` directory) to force a fresh
pull; cache entries roll over automatically at UTC midnight.

## Key handling

`fmp.py` reads `FMP_API_KEY` from the process environment first, falling back to
`state/fmp.env` (format: `FMP_API_KEY=<key>`, one line). Prefer the environment variable in any
context where `state/fmp.env` might end up readable by something other than you (shared machines,
CI, etc.) — either way, `state/fmp.env` is `.gitignore`'d and the key is never printed by any
command.

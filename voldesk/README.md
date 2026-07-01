# Vol Desk

A pure-Python, deterministic decision-rule engine for the "Vol Desk" GEX
(gamma exposure) / dealer-positioning mechanical options swing-trading
strategy.

This package does **not** fetch market data, connect to any brokerage, or
place trades. It takes structured data you provide (a CSV export of a
vendor's nightly "gamma screen," plus plain Python/CLI values for live
price and candle data) and returns classifications and recommendations. A
human, working in a *separate* Claude Code session that has the Robinhood
MCP tools connected, is responsible for reviewing that output and manually
executing any trades.

## Important disclaimers -- read this first

- **This implements a strategy from an external, unverified source.** The
  rules encoded here were provided by the user and have not been
  independently validated by Anthropic or verified against real market
  outcomes by this codebase.
- **The claimed "100% win rate" for this strategy is based on a two-week
  sample.** A two-week sample is not statistically meaningful. Past
  performance, especially over such a short window, is not indicative of
  future results.
- **Nothing in this package is investment advice.** It is a mechanical
  rule-evaluation tool, not a recommendation to buy or sell any security.
- **Options trading carries substantial risk of loss, including total loss
  of premium paid.** Swing trading short-dated options can lose 100% of
  the position rapidly.
- **You are solely responsible for any trades you place.** This tool does
  not place orders, does not manage risk on your behalf beyond generating
  suggested stop/target levels, and does not guarantee the correctness of
  any classification. Always apply your own judgment.

## What this package does NOT do

- No calculation of the Vol Desk *proprietary* levels (pTrans, nTrans,
  COTMP, COTMC, the 11-point "grade", "db_change") from raw options chain
  data -- no published formula for these exists anywhere in this codebase.
  Bring your own vendor export (the gamma screen CSV) for those.
- Standard, well-defined GEX/DEX/VEX/CEX math *can* be computed from a raw
  options chain via `voldesk fetch` (see "Using FMP as a data source"
  below), as an alternative to a manual CSV export for those specific
  fields -- but this only covers the fields with a known, standard formula.
- Live market data fetching is limited to what `voldesk fetch --provider
  fmp` supports (an options chain + a quote for spot price); no candles or
  historicals.
- No order placement of any kind.
- No autonomous or scheduled execution. Every decision point in the
  intended workflow requires a human to run a command and read the output.

## Installation

```bash
cd voldesk
poetry install
# or, without poetry:
pip install -e .
```

Run the test suite:

```bash
cd voldesk
pytest
```

## Gamma screen CSV schema

`voldesk scan` (and `voldesk.ingest.load_gamma_screen`) reads a CSV with
one row per symbol. Column names are matched exactly (case-sensitive).

### Required columns

| Column       | Type  | Meaning                                              |
|--------------|-------|-------------------------------------------------------|
| `symbol`     | str   | Ticker symbol                                          |
| `spot`       | float | Current/last spot price                                |
| `db`         | float | Dealer delta balance (typically 0-1)                   |
| `db_change`  | float | Change in `db` from the prior session                  |
| `grade`      | int   | Setup grade, 0-11                                       |
| `p_trans`    | float | pTrans level (the break/trigger level)                  |
| `n_trans`    | float | nTrans level (the downside stop-reference level)        |
| `plus_gex`   | float | +GEX level -- the T1 profit target                     |
| `cotmp`      | float | Center Of Put Mass -- used for the cushion filter        |

### Optional columns (default if omitted)

| Column                  | Type          | Default | Meaning                                                              |
|--------------------------|---------------|---------|------------------------------------------------------------------------|
| `grade_11_deep`          | bool          | `False` | Whether this is a "Grade 11 DEEP" name (relaxes some thresholds)       |
| `db_prior_2_sessions`    | float or None | `None`  | `db` value two sessions ago, used to detect a sustained peg at 1.00     |
| `minervini_score`        | float or None | `None`  | Optional Minervini trend-template score                                 |
| `oi_depth`                | float or None | `None`  | Optional open-interest depth metric                                     |
| `zero_gex`                | float or None | `None`  | Optional zero-gamma level                                               |
| `plus_gex_next`           | float or None | `None`  | Optional secondary +GEX level                                          |
| `cotmc`                   | float or None | `None`  | Center Of Call Mass -- optional T2 target candidate                     |
| `spike_crash_pattern`     | bool          | `False` | Vendor-flagged: True means the +GEX target is a prior spike high with institutional selling already observed there -- a hard block |

Boolean columns accept (case-insensitively): `true`/`false`, `1`/`0`,
`yes`/`no`.

### Example row

```csv
symbol,spot,db,db_change,grade,p_trans,n_trans,plus_gex,cotmp,grade_11_deep,db_prior_2_sessions,spike_crash_pattern
AAPL,101.25,0.82,0.60,10,100.00,90.50,112.00,98.10,false,,false
```

## CLI usage

Run as `python -m voldesk <command>` or, if installed via poetry/pip, as
`voldesk <command>`.

### `scan` -- classify every name in a gamma screen export

```bash
voldesk scan gamma_screen_2026-06-30.csv
```

Prints every symbol grouped under `CONFIRMED`, `PENDING`, or `BLOCKED`,
with the specific filter reasons shown for blocked names.

### `regime` -- evaluate the day's macro gates

```bash
voldesk regime --spy 0.8 --qqq 0.3 --bull 22 --bear 4 \
  --vix-delta -1.5 --hyg-bearish --basket-bullish-or-bull-bear-confirms
```

- `--spy` / `--qqq`: today's percent change for SPY / QQQ.
- `--bull` / `--bear`: breadth counts (e.g. bullish vs bearish names on your
  scan).
- `--vix-delta`: VIX dealer delta balance for the day.
- `--hyg-bearish`: pass this flag if HYG (high-yield credit) is acting
  bearish today.
- `--basket-bullish-or-bull-bear-confirms`: pass this flag if the equity
  basket or bull/bear breadth is otherwise confirming bullish -- used only
  to detect an HYG divergence warning.

### `position open` -- record a new position in the ledger

```bash
voldesk position open AAPL --entry-price 101.25 --entry-date 2026-06-30 \
  --p-trans 100.00 --n-trans 90.50 --t1 112.00 --t2 120.00 \
  --ledger ~/voldesk-ledger.json
```

### `position check` -- get stop/target recommendations

```bash
voldesk position check AAPL --price 105.00 --date 2026-07-01 \
  --ledger ~/voldesk-ledger.json
# add --closed-below-ntrans if yesterday's close was below nTrans
```

### `position list` -- list all open positions

```bash
voldesk position list --ledger ~/voldesk-ledger.json
```

## The intended human-in-the-loop workflow

This tool is one half of a two-session workflow. The other half is a
separate Claude Code session with the Robinhood MCP server connected,
which can see live quotes and place orders under your direct supervision.

1. **Each evening**, export/save the vendor's gamma screen to a CSV file
   and run `voldesk scan <file.csv>` to get `CONFIRMED` / `PENDING` /
   `BLOCKED` classifications for every name.
2. **Each evening (or before the next session)**, run `voldesk regime`
   with that day's SPY/QQQ change, breadth counts, and VIX dealer delta to
   check whether the macro gates allow mechanical Track 1 trading, and
   whether the "B continuation" gate (all 3 gates) is open.
3. **At market open**, in a *separate* Claude Code session with the
   Robinhood MCP server connected, ask Claude to pull the first 5-minute
   candle close (via Robinhood quote/historicals-style MCP tools) for your
   `CONFIRMED` / `PENDING` names. Conceptually, that close price is what
   you pass into this package's `confirm_entry_trigger(evaluation,
   five_min_candle_close, p_trans)` function -- this repo does not call
   MCP tools itself, it only defines the rule. Never pass a pre-market
   price into that function; it must be a real 5-minute candle close.
4. **Before placing any order**, in that Robinhood-MCP session, use the
   `review_option_order`-style tool to see the quote, fees, and any alerts,
   and get your own explicit confirmation before calling
   `place_option_order`. Never let any agent place unsupervised or
   autonomous orders -- you are the one deciding to click submit.
5. **Each day you hold a position**, log the day's closing price into the
   ledger (`update_daily_close` / re-run `position open` state via the
   ledger APIs, or extend the CLI in your own workflow scripts) and run
   `voldesk position check` to get the stop/target recommendation for that
   day. Act on Stop 1 (close below nTrans) and Stop 2 (hard drawdown)
   mechanically and promptly. Use your own judgment only at the T1 target,
   per the strategy's own rule: either bank the gain, or lock your stop to
   entry before riding toward T2 -- never chase T2 with an unprotected
   stop.

## Using FMP as a data source

`voldesk fetch` pulls a raw options chain from the [Financial Modeling
Prep](https://financialmodelingprep.com/) (FMP) API and computes the
*standard, well-defined* GEX/dealer-positioning metrics from it, as an
alternative to a manual gamma-screen CSV export for those specific fields.

### What FMP can and cannot supply

FMP's options-chain endpoint gives you raw chain data: strikes,
expirations, call/put, open interest, volume, and implied volatility. It
does **not** give you:

- **Greeks.** FMP does not return delta/gamma/vanna/charm. `voldesk`
  computes them itself via textbook European Black-Scholes
  (`voldesk/greeks.py`). US equity/index options are American-style
  (early exercise allowed), so this is an *approximation* -- it is most
  accurate for short-dated, near-the-money contracts, and least accurate
  for deep ITM options (especially deep ITM puts on dividend payers, where
  early-exercise value is not modeled at all).
- **GEX/dealer-positioning derived levels.** Net GEX, GEX ratio, vGEX,
  zero-gamma strike, OI walls, and net DEX/VEX/CEX are all computed here
  (`voldesk/gex.py`) from the greeks above -- these are standard, publicly
  documented formulas (see the docstrings in `voldesk/greeks.py` and
  `voldesk/gex.py` for the exact math and edge-case handling).
- **The Vol Desk proprietary levels.** pTrans, nTrans, COTMP, COTMC, the
  11-point "grade", and "db_change" remain unavailable from FMP -- or from
  any other source right now -- because no published formula for them
  exists anywhere in this codebase. `voldesk fetch` prints them explicitly
  as `NOT YET DEFINED`. As a consequence, `voldesk scan` / the entry
  grading filters (`grading.py`) and the exit/stop framework (`exits.py`)
  cannot run end-to-end on FMP-sourced data alone until those levels are
  defined from the vendor's actual methodology -- they still require the
  gamma-screen CSV export.

### Schema caveat -- read before trusting the numbers

**FMP's exact options-chain response field names were not verified
against live API docs while building this** (the docs site blocked
automated fetching during development). `voldesk/voldesk/sources/fmp.py`
resolves each logical field (strike, option type, open interest, volume,
implied volatility, expiration) against a short list of plausible
alias names (e.g. `strike`/`strikePrice`, `openInterest`/`open_interest`)
and raises a clear `ValueError` if none of them match -- it will never
silently default a missing field to 0. Before trusting any numbers from
`voldesk fetch`, call your FMP plan's options-chain endpoint directly,
compare the real field names to the `_STRIKE_ALIASES` / `_OPTION_TYPE_ALIASES`
/ etc. lists at the top of that file, and update them if they don't match.

### Setup

```bash
export FMP_API_KEY=your-fmp-api-key
```

### CLI usage

```bash
voldesk fetch --provider fmp --symbol TSLA
# optional: --expiration 2026-08-21 --risk-free-rate 0.05 --dividend-yield 0.0
```

Sample output:

```
Vol Desk fetch report: TSLA (FMP)
  spot:              251.3
  as_of:             2026-07-01
  total_net_gex:     1234567.89
  gex_ratio:         0.5821
  zero_gamma_strike: 245.30
  max_oi_strike:     250.00
  oi_ratio:          0.5104
  dex_ratio:         0.6210
  vex_ratio:         0.4998
  cex_ratio:         0.5555
  vgex_ratio:        0.6002

p_trans:   NOT YET DEFINED (no published formula -- see README)
n_trans:   NOT YET DEFINED (no published formula -- see README)
cotmp:     NOT YET DEFINED (no published formula -- see README)
cotmc:     NOT YET DEFINED (no published formula -- see README)
grade:     NOT YET DEFINED (no published formula -- see README)
db_change: NOT YET DEFINED (no published formula -- see README)
```

`--provider` currently only accepts `fmp`; other values raise a clear
"not implemented" error (the option exists so future providers can be
added without changing the CLI surface).

## Module map

- `voldesk/models.py` -- shared dataclasses and enums.
- `voldesk/grading.py` -- the five entry filters and `evaluate_setup`.
- `voldesk/entry.py` -- the 5-minute candle close entry trigger.
- `voldesk/regime.py` -- the macro/regime gate evaluation.
- `voldesk/exits.py` -- the stop framework and take-profit recommendation.
- `voldesk/ingest.py` -- gamma screen CSV loading.
- `voldesk/ledger.py` -- JSON-file-backed position ledger.
- `voldesk/greeks.py` -- Black-Scholes delta/gamma/vanna/charm, stdlib-only.
- `voldesk/gex.py` -- GEX/vGEX/DEX/VEX/CEX, ratios, zero-gamma strike, OI
  walls, computed from an options chain + greeks.
- `voldesk/sources/fmp.py` -- FMP options-chain and quote client.
- `voldesk/cli.py` -- the `voldesk` command-line tool.

# 0DTE SPY/QQQ process

A gated, rules-based process for short-duration directional 0DTE trades on
SPY and QQQ. It encodes the approach from the thread that prompted it —
trade with the tech tape, use the 9/21 EMA stack and premarket levels for
timing, take profit quickly rather than holding for a runner — and adds the
risk scaffolding that the thread itself identified as the missing piece
("I want to size up but know that's when shit goes south").

**The engine produces a signal. It never places an order.** Contract choice
and order entry stay manual by design.

---

## What this is not

- **Not a backtester.** `--now` shifts the timing gate only; quotes are
  always fetched live. Replaying a past timestamp does not rewind price.
- **Not validated as profitable.** No walk-forward test, no live sample.
  The gates encode a plausible, internally-consistent rule set — that is
  all. Paper trade it before risking money.
- **Not financial advice.** 0DTE options routinely go to zero. The default
  risk budget is 1% of a $25k account per trade; set it to something you're
  content to lose.

---

## Data sources: what is actually wired

| Need | Source | Status |
|---|---|---|
| Daily bars (200 SMA) | FMP `/stable/historical-price-eod/full` | Working |
| Intraday bars (9/21 EMA, VWAP, ATR) | FMP `/stable/historical-chart/5min` | Working |
| Tech-complex quotes (regime) | FMP `/stable/batch-quote` | Working |
| **Premarket high/low** | **Robinhood MCP** `get_equity_historicals` | Working, manual step |
| Live quote | Robinhood MCP, else FMP | Working |
| 0DTE chain / contracts | Robinhood MCP | Working, manual step |
| Flow confirmation | Unusual Whales | **Not wired — no credential** |

Two things are worth knowing before you rely on this:

**FMP has no premarket data.** A 1-minute request returns exactly 390 bars
per session, 09:30–15:59 ET. Since premarket high/low is load-bearing for
the entry rules, those levels come from the broker feed instead. Robinhood's
`get_equity_historicals` with `bounds='extended'` tags each bar `pre` /
`reg` / `post`, which is what makes them computable.

**Unusual Whales is not connected.** There is no `UW_API_KEY` in this
environment and no UW connector installed, despite the plan assuming one.
`odte/uw.py` implements the adapter against UW's documented v1 shape, but
none of it has been run against the live API. It is gated so that its
absence changes nothing: without a key it returns `None`, and even when
present it only nudges *conviction* — it can neither open a trade the price
gates rejected nor veto one they accepted. So a wrong field name costs you a
slightly mis-scored number, not a bad entry. Set `UW_API_KEY` and pass
`--use-uw` to reconcile it against a real payload.

Legacy FMP `/api/v3/` routes are dead for keys issued after 2025-08-31 —
they return a "Legacy Endpoint" error. Everything here uses `/stable/`.

---

## The rules

A trade requires **all five gates** to agree. Every gate is evaluated even
after one fails, so the output always explains the full picture — a
no-trade with no reasoning is impossible to review after the close.

**1. Timing.** Entries only between 09:40–11:30 and 13:30–15:00 ET. The
opening rotation hasn't resolved before 09:40, midday is where trend
strategies bleed, and after 15:00 gamma makes premium behave differently.
Flat by 15:30 — Robinhood force-closes 0DTE positions 30 minutes before
expiry (`sellout_time_to_expiration: 1800` on the SPY chain), and you do not
want to discover that at 15:45.

**2. Risk budget.** Max 3 trades/day, and two losers ends the day. This is
the gate that does the most work over a month.

**3. Data.** Price, both EMAs, ATR and both premarket levels must exist. No
premarket data means no trade, rather than a trade on partial information.

**4. Regime — the actual edge.** Tech strength scored to `[-1, 1]` from
three components:

- `sector_rs` (35%) — XLK's day change relative to SPY.
- `breadth` (40%) — how much of the mega-cap complex (NVDA, MSFT, AAPL,
  AVGO, META, GOOGL, AMZN, TSLA) is green. This catches the case where one
  gapping name carries XLK while the rest of the group is flat; that is not
  a real tech bid, and the sector term alone would misread it.
- `qqq_rs` (25%) — QQQ relative to SPY, confirming the index expresses it.

`|score| >= 0.20` gives a direction; `>= 0.50` is "strong". Anything inside
±0.20 is **NEUTRAL and does not trade**. That is the thread's "if it's
neutral that's a bit more of a difficult day for me", turned into a
threshold instead of a feeling.

**5. Trend.** Price above EMA9 above EMA21 for longs (inverted for shorts),
with price clearing the fast EMA by 10% of ATR so EMA-hugging chop doesn't
qualify. The 200 SMA is reported and feeds conviction, but does not veto —
intraday 0DTE trades against the daily trend are common and often the best
ones.

**6. Level.** Price must have cleared the premarket high (longs) or broken
the premarket low (shorts) by 5% of ATR. The buffer is there so a one-tick
poke doesn't arm a trade.

### Exits

Fixed and mechanical, because 0DTE decay punishes discretion:

- **+30%** on premium — target
- **−25%** on premium — stop
- **25 minutes** — time stop; if it hasn't worked, the thesis was wrong
- Trail after **+20%** rather than holding for a runner
- **Flat by 15:30** regardless of P&L
- Underlying invalidation: a 5-minute close back through the broken level
  or the fast EMA, whichever is nearer

### Sizing

`quantity = floor(risk_dollars / (premium × 100 × stop%))`, capped at 10
contracts. Risk is a fixed 1% of account — **size never scales with
conviction**. Conviction is reported for review, not for sizing. That is
deliberate: scaling size with confidence is precisely the failure the
thread was worried about.

---

## Running it

```bash
cd tools/0dte
pip install -r requirements.txt
export FMP_API_KEY=...        # already set in this workspace

# regime only — cheap, one API call, good for a pre-open read
python -m odte.cli regime

# full signal (needs premarket data, see below)
python -m odte.cli signal --symbol SPY --broker-data premarket.json
python -m odte.cli signal --symbol QQQ --broker-data premarket.json --json
```

### The premarket step

The Robinhood connection is an MCP server — callable by the agent, not by
this process. So the premarket bars come across as a file:

1. Call `mcp__Robinhood__get_equity_historicals` with
   `symbols=["SPY","QQQ"]`, `bounds="extended"`, `interval="5minute"`,
   `start_time` = 08:00Z on the session date.
2. Save the raw JSON.
3. Pass it with `--broker-data`.

`/0dte` (`.claude/skills/0dte/SKILL.md`) does all three steps plus the chain
pull. If you later add direct broker credentials, write a client that emits
`Bar` and `Quote` and nothing downstream changes.

### Reading the output

```
  [pass] timing       10:00 is inside an entry window
  [pass] regime       STRONG_BULL (score +0.70) | XLK vs SPY +1.00, breadth +0.25 (5/8 green)
  [pass] trend        price 741.69 > EMA9 741.55 > EMA21 741.16; with the 200SMA
  [pass] level        price 741.69 is above premarket high 736.06
```

A `fail` line tells you exactly which condition was missing, which is the
part worth logging daily.

---

## Layout

```
odte/config.py       every tunable number, in one auditable place
odte/models.py       Bar / Quote / Signal / Gate types shared by both feeds
odte/indicators.py   EMA, SMA, ATR, VWAP — pure, fully tested
odte/fmp.py          FMP stable client
odte/brokers.py      Robinhood MCP payload -> Bar / Quote
odte/uw.py           Unusual Whales adapter (optional, unwired)
odte/regime.py       tech-strength scoring
odte/levels.py       premarket / opening range / indicator assembly
odte/signal.py       the six gates and the trade plan
odte/contract.py     0DTE contract filtering and position sizing
odte/cli.py          `python -m odte.cli`
```

`python -m pytest` — 55 tests covering the indicator maths, regime
classification (including the narrow-leadership case), every gate's reject
path, contract filtering, sizing, and parsing of a real Robinhood payload.

## Tuning

Everything lives in `odte/config.py`. The two you'll actually want to change
first are `RiskConfig.account_size` (defaults to $25k) and
`RegimeConfig.directional_threshold` — raise it to 0.30 to trade less and
only on clear tech days, lower it to 0.15 to see more signals.

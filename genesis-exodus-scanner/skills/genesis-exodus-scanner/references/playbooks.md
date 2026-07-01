# Playbooks — Genesis / Exodus / Turtle

Reference detail for SKILL.md §5 (position state machine) and §7 (buy discovery). The skill is
the authority on gating; this file is the mechanics behind each engine's score.

## Trend Template (Minervini-style quality filter)

A symbol passes the trend template when ALL of the following hold (computed by
`scripts/fmp.py indicators SYM`, field `trend_template_pass`):

1. Price > 150-day SMA and price > 200-day SMA.
2. 150-day SMA > 200-day SMA.
3. 200-day SMA has been trending up for at least ~1 month (`sma200_rising`).
4. Price > 50-day SMA (the near-term trend agrees with the longer one).
5. Price is at least ~30% above its 52-week low.
6. Price is within ~25% of its 52-week high.

Names that fail the trend template are never buy candidates, regardless of how good their
short-term setup looks — Genesis, Exodus, and Turtle all require it as a floor.

## Genesis engine — "own the leaders"

Primary entry style. Discovery: `fmp.py screener` for a quality, liquid US universe (real
companies, no ETFs/funds — `isEtf=false`, `isFund=false`), then rank by blended relative strength
(`fmp.py rs SYM`) among names that pass the trend template.

Score 0–10 on:
- Relative strength percentile vs. the current universe (higher = better).
- Trend template pass (hard requirement — 0 if failed).
- Distance from ideal entry (near a natural support / prior breakout level scores higher; more
  than ~8% above ideal entry is disqualifying per SKILL.md §7).
- Volume quality: `avgDollarVol20` comfortably above your minimum liquidity floor.
- Sector concentration: does adding this name push a sector over the `<=3 per sector` cap?
- Earnings guard clean (`fmp.py earnings SYM`, `earnings_guard_block=false`).

A fresh breakout (`breakout20` / `breakout55` true) is a bonus, not a prerequisite — Genesis will
buy a strong leader mid-trend if the trend template and relative strength both qualify.

## Exodus engine — rebound / capitulation-recovery

Discovery: `fmp.py movers` losers list, filtered to names that still pass a relaxed trend check
(price didn't just break its 200-day SMA — a broken long-term trend is a Genesis disqualifier, not
an Exodus opportunity). Exodus looks for high-quality names that sold off sharply on the day but
remain structurally sound, with a stop just below the day's low or a recent higher-low.

Score 0–10 on:
- Quality of the underlying trend (still must pass or nearly pass the trend template).
- Reason for the drop: prefer broad-market/sector-driven selloffs over company-specific bad news
  (`fmp.py news SYM` as an advisory read — a name gapping down on negative company news is usually
  a pass, not a rebound buy).
- R:R from a tight stop just under the day's low/recent structure to a realistic near-term target.
- Not within the earnings guard window.

## Turtle engine — breakout confirmation

Only evaluated for candidates that already pass Genesis-quality (trend template + no earnings
conflict). Turtle adds a classic breakout confirmation:
- `breakout20` or `breakout55` true (new 20- or 55-day high).
- Entry stop sized off `atr20` (~1x ATR below entry, tightened to the SKILL.md ~10% cap if ATR
  would put the stop further away).
- Same scoring floor as Genesis (>=7/10, R:R >=2:1) — Turtle is a confirmation signal layered on
  top of Genesis-quality, never a way to relax the other gates.

## Position state machine (SKILL.md §5)

```
OPEN
  -> TARGET_NEAR        (price within ~2% of the +10% first target)
  -> SELL_LIMIT_READY    (target hit this scan, no resting sell yet)
  -> SELL_LIMIT_PLACED   (partial take-profit order resting/placed)
  -> SELL_LIMIT_FILLED   (broker confirms the partial filled)
  -> PRINCIPAL_RECOVERED (realized proceeds >= original cost basis for the position)
  -> FREE_RIDE_POSITION  (remaining runner, trailing stop ~25% off highest close, no cap)

STOP_WARNING    (price within ~2% of the current stop — no action yet, flag it)
EXIT_REQUIRED   (price at/through the stop — place the protective exit this scan)
CLOSED          (position fully exited; ledger-add the outcome)
```

Re-derive state from the live account every scan (`get_equity_positions` + `get_equity_orders`
are the source of truth) — never trust a state carried over from a prior scan's notes.

## Universe rules (hard scope, SKILL.md §7)

Never, without explicit manual approval: options, shorting, margin, leveraged ETFs, crypto,
futures, penny stocks (<$5), low-volume pumps, biotech binary-event gambles, averaging down,
after-hours trades. The screener (`isEtf=false`, `isFund=false`, `priceMoreThan` >= your floor,
`volumeMoreThan` >= your liquidity floor) enforces the mechanical parts of this; the earnings
guard and news sensor cover the binary-event and headline-risk parts.

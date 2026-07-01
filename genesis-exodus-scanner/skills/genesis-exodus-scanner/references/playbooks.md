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

## Reward:Risk formula (the SKILL.md §7 "R:R >= 2:1" gate)

This used to be left to per-scan judgment, which meant two runs on the same borderline name could
reasonably reach different conclusions. It's now computed deterministically by
`fmp.py indicators SYM` (`compute_reward_risk()` in `scripts/fmp.py`) and returned as
`reward_pct` / `risk_pct` / `rr_ratio` / `rr_pass` / `reward_method`:

- **Risk** is always the 10% initial stop (`SKILL.md` §0's `INITIAL_STOP`) — `risk_pct = 10.0`.
- **Reward** depends on how much room is left before the next real resistance:
  - If price is **more than 3% below its 52-week high** and not confirmed breaking out: reward is
    the % distance up to that prior high (the classic "room to the last swing high" measure).
  - If price is **within 3% of its 52-week high**, or `breakout20`/`breakout55` is true: there's no
    overhead resistance left to measure, so reward is instead **3x ATR20** (as a % of price) — a
    rough proxy for near-term continuation room, not a promise of a specific target.
- `rr_ratio = reward_pct / risk_pct`; the buy gate requires `rr_ratio >= 2.0` (`rr_pass`).
- If 52-week-high or ATR20 data is missing, the function returns `null` — treat that as a gate
  **failure**, never substitute a guessed number (SKILL.md's honesty rule applies here too).

Worked examples from the 2026-07-01 $1,000 paper-simulation run (see `state/journal.jsonl` /
session notes for the full comparison):

| Symbol | Price | 52wk high | Distance to high | Method used | Reward% | R:R | Passes 2:1? |
|---|---|---|---|---|---|---|---|
| INTC | $127.02 | $142.35 | -10.77% (not near) | distance-to-high | 10.77% | 1.08:1 | No |
| NBIS | $229.18 | $299.86 | -23.57% (not near) | distance-to-high | 23.57% | 2.36:1 | **Yes** |
| BAC  | $58.36  | $59.20  | -1.42% (near/at high) | 3x ATR20 | 6.20% | 0.62:1 | No |

The 3% "near-high" threshold and the 3x ATR multiple (`RR_NEAR_HIGH_THRESHOLD_PCT` /
`RR_ATR_REWARD_MULTIPLE` in `scripts/fmp.py`) are CUSTOMIZE constants like everything else in the
active growth profile — backtest before changing them, and expect the pass/fail line to move
candidates like INTC (very close to 2:1 already) across it.

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
- Reason for the drop: prefer broad-market/sector-driven selloffs over company-specific bad news.
  This is no longer just a scoring input — SKILL.md §2 step 12b / §7 NEWS CHECK makes running
  `fmp.py news SYM` and recording an explicit pass/fail judgment MANDATORY for the top candidate
  before any buy, Exodus or Genesis. A name gapping down on negative company-specific news is
  disqualified to WATCHLIST, full stop, no matter how clean the rest of the setup is.
- R:R from a tight stop just under the day's low/recent structure to a realistic near-term target.
- Not within the earnings guard window.

### Worked example: why the news check is mandatory, not advisory

On 2026-07-01, a $5,000 paper simulation ran NBIS (Nebius Group) through every quantitative gate:
trend template pass, RS vs. SPY of 106 (near the top of the universe), R:R of 2.36:1 (cleared the
2:1 bar), earnings clear (36 trading days out), no sector-cap conflict, affordable at the sizing
cap. On paper, a clean BUY. But `fmp.py news NBIS` (and a plain read of the headlines) showed the
day's -17% drop was driven by Meta — Nebius's largest customer — announcing it was building
competing in-house AI cloud infrastructure: a direct, company-specific competitive threat, not a
broad selloff. The correct call was WATCHLIST, not BUY, despite every other gate passing cleanly.
`fmp.py news SYM` also returns a `negative_keyword_scan` field (see `scripts/fmp.py`'s
`scan_news_for_negative_catalysts()`) that would have auto-flagged this case (matched "threat" and
"tumble" across two of the real headlines) — a cheap first-pass prompt to look closer, not a
verdict. The keyword flag can miss real bad news phrased without a listed word, and can also flag
harmless mentions, so reading the actual headlines and writing down the one-line reason is still
required every time, not just when the flag fires.

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

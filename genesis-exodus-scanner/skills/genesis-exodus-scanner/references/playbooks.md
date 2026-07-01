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

## Ideal entry (the SKILL.md §7 "price <= 8% above ideal entry" gate)

This was undefined prose until now — SKILL.md required the check without ever specifying what
"ideal entry" *is*. It's now computed deterministically by `fmp.py indicators SYM`
(`compute_ideal_entry()` in `scripts/fmp.py`), returned as `ideal_entry` /
`pct_above_ideal_entry` / `entry_gate_pass` / `entry_method`:

- **Confirmed breaking out** (`breakout55`, or `breakout20` if not `breakout55`): ideal entry is
  the level just cleared — the 55-day or 20-day high. Buying right at/near a fresh breakout is the
  ideal Turtle-style entry; buying it 15% past the breakout level is chasing.
- **Otherwise** (the far more common case for Genesis's primary "own the leader" style, which
  explicitly doesn't require a fresh breakout): ideal entry is the **50-day SMA** — the natural
  pullback/support level in an established uptrend. A name trading far above its own 50-day
  average has already run; entering there has a worse risk profile than catching it on a
  controlled pullback toward that average.
- `pct_above_ideal_entry = (price - ideal_entry) / ideal_entry * 100`; the gate needs
  `pct_above_ideal_entry <= 8.0` (`entry_gate_pass`).
- Missing SMA50/breakout-level data -> the function returns `null` -> treat as a gate **failure**.

Worked examples (all previously analyzed candidates -- none of these needed the breakout-level
branch, since none had `breakout20`/`breakout55` true that day):

| Symbol | Price | 50-DMA | Method | % above ideal entry | Passes <=8%? |
|---|---|---|---|---|---|
| INTC | $127.02 | $112.30 | 50-day SMA | 13.11% | No |
| NBIS | $229.18 | $213.91 | 50-day SMA | 7.14% | **Yes** |
| TTWO | $250.32 | $225.54 | 50-day SMA | 10.99% | No |

Notably, INTC and TTWO both already failed on other gates (R:R and trend-template, respectively)
— this check independently confirms both were too extended above their own support to be a good
entry regardless, which is a useful cross-check rather than a redundant one: a candidate can pass
R:R and trend template while still being priced too far from a sane entry point (e.g. mid-breakout
momentum names right before this check was added would have slipped through on that basis alone).

For Exodus-sourced candidates (buying today's plunge itself), this gate is usually trivially
satisfied or even negative (price below the 50-DMA reference) -- that's expected and fine. The
gate exists to stop chasing an extended Genesis-style move, not to add friction to a legitimate
capitulation buy.

## Deployable-capital floor (SKILL.md §2's no-deployable-capital fast-path)

Also previously undefined -- SKILL.md said "BP below your smallest-deployable floor" without a
number. `scripts/ops.py`'s `DEPLOYABLE_CAPITAL_FLOOR = $10.00`, checked via
`ops.py preflight --nav <nav> --buying-power <bp>` (`deployable_capital_ok` in its output).

Derivation: the whole-share rule requires >=2 shares of any new entry, and the screener's own
`UNIVERSE_PRICE_FLOOR` is $5.00 (`scripts/fmp.py`) -- so $10 (2 x $5) is the absolute floor below
which no valid buy exists anywhere in our own universe, full stop. This isn't meant to represent
"enough capital for a *meaningful* trade" (in practice, sizing/R:R/liquidity will reject almost
anything bought with barely-above-floor capital anyway) -- it's the precise boundary below which
running discovery at all is provably pointless, so the fast-path exists mainly to save wasted
API/token cost on a scan that could never place an order regardless of what it found.

The two constants ($5 price floor in `fmp.py`, $10 deployable floor in `ops.py`) are duplicated
across the two independent CLI scripts (they don't import each other) rather than shared -- if you
change `UNIVERSE_PRICE_FLOOR`, update `DEPLOYABLE_CAPITAL_FLOOR` to match (2x it) by hand.

## Confidence formula (the SKILL.md §7 "confidence >= 7" gate)

The original build guide required "Score 0-10 each; BUY only if ALL: confidence >=7..." without
ever defining what the score is made of -- like R:R and ideal entry, this was left as prose. It's
now computed by `fmp.py confidence SYM` (`compute_confidence()` in `scripts/fmp.py`).

**Design principle: this scores MARGIN beyond gates that already exist separately, it doesn't
duplicate or replace them.** Trend template, R:R, liquidity, entry quality, the earnings guard, and
the mandatory news check are all independent hard pass/fail requirements elsewhere in SKILL.md §7
-- a candidate needs ALL of them to pass regardless of its confidence score. Confidence exists to
answer a different question: among candidates that already clear every hard gate, which one is the
strongest conviction, and is even a technically-qualifying candidate actually good enough to act on
(the >=7 bar can still reject a marginal pass)?

**`trend_template_pass = false` is a hard zero**, not a partial score -- matching this file's
original (never-implemented) note under the Genesis engine that trend template is "a hard
requirement -- 0 if failed." A stock that isn't a confirmed trend leader gets confidence=0 no
matter how good its other numbers look.

Otherwise, 5 dimensions each contribute 0-2 points (10 max), scoring how far a candidate clears its
own dimension's separate minimum -- not just whether it clears it:

| Dimension | 2 points | 1 point | 0 points |
|---|---|---|---|
| Relative strength (`rs_vs_spy`) | >= 50 (clear leadership) | >= 15 (real but modest) | < 15 |
| R:R margin (`rr_ratio`) | >= 3.0 | >= 2.0 (the minimum) | < 2.0 |
| Entry quality (`pct_above_ideal_entry`) | <= 2% | <= 8% (the maximum) | > 8% |
| Liquidity margin (`avgDollarVol20`) | >= 3x the $3M floor ($9M+) | >= 1x the floor | below floor |
| Earnings safety margin | >= 15 trading days out | > 7 (the guard minimum) | <= 7 (already blocked) |

Missing data on any dimension scores that dimension 0 -- fail closed, same as every other gate in
this file, never a guessed middle value.

Worked examples from real 2026-07-01 data:

| Symbol | RS | R:R | Entry | Liquidity | Earnings | Confidence | Notes |
|---|---|---|---|---|---|---|---|
| NBIS | 2 (106.2) | 1 (2.36) | 1 (7.14%) | 2 ($4.5B/day) | 2 (36d) | **8/10** | Passes the >=7 bar on confidence alone -- still correctly blocked by the mandatory news check (Meta competitive threat). Proof the score doesn't override the other gates. |
| INTC | 2 (173.2) | 0 (1.08) | 0 (13.1%) | 2 ($16.1B/day) | 2 (22d) | 6/10 | Below the bar -- consistent with its independent R:R and entry-gate failures. |
| TTWO | -- | -- | -- | -- | -- | 0/10 | Hard zero: `trend_template_pass=false` (150-DMA below 200-DMA). |

The exact thresholds (50/15 for RS, 3.0 for strong R:R, 2%/8% for entry, 3x for liquidity, 15 days
for earnings) are CUSTOMIZE constants (`CONFIDENCE_*` in `scripts/fmp.py`) like everything else in
the active growth profile -- backtest before changing them.

## Genesis engine — "own the leaders"

Primary entry style. Discovery: `fmp.py screener` for a quality, liquid US universe (real
companies, no ETFs/funds — `isEtf=false`, `isFund=false`), then rank by blended relative strength
(`fmp.py rs SYM`) among names that pass the trend template.

Score via `fmp.py confidence SYM` (see "Confidence formula" above for the full breakdown: relative
strength, R:R margin, entry quality, liquidity margin, earnings safety margin, with trend template
as a hard zero). Sector concentration (does adding this name push a sector over the `<=3 per
sector` cap?) is checked separately as a portfolio-level cap, not folded into the per-symbol score.

A fresh breakout (`breakout20` / `breakout55` true) is a bonus, not a prerequisite — Genesis will
buy a strong leader mid-trend if the trend template and relative strength both qualify.

## Exodus engine — rebound / capitulation-recovery

Discovery: `fmp.py movers` losers list, filtered to names that still pass a relaxed trend check
(price didn't just break its 200-day SMA — a broken long-term trend is a Genesis disqualifier, not
an Exodus opportunity). Exodus looks for high-quality names that sold off sharply on the day but
remain structurally sound, with a stop just below the day's low or a recent higher-low.

Score via `fmp.py confidence SYM`, same as Genesis (trend template still applies as a hard zero —
"relaxed" above means the discovery/screening step is lenient about a fresh breakout not being
required, not that the trend template gate itself is skipped). Two things matter more here than for
a typical Genesis entry:
- Reason for the drop: prefer broad-market/sector-driven selloffs over company-specific bad news.
  This is no longer just a scoring input — SKILL.md §2 step 12b / §7 NEWS CHECK makes running
  `fmp.py news SYM` and recording an explicit pass/fail judgment MANDATORY for the top candidate
  before any buy, Exodus or Genesis. A name gapping down on negative company-specific news is
  disqualified to WATCHLIST, full stop, no matter how clean the rest of the setup is (or how high
  it scored on confidence -- see the worked example below).
- R:R from a tight stop just under the day's low/recent structure — the standard R:R formula
  already accounts for this via the ATR-multiple branch when a name is near its highs, but a stop
  placed at the day's actual low/recent structure (rather than a flat 10%) may be tighter and
  produce a better real R:R than the formula's default assumption; use judgment on which stop is
  actually being risked.

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

## Watchlist entries (state/watchlist.json, SKILL.md §2 step 11b)

A candidate that's interesting but doesn't clear every gate today (failed trend template, failed
R:R, or was disqualified by the mandatory news check) gets logged here instead of just forgotten,
so future scans re-check it cheaply without re-running full discovery. Schema:

```json
{
  "watchlist": [
    {
      "symbol": "TTWO",
      "added_at": "2026-07-01",
      "added_reason": "why it was interesting + why it didn't qualify yet",
      "reevaluate_when": "the specific, checkable condition that would flip the verdict",
      "last_checked": {"date": "...", "price": 0.0, "trend_template_pass": false, "rr_ratio": 0.0, "news_check": "PASS|FAIL (reason)"}
    }
  ]
}
```

`reevaluate_when` must be something a scan can actually test cheaply (an indicators/earnings
field crossing a threshold), not a vague narrative -- "re-check when 150-DMA crosses above
200-DMA" is checkable every scan for free; "re-check when the market likes it again" is not.
Every trigger check still runs the FULL gate stack (including a fresh mandatory news check) before
any buy -- being on the watchlist waives nothing, it just saves re-running discovery from scratch.

## Universe rules (hard scope, SKILL.md §7)

Never, without explicit manual approval: options, shorting, margin, leveraged ETFs, crypto,
futures, penny stocks (<$5), low-volume pumps, biotech binary-event gambles, averaging down,
after-hours trades.

These are now persisted defaults in `scripts/fmp.py` (`UNIVERSE_*` constants), not ad hoc flags
typed in each session -- a bare `fmp.py screener` call applies them automatically:

| Constant | Default | Purpose |
|---|---|---|
| `UNIVERSE_MARKET_CAP_FLOOR` | $300,000,000 | Excludes micro-caps; still opens up quality small/mid-caps (was implicitly $5B+ in early sessions before this was formalized) |
| `UNIVERSE_PRICE_FLOOR` | $5.00 | Matches the hard-scope penny-stock exclusion exactly |
| `UNIVERSE_SHARE_VOLUME_FLOOR` | 200,000 shares/day | Coarse pre-filter on the screener call itself |
| `UNIVERSE_MIN_AVG_DOLLAR_VOL20` | $3,000,000/day | The real liquidity gate -- checked post-screener via `fmp.py indicators`'s `liquidity_pass` field, since dollar volume (not raw share count) is what actually governs slippage and manipulation risk. Required alongside `trend_template_pass` and `rr_pass` before any buy. |

`isEtf=false` / `isFund=false` / `isActivelyTrading=true` are hardcoded, not overridable. All four
`UNIVERSE_*` floors can be overridden per-call via explicit `--marketCapMoreThan` etc. flags for a
one-off query (e.g. deliberately widening or narrowing the universe) — but the defaults are what
an actual scheduled scan gets if it just calls `fmp.py screener` plainly. The earnings guard and
mandatory news check (see below) cover the binary-event and headline-risk parts of hard scope.

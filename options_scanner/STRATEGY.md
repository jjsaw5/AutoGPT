# Strategy — how the engine finds strong new positions

*Companion to the code. Recommend-only decision support; a human confirms every
order. Every GO is a hypothesis to validate (§9), not a signal to trust blindly.*

Everything here is what a bare `scan` (no `--tickers`) does — the opportunity
hunt. The same pipeline also grades positions you already hold, so a new idea
and a held trade are directly comparable.

**Core principle — vol regime decides everything before direction does.** When
implied vol is **cheap**, the engine looks to **buy** premium (long options,
debit spreads, LEAPS). When it's **rich**, it looks to **sell** premium (credit
spreads, iron condors). A great directional read in the wrong vol regime scores
near zero — that anti-pattern is the whole reason the scanner exists.

Key parameters: GO ≥ 72 · WATCH 58–71 · account $5,000 · per-trade $200 standard
/ $500 ceiling · aggregate ≤ $2,000 & ≤ 6 positions.

## The funnel — nine stages

### 1 · Discovery (two-tier universe)
UW's market-wide feeds scan the whole market server-side, so we get reach
without brute-forcing ~5,000 names.
- **Tier A** — curated liquid core watch, scored every scan.
- **Tier B** — feed-driven pull-ins that surface names *not* on the watchlist:
  flow alerts, hottest chains, unusual OI change, vol anomalies (live on base
  tier); top movers (needs UW Advanced — degrades silently); congress/insider
  and upcoming-catalyst feeds. Cap-tier tags (MEGA/LARGE/MID/SMALL; MICRO
  manual-only) drive gate thresholds and sizing.

### 2 · Enrichment (signal snapshot, cached per-ticker per-scan)
- **FMP** — price, market cap, sector, avg volume, earnings dates.
- **UW** — IV rank, IV-vs-RV, net-premium flow, dark-pool skew, term structure,
  max pain, flow alerts.
- **UW chain** — per-strike OI, volume, NBBO bid/ask, IV, delta.
- **Robinhood** — live-quote confirm, buying power, execution (human-gated, at
  order time only).

### 3 · Thesis
- **Direction + conviction** — agreement across net-premium flow, dark-pool
  skew, price vs moving averages.
- **Vol regime** (the pivot) — cheap ≤ IVR 30, rich ≥ 50, else fair;
  cross-checked vs realized vol.
- **Horizon** — intraday (0DTE) / swing / position / LEAPS.
- **Catalyst** — earnings / flow / technical / news + days-to-event.
- **Implied vs expected move** — long premium only when expected > implied.

### 4 · Structure (regime-first, real strikes from the live chain)
| Regime | Read | Structure |
|---|---|---|
| cheap | strong, swing | long call/put (debit) |
| cheap | strong, LEAPS | deep-ITM LEAPS (~0.75Δ) |
| cheap | moderate | debit vertical |
| rich | directional | credit vertical |
| rich | neutral | iron condor |
| rich | into earnings, move < implied | credit spread (harvest crush) |
| fair+ | into earnings, move > implied | debit spread |
| any | strong intraday flow | defined-risk 0DTE spread |

Baked-in: prefer spreads over naked long premium when IVR is elevated; never
long premium through earnings unless tagged an earnings play; 0DTE always
defined-risk + top-liquidity. Widths are chosen to be liquid and to fit the
per-trade risk cap.

### 5 · Hard gates (any failure = PASS, regardless of score)
| Gate | Rule |
|---|---|
| G1 | OI ≥ 500 & volume ≥ 100 (scaled by cap tier) — real chain |
| G2 | bid/ask ≤ 10% of mid (≤ 5% for 0DTE) — real chain |
| G3 | underlying $-volume floor by cap tier |
| G4 | no long premium held through earnings unless it's the thesis |
| G5 | 0DTE ≤ 3/week, defined-risk, top-liquidity |
| G6 | per-trade risk ≤ $200 standard, $500 ceiling |
| G7 | open + new ≤ $2,000 and ≤ 6 positions |
| G8 | reject stale quotes/flow (weekend/holiday/halt) |
| G9 | flag short leg ITM near expiry (assignment) — real chain |
| G10 | intraday margin deficit under safe harbor |

A setup blocked *only* by G6/G7 is the "would we have won if we could afford it"
case, tracked separately (stage 9).

### 6 · Scoring (0–100 composite; weights are priors to be re-fit)
| Pillar | Measures | Wt |
|---|---|---|
| P1 Vol edge | buying cheap / selling rich vol; regime-conditional | 25 |
| P2 Direction | strength + agreement of flow, dark pool, technicals | 22 |
| P3 Expected value | POP × reward vs (1−POP) × risk, net of fees/slippage | 20 |
| P4 Catalyst | presence, proximity, reliability; expected vs implied move | 18 |
| P5 Liquidity | tightness beyond the gate — spread %, depth, OI | 10 |
| P6 Corroboration | # of independent agreeing signals; single-signal penalized | 5 |

POP is delta-based off the real chain. P1 → ~0 on a structure/regime mismatch —
the mechanism that enforces the core principle.

### 7 · Decision (all three required for GO)
`composite ≥ 72` **and** `all gates pass` **and** `EV > 0`. Otherwise WATCH
(≥ 58) or PASS. GO size scales with score above 72, capped by G6, inside the
$2,000 / 6-position aggregate cap.

### 8 · Readout
GO-first core book (legs, pillars, POP, max P/L, breakevens, gates, size, why +
biggest risk) · separated speculative/0DTE bucket (higher bar, off-budget) ·
portfolio summary. You confirm every order.

### 9 · Journal & calibration
Every strong idea is logged, including the ones we don't take. Exact legs are
re-priced against the live chain into win/loss/scratch, feeding a Brier score on
POP, win-rate by composite bucket, and a regime × structure audit — the loop
that calibrates the weights.

## What "strong" means — a GO clears all at once
- Regime-appropriate structure (buy cheap / sell rich vol).
- Corroborated direction (multiple independent signals agree).
- Positive expected value after fees/slippage.
- Real, tradeable liquidity on the actual strikes.
- A catalyst with proximity inside the horizon.
- Defined risk that fits the per-trade and aggregate caps.

## Caveats before trusting a GO
- **Weights are priors, not truth** — validated only by the stage-9 loop.
- **Base-tier reach** — `movers` and full-universe enumeration need UW Advanced;
  discovery works without them, just narrower.
- **Recommend-only** — a human confirms every order.

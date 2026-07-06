# Methodology — full technical reference

*Everything the engine actually computes: data sources, formulas, thresholds,
and the assumptions most worth reviewing. Grounded in the code, not the spec.
Recommend-only; a human confirms every order.*

> **How to read this:** every number here is a **tunable knob or a placeholder
> prior**, not a law. The "⚠ Review" callouts flag the ones most likely to need
> your judgment. The whole point of the calibration loop (§10) is to replace
> these priors with values fit from your own outcomes.

---

## 1. What the system does

On a bare `scan` it hunts the whole market for optionable setups, builds a
thesis and a concrete options structure for each, filters on hard rules, scores
six ways, applies a market-regime overlay, and emits a ranked **GO / WATCH /
PASS** readout. The same pipeline also grades positions you already hold.

**Core principle:** *vol regime decides buy-vs-sell before direction does.* Cheap
vol → buy premium; rich vol → sell premium. A great directional read in the
wrong regime scores near zero.

---

## 2. Data sources — exactly what comes from where

| Source | Endpoint | Fields we use | Feeds |
|---|---|---|---|
| **FMP** | `/stable/profile` | market cap, sector, avg volume, price | universe cap-tier, G3 |
| **FMP** | `/stable/quote` | price, volume, 50/200-day avg | thesis technicals |
| **FMP** | `/stable/earnings` | next earnings date | catalyst, G4 |
| **FMP** | `/stable/historical-price-eod/light` | daily closes (8 ETFs) | market regime |
| **FMP** | `/stable/treasury-rates` | year10, year2 | regime yield curve |
| **UW** | `/stock/{t}/iv-rank` | `iv_rank_1y`, `volatility` (IV) | vol regime, P1 |
| **UW** | `/stock/{t}/volatility/realized` | implied vs realized vol | P1 (IV-vs-RV) |
| **UW** | `/stock/{t}/net-prem-ticks` | net call/put premium & volume | direction, P2 |
| **UW** | `/stock/{t}/flow-alerts` | per-alert OI, volume, side | P5, G1 proxy |
| **UW** | `/darkpool/{t}` | prints vs NBBO midpoint | direction (dark-pool skew) |
| **UW** | `/stock/{t}/volatility/term-structure` | `implied_move_perc` by DTE | implied move |
| **UW** | `/stock/{t}/max-pain` | max-pain strike | context |
| **UW chain** | `/stock/{t}/option-contracts?expiry=` | per-strike OI, volume, NBBO bid/ask, IV | structure, G1, G2 |
| **UW chain** | `/stock/{t}/greeks?expiry=` | per-strike delta | structure, POP, G9 |
| **UW feeds** | `option-trades/flow-alerts`, `screener/option-contracts`, `screener/stocks`, `market/oi-change`, `volatility/anomaly/top` | tickers | Tier-B discovery |
| **UW feeds** | `market/movers` | *(gated — UW Advanced)* | Tier-B (degrades) |
| **Robinhood** (MCP, agent-driven) | positions, quotes, greeks, orders | fills, live quotes, execution | journal reconcile, human confirm |

Auth: FMP `?apikey=`; UW `Authorization: Bearer` + `UW-CLIENT-API-ID: 100001`.
Every response is cached per-ticker per-scan.

---

## 3. Universe & discovery (two-tier)

- **Tier A** — curated list in `config.universe.tier_a`, scored every scan.
- **Tier B** — pulled per-scan from UW feeds (flow alerts, hottest chains,
  screener, OI change, vol anomalies), capped at ~25 nominees.
- **Cap tiers** (from market cap): `MEGA >$200B`, `LARGE $10–200B`,
  `MID $2–10B`, `SMALL $300M–2B`, `MICRO <$300M` (manual only). Drives G1/G3
  thresholds and sizing.

---

## 4. Thesis — formulas

Per candidate, from the signal snapshot:

**Direction.** Three votes in [−1, +1]:
```
prem_vote = clamp( (net_call_premium − net_put_premium) / 1_000_000 , −1, +1 )
tech_vote = mean of: (+1 if price ≥ MA50 else −1), (+1 if price ≥ MA200 else −1)
dp_vote   = (prints_above_mid − prints_below_mid) / total_prints
net_vote  = mean(non-zero votes)
direction = bullish if net_vote > 0.15 ; bearish if < −0.15 ; else neutral
```
⚠ **Review:** the `1_000_000` premium-normalization constant and the `0.15`
direction band are hand-set. On very high-premium names `prem_vote` saturates at
±1 quickly.

**Conviction** (0–1):
```
agreement = max(#positive, #negative) / #non-zero votes
conviction = min(1, |net_vote|·0.6 + agreement·0.4)
```

**Vol regime** (the pivot): `cheap` if IV-rank ≤ 30, `rich` if ≥ 50, else `fair`
(config `ivr_cheap_max` / `ivr_rich_min`). Fallback when IV-rank missing: IV vs
RV (cheap if IV < 0.9·RV, rich if IV > 1.2·RV).

**IV-vs-RV helper** (used in P1): `50 + (RV − IV)/RV · 100`, clamped 0–100
(>50 = IV cheap vs realized = buyer's edge).

**Catalyst / horizon.** Earnings if next earnings ≤ 14 days; else flow / technical
/ news. Horizon from days-to-catalyst: 0 → intraday, ≤10 → swing, ≤56 → position,
else LEAPS.

**Implied vs expected move.**
```
implied_move  = nearest non-0DTE term-structure implied_move_perc
expected_move = implied_move · (0.6 + 0.9·conviction)      # if implied available
              = (RV or IV) · 0.29 · (0.5 + conviction)     # fallback (~1-mo de-annualized)
```
⚠ **Review:** `expected_move` is a conviction-scaled proxy, not an independent
forecast — high conviction mechanically makes expected > implied, which then
rewards long premium. This is circular and a prime calibration target.

---

## 5. Structure selection — regime-first

Decision tree (`plan_structure`), thresholds `_STRONG = 0.6`, `_MODERATE = 0.35`:

| Regime | Condition | Structure |
|---|---|---|
| any | horizon = intraday | 0DTE defined-risk spread |
| any | earnings play, expected > implied | debit vertical |
| any | earnings play, expected < implied | credit vertical |
| cheap | neutral | iron condor |
| cheap | strong + swing, IVR < rich | long call/put |
| cheap | strong + swing, IVR ≥ rich | debit vertical (spread over naked) |
| cheap | LEAPS | deep-ITM LEAPS (~0.75Δ) |
| cheap | moderate | debit vertical |
| rich | neutral | iron condor |
| rich | directional (≥ moderate) | credit vertical |
| fair | directional | debit vertical |

**Real strikes** come from the live chain at the expiry nearest the horizon
(target DTE: intraday 0, swing 14, position 35, LEAPS 270). Premiums = NBBO mid.

**Geometry** (corrected): debit uses the trade-direction option type (bull call /
bear put); credit uses the opposite (bull *put* / bear *call*).

**Width fitting.** Among widths 1–8 strikes that keep 1-contract max-loss ≤ the
$500 ceiling, pick the **most liquid** (max of the least-liquid leg's OI), tie-
break wider. Per-point risk assumptions: credit ≈ $65/pt, debit ≈ $40/pt, condor
wing ≈ $70/pt.

**Long-premium reward:risk target** (for EV, since upside is unbounded):
`max_profit = 1.3 · risk` (LEAPS 1.5). ⚠ **Review:** these RR targets are priors.

---

## 6. Hard gates (any failure = PASS)

| Gate | Rule | Source |
|---|---|---|
| G1 | OI ≥ 500 **and** volume ≥ 100 on the chosen legs (×0.5 MID, ×0.25 SMALL) | live chain |
| G2 | bid/ask spread ≤ 10% of mid (≤ 5% for 0DTE) | live chain |
| G3 | underlying avg $-volume ≥ tier floor (MEGA 500M · LARGE 200M · MID 50M · SMALL 10M) | FMP |
| G4 | block long premium held through earnings unless it's the thesis | FMP earnings |
| G5 | 0DTE ≤ 3/week, defined-risk, top-liquidity | config/state |
| G6 | per-trade max-loss ≤ $500 ceiling | structure |
| G7 | open risk + new ≤ $2,000 **and** open positions < 6 | context |
| G8 | reject stale quotes/flow (weekend/holiday/halt) | timestamps |
| G9 | short leg ITM within 2 days of expiry → close-only | live chain |
| G10 | intraday margin deficit ≤ $250 (non-binding for defined-risk) | context |

Gates needing live-chain data (G2, G9) *defer* — surface for human confirm —
when no chain is available (offline/placeholder path).

---

## 7. Scoring — six pillars

Each pillar 0–100. `COMPOSITE = (25·P1 + 22·P2 + 20·P3 + 18·P4 + 10·P5 + 5·P6) / 100`.

**P1 · Volatility edge** (regime-conditional):
```
buying premium:  base = 100 − IVR ; blended 0.5·base + 0.5·IV_vs_RV
                 × 0.2 if regime is RICH        (mismatch → near-kill)
selling premium: if IVR < 50 → IVR · 0.4
                 else base = IVR ; blended 0.5·IVR + 0.5·(100 − IV_vs_RV)
                 × 0.3 if regime is CHEAP       (mismatch)
IVR missing → 40 (neutral prior)
```

**P2 · Directional signal:**
```
neutral thesis → 60 − |conviction|·20 + 20     (scores on stability)
else → clamp( conviction·100·0.7 + min(3, #supporting_signals)·8 )
```

**P3 · Expected value:** pre-pool `50 + (EV/risk)·70`; then **re-normalized
min-max across the day's pool** to 0–100 at the ranking stage.
```
POP (real, from chain deltas): credit → 1 − |short_delta| ; long/debit → |delta|
POP (heuristic, no chain):     credit 0.62 + 0.10·conviction (condor 0.65)
                               long   0.42 + 0.15·conviction ± 0.08 (exp vs implied)
EV = POP·max_profit − (1 − POP)·max_loss − 5      (the 5 = fee/slippage prior)
```
⚠ **Review:** POP heuristics (no-chain path) and the flat `$5` fee/slippage are
placeholders. Real slippage should come from the journal's taken-trade fills.

**P4 · Catalyst quality:** `reliability · proximity · 100`.
```
reliability: earnings .90 · fda .85 · macro .70 · news .55 · technical .50 · flow_only .45
proximity (days): <0 → .30 ; ≤5 → 1.0 ; ≤14 → .80 ; ≤45 → .55 ; else .35 ; none → .50
earnings play: +10 if expected > implied ; −15 if buying long premium & reverse
```
⚠ **Review:** reliability weights are pure priors.

**P5 · Liquidity/execution:** `50 + min(25, OI/5000·25) + min(25, vol/2000·25)`
from the best flow alert.

**P6 · Corroboration:** by count of independent agreeing signals →
`{1:20, 2:50, 3:75, 4+:100}`.

---

## 8. Market regime overlay (cross-asset risk-on/off)

Computed **once per scan** from ETF ratios + the yield curve.

| Component | Ratio | Weight | Risk-on when |
|---|---|---|---|
| Concentration | RSP/SPY | 0.25 | equal-weight leads |
| Yield curve | 10Y−2Y | 0.20 | positive / steepening |
| Credit | HYG/LQD | 0.15 | high-yield leads |
| Size | IWM/SPY | 0.15 | small-caps lead |
| Equity–bond | SPY/TLT | 0.15 | stocks lead |
| Sector | XLY/XLP | 0.10 | cyclicals lead |

```
component signal = 0.5·(ratio vs its SMA200) + 0.5·(SMA200 slope over 20 bars)  ∈ {−1,0,+1}
composite = Σ(signal·weight) / Σ(weight of available components)   , clamped [−1,+1]
macro score: ≥.5 → +2 ; ≥.2 → +1 ; >−.2 → 0 ; >−.5 → −1 ; else −2
inflationary flag: SPY-TLT return-corr > 0.25 AND equity-bond signal ≤ 0  → caps macro at −1
```
Missing components redistribute their weight. **Adjustment applied to each
thesis:**
```
regime_adj = thesis_dir · regime_dir · max_adj · min(1, |composite| / 0.5)
effective_composite = pillar_composite + regime_adj      (max_adj = 5; 0 = advisory-only)
```
A bullish thesis in a risk-off tape is docked; aligned is boosted.

*(Adapted from the MIT-licensed macro pillar in Oft3r/agentic-trading-desk.)*

---

## 9. Decision & sizing

```
GO   if effective_composite ≥ 72 AND all gates pass AND EV > 0
WATCH if effective_composite ≥ 58
PASS otherwise
```
Sizing (GO only):
```
fraction = min(1, (effective_composite − 72) / (100 − 72))
ceiling  = $500 if effective_composite ≥ 85 else $200      (top-decile high-conviction)
target   = 200 + fraction·(ceiling − 200)
contracts = floor(target / per_contract_risk) ; size = contracts · per_contract_risk
```
Bounded by G7 aggregate cap ($2,000 open risk, 6 positions).

---

## 10. Journal & calibration

**Shadow trade** logged when: decision = GO, **or** composite ≥ 72 & EV > 0 &
the only failing gates are G6/G7 (budget-blocked). **Taken trade** reconciled
from Robinhood fills.

**Resolution** (re-price exact legs against the live chain at horizon):
```
pnl = Σ_legs  sign·(mid_now − mid_entry)·100        (sign = +1 long leg, −1 short)
outcome = win if pnl > 5%·max_loss ; loss if < −5%·max_loss ; else scratch
```

**Calibration report:** Brier score `mean((POP − win)²)`; win-rate + avg PnL% by
composite bucket; win-rate by vol-regime × structure; avg slippage on taken
trades. At ≥ 100 resolved outcomes, the pillar weights can be re-fit by logistic
regression from *your* results.

---

## 11. Config knobs (all tunable in `config.yaml`)

`account`: size 5000 · risk_standard 200 · risk_high_conviction 500 · max_open
2000 · max_positions 6 · `budget.zerodte_per_week` 3 · `scoring.go_threshold`
72 · `watch_threshold` 58 · `weights` {25/22/20/18/10/5} · `structure`
ivr_cheap_max 30 / ivr_rich_min 50 · `gates` oi_min 500 / contract_vol_min 100 /
spread_max_pct 0.10 / 0.05 (0DTE) · `market_context` max_composite_adjustment 5 ·
`speculative_bucket` quality_bar 75.

---

## 12. ⚠ What to review — priors, placeholders, and gaps

**Priors most likely to need tuning (all in code/config today):**
1. **Pillar weights** 25/22/20/18/10/5 — the biggest single assumption; only the
   calibration loop can validate them.
2. **GO / WATCH thresholds** (72 / 58) and the **regime adjustment** (±5).
3. **POP heuristics** and the **$5 flat fee/slippage** — replace slippage with
   real fills from the journal.
4. **`expected_move`** being conviction-scaled off implied — circular; a real
   independent move forecast would be better.
5. **Catalyst reliability priors** (.90/.85/…/.45) and **P4 proximity** buckets.
6. **Direction band** (±0.15) and **premium normalization** ($1M) in the thesis.
7. **Long-premium RR targets** (1.3 / 1.5) and **per-point risk** width assumptions.

**Genuine gaps (not yet built):**
- **No backtest** — everything is forward-logged; we can't yet validate on
  history without waiting for outcomes to accrue.
- **Technicals are thin** — direction's technical vote is only price vs 50/200-day
  MA. (A richer TA stack — RSI/MACD/TRIX — is a candidate upgrade to P2.)
- **No position-management / exit engine** — the scanner grades *entries*; exits
  on held positions are done manually. (A holder-state exit cascade is a
  candidate build.)
- **Taken-trade auto-capture** depends on the Robinhood MCP (agent-driven);
  there's no headless reconcile.
- **Gate thresholds (G1 OI ≥ 500, G2 ≤ 10%)** may be strict for constructed
  spread legs — worth validating on live-market data.
- **Weights are global**, not per-cap-tier or per-structure; a MEGA credit spread
  and a SMALL long call are scored on the same curve.

---

*Not investment advice. Every GO is a hypothesis to validate in §10, not a signal
to trust blindly.*

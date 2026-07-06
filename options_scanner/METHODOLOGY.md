# Methodology — full technical reference

*Everything the engine actually computes: data sources, formulas, thresholds,
and the assumptions most worth reviewing. Grounded in the code, not the spec.
Recommend-only; a human confirms every order.*

> **How to read this:** every number here is a **tunable knob or a placeholder
> prior**, not a law. The "⚠ Review" callouts flag the ones most likely to need
> your judgment. The calibration loop (§14) exists to replace these priors with
> values fit from your own outcomes.
>
> **Updated** for the strategy-review builds: %-based sizing, cheap-vol fix,
> independent expected-move model, exit engine, flow-quality + technicals.

---

## 1. What the system does

On a bare `scan` it hunts the whole market for optionable setups, builds a
thesis and a concrete options structure for each, filters on hard rules, scores
six ways, applies a market-regime overlay, attaches an exit plan, and emits a
ranked **GO / WATCH / PASS** readout. The same pipeline also grades positions
you already hold.

**Core principle:** *vol regime decides buy-vs-sell before direction does.* Cheap
vol → buy premium; rich vol → sell premium. A great directional read in the
wrong regime scores near zero.

---

## 2. Data sources — exactly what comes from where

| Source | Endpoint | Fields we use | Feeds |
|---|---|---|---|
| **FMP** | `/stable/profile` | market cap, sector, avg volume | universe cap-tier, G3 |
| **FMP** | `/stable/quote` | price, volume, 50/200-day avg | thesis |
| **FMP** | `/stable/earnings` | next + past earnings dates | catalyst, G4, expected-move |
| **FMP** | `/stable/historical-price-eod/light` | dated daily closes | expected-move (RV), technicals, regime |
| **FMP** | `/stable/treasury-rates` | year10, year2 | regime yield curve |
| **UW** | `/stock/{t}/iv-rank` | `iv_rank_1y`, `volatility` (IV) | vol regime, P1 |
| **UW** | `/stock/{t}/volatility/realized` | implied vs realized vol | P1 (IV-vs-RV) |
| **UW** | `/stock/{t}/net-prem-ticks` | net call/put premium | direction fallback |
| **UW** | `/stock/{t}/flow-alerts` | type, **ask/bid-side prem, opening, sweep, multileg, vol/OI**, OI | **flow quality**, P5 |
| **UW** | `/darkpool/{t}` | prints vs NBBO midpoint | direction (dark-pool skew) |
| **UW** | `/stock/{t}/volatility/term-structure` | `implied_move_perc` by DTE | implied move |
| **UW** | `/stock/{t}/max-pain` | max-pain strike | context |
| **UW chain** | `/stock/{t}/option-contracts?expiry=` | per-strike OI, volume, NBBO, IV | structure, G1, G2 |
| **UW chain** | `/stock/{t}/greeks?expiry=` | per-strike delta | structure, POP, G9 |
| **UW feeds** | flow-alerts, option-contracts, screener/stocks, oi-change, anomaly/top | tickers | Tier-B discovery |
| **UW feeds** | `market/movers` | *(gated — UW Advanced)* | Tier-B (degrades) |
| **Robinhood** (MCP, agent-driven) | positions, quotes, greeks, orders | fills, live quotes, execution | journal reconcile, human confirm |

Auth: FMP `?apikey=`; UW `Authorization: Bearer` + `UW-CLIENT-API-ID: 100001`.
Cached per-ticker per-scan.

---

## 3. Universe & discovery (two-tier)

- **Tier A** — curated list in `config.universe.tier_a`, scored every scan.
- **Tier B** — pulled per-scan from UW feeds (flow alerts, hottest chains,
  screener, OI change, vol anomalies), ~25 nominees.
- **Cap tiers**: `MEGA >$200B`, `LARGE $10–200B`, `MID $2–10B`,
  `SMALL $300M–2B`, `MICRO <$300M` (manual only). Drives G1/G3 + sizing.

---

## 4. Thesis — formulas

**Direction.** A blend of three independent votes in [−1, +1]:
```
flow_vote  = quality-weighted options-flow read (§5); falls back to
             clamp((net_call_prem − net_put_prem)/1e6, −1, +1) when no alerts
tech_vote  = technical stack vote (§6)
dp_vote    = (dark-pool prints above mid − below mid) / total prints
net_vote   = mean(non-zero votes)
direction  = bullish if net_vote > 0.15 ; bearish if < −0.15 ; else neutral
```

**Conviction** (0–1), now with a late-entry penalty:
```
agreement  = max(#pos, #neg) / #non-zero votes
raw        = min(1, |net_vote|·0.6 + agreement·0.4)
conviction = raw · late_entry_penalty(technicals, direction)   (§6)
```

**Vol regime** (the pivot): `cheap` if IV-rank ≤ 30, `rich` if ≥ 50, else `fair`.
Fallback when IV-rank missing: IV vs RV.

**Catalyst / horizon.** Earnings if next earnings ≤ 14 days; else flow / technical
/ news. Horizon from days-to-catalyst: 0 → intraday, ≤10 → swing, ≤56 →
position, else LEAPS.

**Implied vs expected move.** Implied is sampled at the term-structure expiry
**nearest the thesis horizon** (so both cover ~the same days). Expected comes
from the independent model (§7). Long premium is favored only when expected
statistically exceeds implied.

---

## 5. Flow-quality model (`flow.py`)

Raw net premium is easy to misread (a big call buy could be a hedge, a spread
leg, or a close). Each UW flow alert is scored for **direction × quality**:
```
base       = +1 (call) / −1 (put)
net_aggr   = ask_side_prem − bid_side_prem      (>0 = bought aggressively)
directional= base · net_aggr                     (bullish if call-bought or put-sold)
weight     = 1.0 ·(×1.3 if all-opening)·(×1.2 if sweep)·(×0.6 if multi-leg)·(×1.15 if vol/OI>1)
vote       = clamp( Σ directional·weight / 2e6 , −1, +1 )
quality    = mean( opening-ratio, single-leg-ratio, decisive-ratio )   ∈ 0..1
```
The thesis discounts noisy flow: `flow_vote = vote · (0.5 + 0.5·quality)`.
⚠ **Review:** the $2M normalization and the weight multipliers are priors.

---

## 6. Technicals (`technicals.py`)

Deterministic stack on daily closes (adapted from the MIT engine in
Oft3r/agentic-trading-desk): **EMA 8/21/50/200**, EMA-200 slope, **RSI-14
(Wilder)**, **MACD histogram (12/26/9)**.
```
technical_vote = mean of ±1 for: price vs EMA21 · EMA8 vs EMA21 · EMA50 vs EMA200 ·
                 EMA200 slope · RSI (≥55 +1 / ≤45 −1) · MACD hist sign
late_entry_penalty: ×0.7 if ≥10% past EMA21 in the trade direction (×0.85 if ≥6%);
                    ×0.8 if RSI ≥75 (long) or ≤25 (short)
```
This penalizes buying calls after a vertical move into resistance even when the
thesis is bullish. ⚠ **Gap:** ATR/ADX not included (need OHLC; FMP light is
close-only).

---

## 7. Independent expected-move model (`expected_move.py`)

**Conviction-free** (fixes the old circular logic where confidence manufactured
a bigger expected move):
```
realized_vol(closes, window) = std(daily log returns) · sqrt(252)   (annualized)
statistical_move = RV_window · sqrt(dte/252)     window: 10d (≤10 DTE) / 20d / 60d
earnings move    = avg |overnight return| around the last ≤8 earnings dates
expected_move    = sqrt(event² + drift²)  for earnings plays ; else statistical_move
```
Compared honestly to the horizon-matched implied move (§4). ⚠ **Review:** the
window→horizon mapping and the earnings/drift combination are priors to
calibrate.

---

## 8. Structure selection — regime-first

Decision tree (`plan_structure`), thresholds `_STRONG = 0.6`, `_MODERATE = 0.35`:

| Regime | Condition | Structure |
|---|---|---|
| any | horizon = intraday | 0DTE defined-risk spread |
| any | earnings play + **directional**, expected > implied | debit vertical |
| any | earnings play + **directional**, expected < implied | credit vertical |
| **cheap** | **neutral + expansion catalyst** | **long straddle** |
| **cheap** | **neutral + no catalyst** | **PASS (no trade)** |
| cheap | strong + swing, IVR < rich | long call/put |
| cheap | strong + swing, IVR ≥ rich | debit vertical |
| cheap | LEAPS | deep-ITM LEAPS (~0.75Δ) |
| cheap | moderate | debit vertical |
| rich | neutral | iron condor |
| rich | directional (≥ moderate) | credit vertical |
| fair | directional | debit vertical |
| fair | neutral | iron condor |

Cheap-vol neutrals no longer sell premium via condor (poorly compensated) — they
buy a straddle if a move is expected, else pass. **Real strikes** from the live
chain at the expiry nearest the horizon; premiums = NBBO mid. Debit geometry uses
the trade-direction type; credit uses the opposite (bull put / bear call).
Width is the **most liquid** among widths that fit the risk cap. Long-premium /
straddle reward:risk target = 1.3× (LEAPS 1.5×). ⚠ Priors.

---

## 9. Hard gates (any failure = PASS)

| Gate | Rule | Source |
|---|---|---|
| G1 | OI ≥ 500 & volume ≥ 100 on chosen legs (×0.5 MID, ×0.25 SMALL) | live chain |
| G2 | bid/ask spread ≤ 10% of mid (≤ 5% for 0DTE) | live chain |
| G3 | underlying avg $-volume ≥ tier floor | FMP |
| G4 | block long premium held through earnings unless it's the thesis | FMP earnings |
| G5 | 0DTE ≤ 3/week, defined-risk, top-liquidity | config/state |
| G6 | per-trade max-loss ≤ high-conviction ceiling (8% = $400 @ $5k) | structure |
| G7 | open risk + new ≤ 30% ($1,500 @ $5k) **and** < 6 positions | context |
| G8 | reject stale quotes/flow | timestamps |
| G9 | short leg ITM within 2 days of expiry → close-only | live chain |
| G10 | intraday margin deficit ≤ $250 (non-binding for defined-risk) | context |
| **G11** | **no complete exit plan (target + stop + invalidation) → no trade** | exit engine (§13) |
| **G12** | **correlated (same-direction or same-sector) open risk + new ≤ 15% of account** | context / open positions |

Gates needing live-chain data (G2, G9) or open-position context (G12) *defer*
when that data isn't supplied.

---

## 10. Scoring — six pillars

Each 0–100. `COMPOSITE = (25·P1 + 22·P2 + 20·P3 + 18·P4 + 10·P5 + 5·P6) / 100`.

- **P1 · Volatility edge** (regime-conditional): buying → `100 − IVR` blended with
  IV-vs-RV, ×0.2 if regime is RICH (mismatch); selling → rises with IVR, ×0.3 if
  CHEAP. Straddle scored as buy-premium.
- **P2 · Directional signal:** `conviction·70 + min(3, #signals)·8` (neutral scores
  on stability).
- **P3 · Expected value:** `EV = POP·max_profit − (1−POP)·max_loss − $5`, then
  **min-max normalized across the day's pool**. POP is delta-based off the chain
  (`credit → 1 − |Δshort|`; `long/debit → |Δ|`), else a regime/conviction prior.
- **P4 · Catalyst quality:** `reliability · proximity · 100` (earnings .90 … flow_only
  .45); earnings bonus if expected > implied.
- **P5 · Liquidity:** from spread %, OI, volume.
- **P6 · Corroboration:** by # independent agreeing signals → `{1:20,2:50,3:75,4+:100}`.

⚠ **Review:** the weights, the $5 fee/slippage, POP heuristics, and catalyst
reliabilities are all priors.

---

## 11. Market regime overlay (cross-asset risk-on/off)

Once per scan from ETF ratios (RSP/SPY, HYG/LQD, IWM/SPY, SPY/TLT, XLY/XLP) +
the 10Y-2Y curve → composite [−1,+1], regime label, and a −2..+2 macro score.
```
regime_adj = thesis_dir · regime_dir · max_adj · min(1, |composite|/0.5)   (max_adj = 5)
effective_composite = pillar_composite + regime_adj
```
Bullish thesis in a risk-off tape is docked; aligned is boosted. *(Adapted from
Oft3r/agentic-trading-desk, MIT.)*

---

## 12. Decision & sizing (percentage-based)

```
GO   if effective_composite ≥ 72 AND all gates pass AND EV > 0
WATCH if effective_composite ≥ 58 ; else PASS
```
Sizing (GO only), as % of `account.size` (default $5k; repoint to real balance):
```
standard = 4% ($200) · high-conviction = 8% ($400, top-decile ≥85) ·
aggregate cap = 30% ($1,500) · positions ≤ 6 · speculative/0DTE = 3% ($150)
fraction = min(1, (effective_composite − 72)/(100 − 72))
target   = standard + fraction·(ceiling − standard)   ; contracts = floor(target / risk)
```
⚠ **Open item:** `account.size` is still $5,000 (paper) vs your real ~$1,400/$800
accounts — one number to change when ready.

---

## 13. Exit engine (`exits.py`)

Every tradeable structure gets a plan **before entry** (enforced by G11):

| Family | Profit target | Stop | Time / delta / event |
|---|---|---|---|
| long / debit | 50–60% of max profit | 40% of risk | time stop at ½ hold; exit before earnings; invalidate on breakeven breach / Δ<0.20 |
| credit / condor | 50% of credit | ~2× credit (≤ max loss) | roll if short Δ > 0.35; close before expiration |
| 0DTE | 50% | 50% | hard time stop; no averaging; one attempt |

Surfaced with every GO/WATCH. ⚠ Targets/stops are priors — but explicit and
consistent, and logged so the loop can tune them.

---

## 14. Journal & calibration

**Shadow trade** logged when: decision = GO, or composite ≥ 72 & EV > 0 & the only
failing gates are G6/G7. **Taken trade** reconciled from Robinhood fills.
**Resolution** re-prices the exact legs against the live chain:
```
pnl = Σ_legs sign·(mid_now − mid_entry)·100 ; outcome = win/loss/scratch (±5%·max_loss)
```
**Report:** Brier score on POP, win-rate + avg PnL by composite bucket, regime ×
structure audit, slippage. At ≥ 100 resolved outcomes the pillar weights can be
re-fit from your results.

---

## 15. Config knobs (all in `config.yaml`)

`account`: size 5000 · risk_standard_pct 4% · risk_high_conviction_pct 8% ·
speculative_pct 3% · max_open_pct 30% · max_correlated_pct 15% · max_positions 6 ·
`scoring.go_threshold` 72 · `watch_threshold` 58 · `weights` {25/22/20/18/10/5} ·
`structure` ivr_cheap_max 30 / ivr_rich_min 50 · `gates` oi_min 500 /
contract_vol_min 100 / spread_max_pct 0.10 / 0.05 (0DTE) ·
`market_context` max_composite_adjustment 5 · `speculative_bucket` quality_bar 75.

---

## 16. ⚠ What to review — priors, placeholders, and gaps

**Fixed since the last review (was flagged, now done):**
- ~~Circular expected move~~ → independent model (§7).
- ~~Cheap-vol iron condor~~ → straddle / no-trade (§8).
- ~~No exit engine~~ → §13 + G11.
- ~~Thin technicals~~ → RSI/MACD/EMA stack + late-entry penalty (§6).
- ~~Flow without quality~~ → quality-weighted flow (§5).
- ~~Aggressive fixed sizing~~ → %-based, less aggressive (§12).

**Priors still worth tuning:**
1. **Pillar weights** 25/22/20/18/10/5 — the biggest assumption; only calibration
   validates them.
2. **GO/WATCH thresholds** (72/58) and **regime adjustment** (±5).
3. **$5 flat fee/slippage** — replace with real fills from the journal.
4. **Catalyst reliability priors** and **exit targets/stops** (§13).
5. **Flow weights + $2M normalization** (§5); **expected-move windows** (§7).

**Genuine gaps (not yet built):**
- **No backtest** — everything is forward-logged; trust waits on ≥100 resolved
  shadow trades showing positive expectancy. *This is the real gate to live capital.*
- **Global weights** — a MEGA credit spread and a SMALL long call score on the same
  curve. Strategy-specific scoring is deferred until there's shadow data to fit it.
- **No *event*-clustering gate** — G12 covers direction/sector correlation, but
  positions clustered around the same catalyst date aren't yet checked.
- **Missing vol/market data** — VIX level, IV percentile, IV/HV, skew, VVIX, MOVE,
  breadth; and ATR/ADX (need OHLC). A selective subset is the next data add.
- **Taken-trade auto-capture** depends on the Robinhood MCP (agent-driven).
- **Account size** still $5,000 (paper) vs real balances.

---

*Not investment advice. Every GO is a hypothesis to validate in §14, not a signal
to trust blindly.*

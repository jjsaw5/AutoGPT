# Backlog — enhancements, tweaks & open decisions

*Living list of things to improve, decide, or revisit. Not committed work — a
parking lot so we don't lose sight. Add to it freely; move items to "Done" (or
just delete) as they ship. Priority is a rough guide, not a promise.*

> **Guiding principle (from the strategy review):** don't make the score fancier
> until it's proven. The single highest-value activity right now is **running the
> scanner on a cadence to accumulate resolved shadow trades** (target 100–300)
> so the "priors" below can be *calibrated from real outcomes* rather than
> hand-tuned. Feature-adds are secondary to that.

---

## 1. Open decisions (need a human call)

- [ ] **Account size.** Config `account.size` is **$5,000** (paper) but real
  tradeable balances are ~**$1,381** (Individual) / ~**$798** (Agentic). One knob
  flips all %-based sizing to reality. Deferred by choice — revisit before sizing
  anything live.
- [ ] **G1 volume floor.** `contract_vol_min: 100` per strike blocks otherwise-
  strong multi-leg names (TSM scored 90, blocked on G1 volume). Options: make G1
  OI-primary with a lower/￮ volume floor, or accept it as correct filtering.
  *Decision pending — don't loosen blindly (reviewer's caution).*

## 2. Enhancements — ready to build

- [ ] **Vol-surface data → P1** *(high value; adds priors).* IV **percentile**
  (vs IV rank), **IV/HV** ratio, **skew** (put vs call), **term-structure slope**.
  Improves the highest-weighted pillar. Needs UW endpoint verification.
- [ ] **Event-clustering gate (G13)** *(med).* Extension of G12: flag/limit
  positions clustered around the **same catalyst date** (e.g., three earnings
  plays all the same week).
- [ ] **ADX / ATR technicals** *(med).* Needs OHLC (switch some FMP calls from
  `historical-price-eod/light` to `/full`). Adds trend-strength + true-range.
- [ ] **More market-regime inputs** *(med).* VIX level, VIX term structure
  (contango/backwardation), breadth (% of S&P > 20/50/200-DMA), put/call ratio.
  Some (VVIX, MOVE, breadth) need sources we haven't wired and may cost.
- [ ] **Rate-limit call tally** *(low).* Log `FMP: N / UW: M calls` per scan so
  usage is visible against the dashboards.

## 3. Blocked on data (the calibration loop)

*These can't be done well until the journal has a real sample of resolved
outcomes. Accumulating shadow trades unblocks them.*

- [ ] **Strategy-specific scoring weights** — separate pillar weights per
  structure family (long premium vs credit vs condor vs 0DTE). Right now one
  global curve scores them all. Fit from outcomes, don't hand-set.
- [ ] **Backtest / historical validation** — the real gate to live capital. Needs
  historical flow/tape (UW Advanced tier) or accumulated forward outcomes.
- [ ] **Re-fit pillar weights** — logistic regression on ≥100 logged outcomes
  (spec §9b step 3) to replace the priors below.
- [ ] **Real slippage into EV** — feed fill-vs-mid from taken trades back into
  P3/EV (currently a flat $5 placeholder).

## 4. Priors to calibrate (once outcomes exist)

*Every value here is a hand-set prior. Listed so we know exactly what to tune.*

- [ ] Pillar weights `25/22/20/18/10/5`
- [ ] GO / WATCH thresholds `72 / 58`
- [ ] Market-regime composite adjustment `±5`
- [ ] Flat fee/slippage `$5`
- [ ] Catalyst reliability priors (earnings .90 … flow-only .45)
- [ ] Flow weights + `$2M` premium normalization; direction weights `1.5/1.0/1.0`
- [ ] Expected-move windows (10/20/60-day) + event/drift combination
- [ ] Long-premium reward:risk targets `1.3 / 1.5`
- [ ] Direction band `±0.15`; conviction thresholds `_STRONG 0.6 / _MODERATE 0.35`
- [ ] Exit-plan targets/stops (§13) and position-review score weights + the
  `0.5` close-conviction floor

## 5. Parked ideas (someday / maybe)

- [ ] **Headless taken-trade reconcile** — auto-capture fills without an
  interactive Robinhood session (currently agent-driven).
- [ ] **Multi-account-aware sizing & correlation** — G12 / risk caps across the
  Individual + Agentic books together, not one $5k account.
- [ ] **News / sentiment catalyst expansion** — analyst revisions, FDA, macro
  calendar, insider, short interest as scored catalyst inputs.
- [ ] **Separate speculative/meme model** — keep social-hype names out of the
  main model; score them in their own bucket.
- [ ] **Position-management as a first-class report/CLI** — run the grade+action
  review on the whole book on a schedule.

---

## Done (for reference)

Shipped this cycle — see `git log` for detail: cheap-vol condor fix, %-based
sizing, independent expected-move model, exit engine + G11, flow-quality +
technicals, market-regime overlay, entry-recommendation lines, position-review
(grades + actions), DKNG-audit refinements (driver labels, conviction-gated
close, flow-weighted direction, IVR ramp, agreement fix), G12 concentration
gate, rate-limit resilience.

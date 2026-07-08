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

- [x] **Account size / risk tolerance** *(decided — learning mode).* Keep
  `account.size` at **$5,000** (no capital added — nothing big enough greenlit
  yet) and instead **loosen the per-trade capital gate** via `max_trade_risk:
  500` (raises the G6 ceiling from the %-based $400 to a flat $500). Rationale:
  prioritize framework refinement + data collection over capital optimization;
  accept higher risk to let bigger setups GO and generate outcomes. **Narrow
  `max_trade_risk` as the model is dialed in.** (Real combined BP is ~$1,200 in
  two accounts — see the Level-3 consolidation note if/when trading larger.)
- [x] **G1 liquidity floor** *(decided — spread-primary).* The OI/vol depth
  floors were false-negativing demonstrably liquid names (NFLX OI 308/vol 159,
  PLTR OI 31/vol 19 — both with 1–5% spreads) because UW reports thin depth for
  liquid strikes. Fix: G1 now passes on the **truest liquidity signal — a tight
  bid/ask** (`liquid_spread_pct: 0.05`, a market maker quoting ≤5% proves the
  strike is tradeable), and the depth floors drop to sane backstops
  (`oi_min: 500→250`, `contract_vol_min: 100→50`) that only bite when the spread
  is *also* wide. Validated live: NFLX now clears all 12 gates (its WATCH is a
  pure score call, not a liquidity block); MSFT (vol 33, 8.6% spread) and META
  (21.5% spread) still correctly fail. *Note:* a multi-leg condor's `spread_pct`
  is the worst leg, so far-OTM wings can still gate a condor — correct behavior.

## 2. Enhancements — ready to build

- [x] **Scheduled sessions — scan half** *(shipped, pending enable).* GitHub
  Actions `scheduled-scan.yml` runs the scan 3×/weekday (DST-correct ET gate) +
  manual dispatch, persisting to Turso and publishing a digest to the run
  summary/artifact. Container-independent (runs on GitHub's infra).
  **To go live:** (a) the scanner must be the repo root — activates on the move
  to AI-Trade-Agent; (b) set the four Actions secrets (FMP/UW/Turso).
  *Follow-ups:* (1) active GO alerting to Slack/email (run summary is passive);
  (2) event-triggered runs (earnings/FOMC) from a catalyst calendar; (3) a
  Turso→JSONL export so scheduled-run history can backfill the git JSONL.
- [ ] **Winner + fading-thesis → take-profit** *(observed live).* TRIM only fires
  when `pnl_pct ≥ 0.40 AND aligned`. A big winner whose thesis has *faded to
  mixed/opposed* (not aligned) falls through to WATCH ("tighten stop") — which
  undersells it. DKNG at +42% with a C-grade fading thesis got WATCH, not a
  take-profit. Add a rule: deep-green (≥40%) + non-aligned thesis → TRIM/"bank
  it," not just watch.
- [x] **G1 gating liquid names early-session** *(fixed).* NFLX/AMD/BAC gated on
  G1 at 10:00 ET from thin early-session per-strike volume / UW volume gaps. The
  spread-primary G1 (see the resolved "G1 liquidity floor" decision above) fixes
  this — a tight bid/ask proves liquidity even when early-session depth is thin.
- [ ] **Confirmed-GO persistence rule** *(deferred — user said "not yet").* A GO
  counts as act-now only after persisting ≥2 consecutive sessions; a single-
  session GO shows as "provisional." Encodes the intraday-noise lesson. Small
  change to the decision logic + a lookback into history.

- [x] **Durable history → Turso** *(shipped).* Phase 1: append-only JSONL under
  `history/` (committed — the source of truth) + a rebuildable local SQLite query
  DB, backfilled with the runs to date. Phase 2: hosted **Turso** (libSQL/SQLite
  over the HTTP pipeline API via `requests`, so it clears this env's HTTPS-only
  egress proxy) behind the same `QueryDB` interface, with per-scan write-through
  and a `history sync` resync path. Provisioned; 233 rows + 6 manifests live.
  *Follow-ups:* (a) periodic/again-on-reconnect auto-sync if write-through fails
  repeatedly; (b) push calibration queries (Brier by bucket, win-rate by regime)
  to run server-side against Turso.
- [ ] **Graduate-to-Postgres trigger** *(someday).* If volume/concurrency
  outgrows SQLite/Turso, the monthly-JSONL layout `COPY`s straight into Postgres
  with no reshaping. Not needed at current volume — revisit if we add live
  dashboards or many writers.

- [ ] **Vol-surface data → P1** *(high value; adds priors).* IV **percentile**
  (vs IV rank), **IV/HV** ratio, **skew** (put vs call), **term-structure slope**.
  Improves the highest-weighted pillar. Needs UW endpoint verification.
- [x] **Catalyst engine — awareness layer** *(shipped).* CATALYST RADAR in the
  readout: upcoming earnings (reused from theses — no extra calls), curated
  macro (FOMC/CPI/NFP in `macro_calendar.yaml`), and computed OPEX; held names
  flagged as IV-crush risk. *Follow-ups:* (1) **ex-dividend dates** — needs a
  dividend feed (OPEX done, ex-div stubbed); (2) scheduled scan-only runs have
  no held set, so earnings show as opportunity-only there; (3) swap curated
  macro for the FMP economic-calendar API when wanted; (4) **earnings radar
  assumes held = long premium** — it labels an earnings catalyst on a held name
  "IV-crush risk on long premium," but a *short*-premium hold (credit spread /
  condor, `is_long_premium=false`) *benefits* from the post-earnings IV crush.
  Flip the framing by position: long premium → "IV-crush risk," short premium →
  "IV crush works for you; gap-through-short-strike is the risk." (Surfaced on
  the NFLX put credit spread, 7/7.)
- [x] **G12 auto-catches held names** *(shipped 7/8).* The session now feeds the
  held book into the scan as `open_exposure`, and G12 blocks any candidate on a
  name already held (`already hold <TICKER> — close/roll before stacking`).
  Stops the scanner re-proposing a position you already own (it was flagging a
  NFLX condor GO while we held the NFLX put spread). Held rows show `gate G12`;
  new-name GOs surface instead (BAC took NFLX's #1 slot once NFLX was blocked).
- [x] **Live P&L in the review** *(shipped 7/8).* `PositionInput` gained
  `pnl_asof`; the review marks any P&L **without** a timestamp as `*` stale
  ("entry value, not live — refresh before trusting the stop triggers"), since
  the CLOSE/stop logic keys off `pnl_pct`. The headless engine can't reach the
  Robinhood MCP, so the agent refreshes `pnl_pct`+`pnl_asof` from the live book
  before the review (per SESSION.md); a stale book is now loud, never silent.
- [x] **Catalyst engine — timing layer** *(shipped, pending enable).* GitHub
  Actions `event-scan.yml` runs one extra scan at ~2:15pm ET on FOMC decision
  days (the only intraday event the 3×/day baseline misses; CPI/NFP at 8:30am
  and earnings are already covered). FOMC dates from `macro_calendar.yaml`;
  gate requires FOMC-day AND the 2:15 window so it never collides with the
  regular pre-close run. Same activation/secrets as the scheduled scan.
- [ ] **Event-clustering gate (G13)** *(med).* Extension of G12: flag/limit
  positions clustered around the **same catalyst date** (e.g., three earnings
  plays all the same week). The radar now provides the event dates to cluster on.
- [ ] **ADX / ATR technicals** *(med).* Needs OHLC (switch some FMP calls from
  `historical-price-eod/light` to `/full`). Adds trend-strength + true-range.
- [ ] **More market-regime inputs** *(med).* VIX level, VIX term structure
  (contango/backwardation), breadth (% of S&P > 20/50/200-DMA), put/call ratio.
  Some (VVIX, MOVE, breadth) need sources we haven't wired and may cost.
- [ ] **Rate-limit call tally** *(low).* Log `FMP: N / UW: M calls` per scan so
  usage is visible against the dashboards.

- [x] **Robinhood confirmation layer** *(shipped).* `confirm.py` re-prices an
  actionable candidate's exact legs on live Robinhood quotes and returns a
  verdict — CONFIRMED / DEGRADED / REJECTED — on real cost, reward:risk, EV, and
  liquidity. Agent-gated (I pull the quotes via MCP, like the book review), so
  it runs on GO/near-GO candidates in interactive sessions, not headless CI.
  Validated live: NFLX GO confirmed ($380cr/$220 risk, EV +$63). *Follow-ups:*
  (1) auto-run it on the top-N candidates as a standard session section;
  (2) persist confirmations to history/Turso alongside candidates.

- [x] **Review-an-external-play tool** *(shipped).* `review_external.py` +
  `cli review` critique a posted/online options book through our framework —
  structure (naked vs defined), direction/premium concentration, correlation
  cluster (G12), near-dated theta, lottery flags — with a verdict and "what
  we'd do instead." Structural read is data-free; IV-fit/EV/catalyst scoring is
  a follow-up (run the tickers through the scanner). See REVIEW.md.

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
- [x] **Position-management as a first-class report/CLI** *(shipped).* The
  `session` command + SESSION.md runbook run scan + live-book review + journal +
  durable history in one operation; reviews persist to `position_reviews`
  (JSONL + SQLite + Turso), tracked over time like candidate scores. *Follow-up:*
  scheduled/autonomous sessions (blocked on the human-gated Robinhood pull for
  the review stage — scan-only can run unattended).

---

## Done (for reference)

Shipped this cycle — see `git log` for detail: cheap-vol condor fix, %-based
sizing, independent expected-move model, exit engine + G11, flow-quality +
technicals, market-regime overlay, entry-recommendation lines, position-review
(grades + actions), DKNG-audit refinements (driver labels, conviction-gated
close, flow-weighted direction, IVR ramp, agreement fix), G12 concentration
gate, rate-limit resilience.

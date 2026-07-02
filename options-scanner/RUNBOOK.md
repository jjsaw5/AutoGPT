# Put/Call Options Scanner — Runbook

Risk-first, defined-risk options scanner for the Robinhood agentic account.
Buys single-leg PUTS on weak stocks (live-tradeable) and ranks CALLS on strong
stocks (scan-only). Default answer is NO TRADE.

## Files
- `scanner.py`       — Stage-1 engine. `python3 scanner.py [put|call|both]`.
                       Computes 50/200-DMA, RSI, rel-strength vs SPY, MACD, ADX,
                       20d/52wk hi-lo, HV-based ticket estimates. PUT=weakness,
                       CALL=strength (with RSI>80 overbought veto). Resilient:
                       retries 402/429/5xx; falls back to a curated liquid
                       universe if the FMP screener is throttled.
- `earnings_exit.py` — Pre-earnings TIME-STOP planner. `python3 earnings_exit.py [SYMS...]`.
                       Buy the liquid monthly, but auto-exit EXIT_LEAD days before
                       earnings. Verdicts: CLEAN / TIME-STOP / BLOCK.
- `override_config.md`— Logged rails, overrides, sizing, exits. SOURCE OF TRUTH.
- `positions.md`     — Open positions + their monitored exits. UPDATE on every fill.

## Prereqs
- Env var `FMP_API_KEY` set (Financial Modeling Prep, /stable API).
- Robinhood MCP connected, agentic account ••2861 (992952861), option_level_2.
- Regular market hours only (9:30-16:00 ET).

## Routine (run order)
0. DATA HYGIENE (every run): append any live ATM IVs you pull to iv_history.csv
   (building our own IV-rank series — the plan has no historical IV). On every
   position OPEN or CLOSE, append a row to journal.csv with the gate values at
   entry (score, RSI, delta, IV, spread, OI, regime, sector) — the feedback loop.
1. HOURS check — abort if market closed.
2. MANAGE OPEN POSITIONS FIRST (see positions.md):
   - Verify each resting GTC take-profit is still working.
   - Check each PREMIUM STOP-LOSS: close any long option whose mark <= 50% of
     entry debit (monitored — per-position stop levels are in positions.md).
   - Check each TIME-STOP date — close on/before it (date-based, monitored;
     a resting order cannot enforce this).
   - Check each thesis exit (PUT: stock reclaims 50-DMA / CALL: loses 50-DMA).
3. Account — get_accounts + get_portfolio (live BP); count open puts (MAX_OPEN 5),
   new puts today (DAILY_CAP 3).
4. Stage 1 — `scanner.py both` -> ranked weakness/strength + HV EST$ tickets.
   The banner prints the MARKET REGIME (SPY vs its 50/200-DMA). REGIME GATE:
   new COUNTER-TREND entries only while that side's total open premium is under
   50% of its sleeve ($200 of $400); open positions grandfathered but count.
   With-trend side keeps the full cap. (UPTREND -> puts are counter-trend.)
   Each run auto-appends a dated snapshot to scan_history.jsonl (backtest data).
5. Earnings — `earnings_exit.py` on affordable candidates -> CLEAN/TIME-STOP/BLOCK.
6. Live gates on survivors' chosen (liquid monthly) expiry: delta band, OI>=500,
   spread<=10% of mid, IV-rank<=70 (elevated+unverifiable IV = flag, don't bless).
7. Safety wrapper (PUTS only): APPROVE iff all gates pass AND debit <= RISK_PER_TRADE
   AND open-put premium <= min(sleeve cap, live BP) AND conviction not marginal.
   Limit only, <= mid*1.02 (no chasing).
8. If APPROVED: liquidate-to-fund if needed (NOTE: cash account — stock proceeds
   settle T+1 and are NOT spendable for options same day; deposit or wait) ->
   review_option_order -> place_option_order (buy_to_open) -> confirm REAL fill via
   get_option_orders -> rest GTC sell_to_close at +100% -> append to positions.md
   with the TIME-STOP date.
9. CALLS: gates for REPORTING ONLY; never place.

## Hard rails (see override_config.md for current values + logged overrides)
limit-only (<= mid*1.02), delta PUT [-0.65,-0.45]/CALL [+0.45,+0.65] nearest 0.55,
OI>=500, spread<=10% of mid, IV-rank<=70, earnings time-stop, DAILY_CAP 3,
MAX_OPEN 5, regular hours, deterministic safety wrapper = only door to a fill,
fill-truth via get_option_orders. Overriding any cap needs explicit written
user instruction (log it + state the risk).
Risk upgrades (2026-07-01): RSI entry vetoes (puts: reject RSI<30 oversold;
calls: reject RSI>80 overbought), PREMIUM STOP-LOSS -50% of debit (monitored
every run), CONCENTRATION CAP (max 2 same-direction positions per sector /
non-US country — scanner prints sector/country per candidate).

## Known gotchas
- FMP plan: some symbols 402 (uncovered); SMA/RSI endpoints 402 (we compute from
  raw EOD instead); heavy use -> 429 (retry/backoff; use cached dates).
- Cash-account T+1 settlement blocks same-day option buys funded by stock sales.
- Options tick: $0.01 below $3.00, $0.05 at/above $3.00.
- Scheduled/headless sessions may lack an interactively-authenticated Robinhood
  MCP -> can scan (FMP) but not trade. Verify after first scheduled run.

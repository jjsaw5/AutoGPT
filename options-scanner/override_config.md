# DIRECTIONAL OPTIONS SCANNER — CONFIG & OVERRIDES (logged)
Updated: 2026-06-26 ~10:0x ET. Account: Agentic ••2861 (992952861), cash, option_level_2.

## DIRECTIONS
- PUT side  (weakness scan): LIVE-TRADEABLE via safety wrapper.
- CALL side (strength scan): LIVE-TRADEABLE as of 2026-07-01 (user override — flipped from
  scan-only; overrides the original "never calls" rail). First call: KDP $33 8/21.
  Separate CALL_SLEEVE_CAP = $400. Rationale: bullish calls diversify the all-bearish put book.

## SIZING / CAPS  (user instruction)
- RISK_PER_TRADE = $500 (max loss on a single option = debit paid). RAISED from
  $350, user override 2026-07-02, to unblock the qualifying CVS $105 call (~$453 —
  passed every other gate). Risk stated: one position can now lose up to ~$500,
  roughly 60% of the ~$840 account — a large single-bet ceiling at this size.
- PUT_SLEEVE_CAP  = $400   (separate)
- CALL_SLEEVE_CAP = $600   (RAISED from $400, user override 2026-07-01: "don't
  want to be restricted on good plays; I can add more." Risk stated: $600 calls +
  $400 puts = $1000 potential premium vs ~$840 account — BP floor still binds
  actual spend; calls are with-trend under the current UPTREND regime.)
- HARD FLOOR: every order also bounded by live buying power. TODAY account ~$370
  total, so real ceiling is BP (~$366 if fully liquidated), NOT the $400 caps.
  Separate $350-400 caps only become fundable at the planned $2,000 deposit
  (then ~$800 options max ≈ 40% of account).
- DTE window = 30-60.
- LIQUIDATION: sell equity to fund ONLY when a PUT trade is APPROVED (scan-first).

## RAILS STILL ENFORCED (both directions)
limit-only (<= mid x1.02), OI>=500, spread<=10% of mid, IV-rank<=70,
DAILY_CAP=3, MAX_OPEN=5, regular hours only, deterministic safety wrapper is the
only door to a fill, fill-truth via get_option_orders.
Delta band: PUT [-0.65,-0.45] nearest -0.55 ; CALL [+0.45,+0.65] nearest +0.55.

## RISK UPGRADES (added 2026-07-01 after first-week assessment)
1) PREMIUM STOP-LOSS: close any long option at -50% of entry debit (MONITORED at
   every run — a resting order can't do OCO here). Rationale: the 50-DMA thesis
   exit sits 10%+ away for deep-below-DMA entries, so BILI bled -31% with no rule
   ever triggering. The loss side now has a hard premium-based line.
2) OVERSOLD VETO (puts): REJECT new puts when underlying RSI14 < 30 — deep-oversold
   names are bounce-prone (every put we bought bounced within days). Mirrors the
   call side's RSI>80 overbought veto. The old RSI<30 score BONUS was removed
   (it rewarded exactly the wrong thing).
3) CONCENTRATION CAP: max 2 same-direction open positions per SECTOR, and max 2
   per non-US COUNTRY. Rationale: NIO+JD+BILI were "three tickers, one China bet."
   NIO+JD (China, bearish) = 2/2 grandfathered AT CAP — no new China-bearish adds
   until one closes. Scanner now prints sector/country per candidate (FMP profile).
4) MARKET REGIME GATE: scanner computes SPY vs its 50/200-DMA each run.
   UPTREND (SPY above both) -> puts are counter-trend: NEW put entries allowed only
   while total open-put premium < 50% of the put sleeve ($200 of $400); open
   positions grandfathered but count toward it. DOWNTREND -> mirror for calls.
   MIXED -> no restriction. Rationale: week one deployed 3-4 puts into a +14% tape.
   STATUS at install: UPTREND + put sleeve $325 -> NEW PUTS BLOCKED until puts < $200.
5) FEEDBACK LOOP (data): journal.csv (every open/close with gate values at entry),
   iv_history.csv (every live ATM IV observed — builds our own IV-rank series; the
   IV-rank<=70 rail has been unverifiable until this accrues ~30 days of data),
   scan_history.jsonl (auto-appended dated snapshot of each scan's top 15/side).

## EARNINGS = PRE-ER TIME-STOP (replaces "block if expiry crosses ER")
Engine: scratchpad/earnings_exit.py. Principle unchanged: NEVER hold a long
option through earnings (IV crush; buyer is on wrong side of the vol premium).
Implementation changed: decouple expiry (liquidity) from holding period.
  - Buy the LIQUID monthly expiry in the 30-60 DTE window (best OI/spread).
  - Set a MONITORED time-stop EXIT = earnings_date - 2 days. Close at/by then.
  - Knobs: EXIT_LEAD=2d, MIN_RUNWAY=21d (today->exit; raised from 14), ENTRY_BUFFER=5d.
  - Verdicts: CLEAN (ER after window) | TIME-STOP (use monthly + dated exit) |
    BLOCK (ER inside entry buffer, runway<14d, or ER date missing=never guess).
  - This unlocks liquid monthlies (e.g. BILI 8/21 OI 4089, exit 8/18) that the
    old block-on-cross rule killed.
NOTE: MIN_RUNWAY=21 now BLOCKS BAC (16d runway). Names need ER >=23d out to qualify.

## EXITS (per open position)
1) Take-profit: resting GTC sell_to_close at +100% (price-based).
2) Thesis exit: PUT -> stock reclaims 50-DMA / CALL -> stock loses 50-DMA (monitored).
3) TIME-STOP exit: close on/before the pre-ER exit date (monitored, DATE-based —
   a resting order can't enforce this; must be actively closed before ER).
4) PREMIUM STOP-LOSS (added 2026-07-01): close at -50% of entry debit (monitored
   at every run). Per-position stop levels are listed in positions.md.

## ENGINE
scratchpad/scanner.py  ->  python3 scanner.py [put|call|both]
  Shared indicators: SMA50/200, RSI14, 63d return, rel-vs-SPY, 20d/52wk hi-lo,
  MACD vs signal, ADX. PUT=weakness score; CALL=strength score with RSI>80
  overbought VETO + 20d-breakout. Resilient: get() retries 402/429/5xx; universe
  falls back to curated liquid-optionable list if FMP screener throttles.
Outputs ranked_dir.json {puts:[...], calls:[...]}.

## FUNDING PLAN
Target deposit ~$2,000 (not yet funded). Until then operate on ~$400 initial;
expect most scans = NO TRADE on buying power.

# DIRECTIONAL OPTIONS SCANNER — CONFIG & OVERRIDES (logged)
Updated: 2026-06-26 ~10:0x ET. Account: Agentic ••2861 (992952861), cash, option_level_2.

## DIRECTIONS
- PUT side  (weakness scan): LIVE-TRADEABLE via safety wrapper.
- CALL side (strength scan): SCAN-ONLY — wrapper must REFUSE to place call orders.
  (Overrides original "never calls" rail only for SCANNING, not execution.)

## SIZING / CAPS  (user instruction)
- RISK_PER_TRADE = $350 (max loss on a single option = debit paid).
- PUT_SLEEVE_CAP  = $400   (separate)
- CALL_SLEEVE_CAP = $400   (separate, but moot while scan-only)
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

# OPEN POSITIONS — Agentic ••2861 (992952861)

## BILI long put  [OPENED 2026-06-26]
- Contract: BILI 2026-08-21 $17.00 PUT (long_put)
- Qty: 1 | Fill: $1.73 | Cost: $173.04 incl $0.04 fees | MAX LOSS = $173.04
- Open order id: 6a3ea163-5eeb-497c-b325-176917f30328  (filled)
- option_id: 9a037e8d-4023-43b2-8469-ded35ca1e249
- Thesis: BILI weak (below 50/200-DMA, death cross, neg rel-strength, support break).
- Entry overrides (user, logged): spread gate (~10%) + IV-rank-unverifiable waived.
### EXITS
1. TAKE-PROFIT (resting): GTC sell_to_close @ $3.45 (+99%) — order 6a3ea1a5-1220-45ba-8e80-ed657f8634b0
2. TIME-STOP (MONITORED, DATE-BASED): CLOSE ON/BEFORE 2026-08-18 (2d before ER 8/20).
   A resting order CANNOT enforce this; must be actively closed.
3. THESIS EXIT: close if BILI reclaims its 50-DMA (~$19.5).

## NIO long put  [OPENED 2026-06-29 — user/agentic, NOT from scanner]
- Contract: NIO 2026-08-21 $5.00 PUT (long_put)
- Qty: 1 | Cost: $48 ($0.48) | MAX LOSS = $48
- option_id: ffc7ecae-a907-4d12-a444-4475ca3c8db0
- Thesis: NIO weak — -11.7% vs 50-DMA, -13.2% vs 200-DMA, death cross, RSI 42,
  rel -26.6% vs SPY. Valid weakness setup (missed scanner top-12 cutoff only).
- Gates: delta -0.444 (ATM, a hair shallow), OI 24,328, spread 7.1%, IV 59%. Earnings CLEAN.
- Breakeven: NIO < $4.57 by expiry. Currently ~$42.50 (-$5.50 / -11%).
### EXITS
1. TAKE-PROFIT (resting): GTC sell_to_close @ $0.96 (+100%) — order 6a428fcf-9591-462b-a56b-e3bb2b6aa207
2. NO TIME-STOP — earnings CLEAN (ER 9/1, after 8/21 expiry).
3. THESIS EXIT: close if NIO reclaims 50-DMA (~$5.68).

## JD long put  [OPENED 2026-06-30 — scanner, clean no-override entry]
- Contract: JD 2026-08-21 $26.00 PUT (long_put)
- Qty: 1 | Fill: $1.78 | Cost: $178.04 incl fees | MAX LOSS = $178.04
- Open order id: 6a43dcb8-7854-4417-be8c-17cfb5e152d1 (filled, settle 7/1)
- option_id: 99e44e8d-bd0d-4440-91fb-addef7f24653
- Thesis: JD weak (death cross, below DMAs, neg rel-strength). Score 12.54.
- Gates: delta -0.515, OI 1481, spread 2.8%, IV 40%. NO overrides needed (cleanest entry yet).
### EXITS
1. TAKE-PROFIT (resting): GTC sell_to_close @ $3.55 (+100%) — order 6a43dcce-18bf-44f8-a041-c1a7bd759116
2. TIME-STOP (MONITORED, DATE): CLOSE ON/BEFORE 2026-08-11 (2d before ER 8/13).
3. THESIS EXIT: close if JD reclaims 50-DMA.

## CAP USAGE
- Open puts: 3 / 5 (MAX_OPEN). New today: 1 / 3.
- PUT sleeve used: BILI $173 + NIO $48 + JD $178 = $399 / $400  ->  ROOM = ~$1 (MAXED).
- Sleeve effectively FULL — no further puts until one closes.

## REMAINING EQUITY (not liquidated): MRK, MA, JPM, V, KO, AMD

## CANCELLED (not filled)
- CPRT 2026-08-21 $30 PUT, limit $2.15 (order 6a43d702-...) — CANCELLED 2026-06-30,
  0 filled. Reason: would have breached the $400 put sleeve ($221+$215=$436), entry
  drifted (delta -0.69, chase to ~$2.30), ~73% concentration. Not worth chasing.
  Sleeve stays $221/$400 (BILI+NIO). Watch for a cleaner candidate <= ~$179.

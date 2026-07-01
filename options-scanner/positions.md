# OPEN POSITIONS — Agentic ••2861 (992952861)

## NIO long put  [OPENED 2026-06-29 — user/agentic, NOT from scanner]
- Contract: NIO 2026-08-21 $5.00 PUT (long_put)
- Qty: 1 | Cost: $48 ($0.48) | MAX LOSS = $48
- option_id: ffc7ecae-a907-4d12-a444-4475ca3c8db0
- Thesis: NIO weak — below 50/200-DMA, death cross, rel -26.6% vs SPY.
### EXITS
1. TAKE-PROFIT (resting): GTC sell_to_close @ $0.96 (+100%) — order 6a428fcf-9591-462b-a56b-e3bb2b6aa207
2. NO TIME-STOP — earnings CLEAN (ER 9/1).
3. THESIS EXIT: close if NIO reclaims 50-DMA (~$5.68).

## JD long put  [OPENED 2026-06-30 — scanner, clean no-override entry]
- Contract: JD 2026-08-21 $26.00 PUT (long_put)
- Qty: 1 | Fill: $1.78 | Cost: $178.04 incl fees | MAX LOSS = $178.04
- option_id: 99e44e8d-bd0d-4440-91fb-addef7f24653
- Thesis: JD weak (death cross, below DMAs, neg rel-strength). Score 12.54.
- Gates: delta -0.515, OI 1481, spread 2.8%, IV 40%. No overrides.
### EXITS
1. TAKE-PROFIT (resting): GTC sell_to_close @ $3.55 (+100%) — order 6a43dcce-18bf-44f8-a041-c1a7bd759116
2. TIME-STOP (MONITORED, DATE): CLOSE ON/BEFORE 2026-08-11 (2d before ER 8/13).
3. THESIS EXIT: close if JD reclaims 50-DMA (WATCH — JD +3.2% on 7/1, closing on it).

## PFE long put  [OPENED 2026-07-01 — scanner, clean no-override entry]
- Contract: PFE 2026-08-21 $24.00 PUT (long_put)
- Qty: 1 | Fill: $0.99 | Cost: $99.04 incl fees | MAX LOSS = $99.04
- option_id: 276f2ded-2a90-457a-bec3-eedb4caa006a
- Thesis: PFE weak (below DMAs, death cross). Score 11.1. Pharma — diversifies bearish sleeve.
- Gates: delta -0.474, OI 14,112, spread 2.0%, IV 28% (cleanest entry yet). No overrides.
### EXITS
1. TAKE-PROFIT (resting): GTC sell_to_close @ $1.98 (+100%) — order 6a453165-0766-40e4-9c9e-3b4e522439cb
2. TIME-STOP (MONITORED, DATE): CLOSE ON/BEFORE 2026-08-02 (2d before ER 8/4).
3. THESIS EXIT: close if PFE reclaims 50-DMA (~$25.8).

## CAP USAGE
- Open puts: 3 / 5 (MAX_OPEN).
- PUT sleeve used: NIO $48 + JD $178 + PFE $99 = $325 / $400  ->  ROOM = ~$75.
- BP: $370 settled (+$119 pending from BILI trade, clears ~7/2). Sleeve (not BP) is the binding limit.
- NOTE: account grew to ~$846 via deposits; $400 sleeve cap now ~47% of account. Consider
  a deliberate cap resize if scaling up (discussed, not yet changed).

## REMAINING EQUITY (not liquidated): MRK, MA, JPM, V, KO, AMD

## CLOSED / CANCELLED
- BILI 2026-08-21 $17 PUT — CLOSED 2026-07-01 @ $1.20 (sell order 6a452e66-2a6b-4679-b478-7c73cebf236e).
  Bought $1.73 (6/26), sold $1.20. REALIZED P&L = -$53.04 (-31%). Reason: TRIMMED for
  risk/concentration — worst performer (-27%), underlying +8% against thesis over 5 days,
  delta decayed to -0.40. Cut to de-risk the 3-put bearish book.
- CPRT 2026-08-21 $30 PUT — CANCELLED 2026-06-30, 0 filled (would have breached sleeve + chase).

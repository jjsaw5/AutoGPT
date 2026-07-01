# Execution — Order Mechanics

Reference detail for SKILL.md §6 (cash-aware profit-recovery) and §8 (stop/risk monitoring).
Robinhood MCP tools referenced below (`place_equity_order`, `review_equity_order`,
`get_equity_orders`, `cancel_equity_order`) are provided by the connected Robinhood MCP server.

## Whole-share vs. fractional positions

Robinhood GTC stop orders only work on whole shares. This forces two different mechanics:

**Whole-share positions**
- Protective stop: a real resting GTC stop order on the broker. Ratchet it UP each scan as the
  position gains (never down — SKILL.md §8). Cancel + replace to move it; never just leave a
  stale one behind and hope it's still right.
- Take-profit: NOT a resting order. It's a MONITORED level — each scan, if price >= the target,
  place a marketable limit sell for the partial (~40%) immediately. This avoids resting two
  conflicting orders (a stop and a limit) on the same shares.

**Fractional positions**
- Protective stop: MONITORED, not resting (Robinhood doesn't support stops on fractional shares).
  Each scan, if price <= the stop level, place a protective marketable-limit (or market, if no
  reasonable limit fills) sell immediately.
- Take-profit: a resting LIMIT order at the target price is fine for fractional shares and can be
  left resting between scans — verify each scan that it hasn't been duplicated and still reflects
  the current target.

## Marketable limits (the default sell mechanism)

When a monitored condition fires (target hit, stop breached), place a limit order priced to fill
immediately: at or just below the current bid for a sell. This gets stop-like execution speed
while still going through `review_equity_order` first (a bare market order in a fast-moving name
can get an ugly fill; a marketable limit just inside the spread is the safer default).

## Ladders

For a resting fractional take-profit or a multi-unit pyramid entry, prefer a small ladder of
limit orders over one large one when the position size is big relative to typical volume — e.g.
split a partial into 2-3 limits a few cents apart rather than one order that has to walk the book.
Not needed for typical position sizes on liquid, trend-template-passing names; use judgment based
on `avgDollarVol20` from `fmp.py indicators`.

## Order lifecycle discipline

1. **Review before placing.** Every order — buy or sell — goes through `review_equity_order`
   first. If it returns a warning (unusual price, odd lot, market-hours issue, anything), do not
   place it; log the warning and alert instead of forcing it through.
2. **Never infer a fill.** An order is filled only when `get_equity_orders` shows
   `state:"filled"` or `cumulative_quantity>0` for it. A "placed" order is not a fill.
3. **Reconcile every scan.** Before deciding anything about buying power or position state, pull
   `get_equity_orders` and reconcile every resting order (filled? partially filled? still open?
   cancelled?) against what the last scan expected.
4. **Freed capital is real only when cash rises.** A sell-limit resting on the broker is NOT
   spendable buying power, no matter how likely it is to fill. Only `get_portfolio` showing cash
   actually higher counts (SKILL.md §6 / §2 step 10).
5. **No duplicate orders.** Before placing any new order, check `get_equity_orders` for an
   existing open order on the same symbol/side that would double up.
6. **Record everything.** Every placed buy: `ops.py buy-record '<json>'` (for the daily cap).
   Every fully closed position: `ops.py ledger-add '<json>'` with the realized outcome (for the
   consecutive-loss breaker and the performance readout).

## Sizing recap (SKILL.md §7)

Whole shares only on new entries (>=2 shares) so a protective stop can actually rest. Size at the
lesser of the dollar cap and the equity percentage cap (both CUSTOMIZE values in SKILL.md §0/§7).
If 2 whole shares don't fit the cap, either pick a lower-priced trend-template-passing equivalent
or skip the trade — never round down to 1 share just to force an entry, and never buy on margin
or with unsettled funds.

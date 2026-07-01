---
name: genesis-quick-check
description: Lightweight Genesis position watcher — :00/:15/:30 past the hour, 9:30a–3:30p ET Mon–Fri. Catches profit targets & stop breaches between full scans. Sells only, never buys.
---

Cron: `0,15,30 9-15 * * 1-5` (at :00/:15/:30 past the hour, between the full scans).

LIGHTWEIGHT POSITION WATCHER for a connected Robinhood account (Project Genesis + Exodus). NOT a full
scan. Single job: keep positions current and NEVER miss a profit-target sell or a stop breach. NO buy
discovery, NO screener/movers/indicators, NO regime deep-dive, NO long report. Speed and safety only.

MODE — match your SKILL.md flags. You MAY place protective SELL orders autonomously (profit partials +
stop exits) — selling needs no buying power. NEVER place a BUY in this task. Put any action in a
1-sentence plain-language note. If nothing is at a target or stop, the correct result is "no action."

ACCOUNT: Robinhood MCP. `get_accounts` -> use the account with agentic_allowed=true. Missing/unreadable
data or unclear order status -> "ACCOUNT ACCESS ERROR — no action" and stop. Never trade on unclear data.

TRADING HOURS (ET): if market is closed/holiday/weekend/pre-open (before 9:30 AM), read-only check ->
"market closed/pre-open — monitor only" and stop. Sells only during regular hours 9:30 AM–4:00 PM;
never at/after 4:00 PM.

KILL-SWITCH: `python3 .../scripts/ops.py status`. If halt=true, place RISK-REDUCING stop exits ONLY and
skip profit-taking; report and stop. If halt=false, do both.

PROCEDURE (fast):
1. get_portfolio, get_equity_positions, get_equity_orders (resting/open).
2. get_equity_quotes for EVERY held symbol.
3. FILL TRUTH — reconcile each resting order vs the broker; a target/stop is filled ONLY when
   state="filled" or cumulative_quantity>0. If a position fully closed, append via `ops.py ledger-add`.
4. For each position compute % vs average_buy_price. First profit target = +10%.
5. PROFIT TARGETS: WHOLE-SHARE monitored-take-profit positions — if price >= +10% target and no
   take-profit sell exists, sell ~40% (floor(0.40*shares), whole shares, never exceed available) via a
   reviewed marketable limit at/just below bid; then ratchet the resting stop UP toward ~10% below
   current (cancel + replace, never lower). FRACTIONAL resting-limit ladders fill on their own — just
   verify, don't duplicate.
6. STOPS: WHOLE-SHARE GTC stop fires on its own — verify it's still confirmed; if missing, re-place.
   Ratchet up, never down. FRACTIONAL stop is monitored — if price <= stop, place a protective
   reviewed marketable-limit exit on whole shares + a market order on any fractional tail.
7. ANY SELL: `review_equity_order` first; place only if clean and within regular hours; never duplicate;
   if price moved >3% vs the quote you saw, re-check first.
8. NO new buys. NO discovery. NO regime analysis.
9. Append ONE compact JSON line to state/journal.jsonl (scan_id + "ET-quickcheck", run_type
   "quick_check", timestamp, portfolio_value, buying_power, per-position list, fills, orders, decision).
10. OUTPUT (max ~4 lines): one line per position — symbol, % vs entry, status (ok / NEAR / TARGET
    HIT->sold X / STOP->exited / stop ratcheted). If a sell happened, add ONE plain-language sentence.
    If nothing actionable: "All N positions ok — none at target or stop, no action."

Read only SKILL.md §5/§6/§8 + references/execution.md for sell/stop mechanics. Skip §7 (discovery) and
§10 (full report) entirely.

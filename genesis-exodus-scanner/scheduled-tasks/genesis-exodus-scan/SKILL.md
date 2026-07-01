---
name: genesis-exodus-scan
description: Genesis+Exodus Robinhood scan — hourly :45, 9:45a–3:45p ET, Mon–Fri (gated by ops.py preflight)
---

Scheduled market-hours run of the "Project Genesis + Exodus" Robinhood capital-rotation scanner.
Cron: `45 9-15 * * 1-5` (every hour at :45, 9:45 AM–3:45 PM ET, Mon–Fri).

MODE — set to match your SKILL.md flags. In PAPER mode, prepare orders but do not place real ones.
In LIVE/full-auto, you MAY place real buy + profit-recovery sell orders autonomously, but ONLY when
every gate and circuit breaker passes. Default to NO TRADE. Protect capital first.

LOAD AND FOLLOW THE SKILL: Read ~/.claude/skills/genesis-exodus-scanner/SKILL.md AND
references/playbooks.md + references/output-format.md, then execute the full scan exactly.
SKILL.md §0 (flags + circuit breakers) is authoritative.

DATA: Robinhood MCP for account + live quotes + order execution; FMP via
`python3 ~/.claude/skills/genesis-exodus-scanner/scripts/fmp.py` (key in state/fmp.env — never print it).

HARD GATES before ANY real order:
- PREFLIGHT FIRST: `python3 .../scripts/ops.py preflight --nav <portfolio_value>`. If
  new_buys_allowed=false -> monitoring + risk-reducing sells only, NO new buys. Seed the day's
  baseline first with `ops.py nav-set <portfolio_value>`.
- Account access OK (else output ACCOUNT ACCESS ERROR and stop).
- Trading hours ET: runs fire :45, 9:45a–3:45p; new buys only in-window. Outside it: pre-9:45 =
  prep/risk-review only; 4:00pm+ = review-only; never trade at/after 4:00pm.
- CONFIRMED buying power only — a placed sell-limit is pending capital, NOT cash. NO-DEPLOYABLE-
  CAPITAL FAST-PATH: skip buy-discovery whenever BP is $0, BP below your floor, the daily buy cap is
  reached, or preflight says new_buys_allowed=false. STILL do account check, preflight, mark positions,
  check/ratchet stops, and place any genuinely-hit profit-recovery sell.
- Candidate scored >=7/10, R:R >=2:1, market filter passes, stop defined, price <=8% above ideal entry,
  not a duplicate, within caps.
- Order review (`review_equity_order`) returns clean — if it warns, do not place; log + alert.

CIRCUIT BREAKERS (override AUTO_BUY): daily-loss halt (>=5% vs session-open NAV baseline); earnings
guard (within ~5 trading days -> WATCHLIST); consecutive-loss halt (2 of last 3 closed at a stop ->
pause + alert); data/fragility halt (missing/contradictory data or price moved >3% -> NO TRADE).

PROCEDURE: (1) account + portfolio/positions/orders; (2) `fmp.py regime`; (3) update each position,
check profit-recovery targets + open/filled sells — place a profit-recovery sell when a target is
genuinely hit and no duplicate exists; run `fmp.py earnings-multi <holdings>` (any reporting within
~5 trading days -> deliberate hold/de-risk/exit call) + `fmp.py rotation <holdings>` (rotation_candidate
flags = funding candidates; never fund a buy by cutting the runner); (4) only if confirmed cash AND hours
allow: discover via `fmp.py screener` (Genesis/Turtle) + `fmp.py movers` losers (Exodus), score top
~8–12 with `fmp.py indicators` + earnings guard + advisory sensors; pick the single best >=7/10; (5)
review then place ONLY if every gate + breaker passes; record with `ops.py buy-record '<json>'`; (6)
output the full SCAN REPORT + BEGINNER SUMMARY; (7) append one JSON line to state/journal.jsonl, and on
any fully-closed position append a record via `ops.py ledger-add`; (8) put a short plain-language summary
of any order/risk event directly in the report.

If the harness blocks an autonomous order, do NOT loop-retry — record it, alert that manual approval is
needed, and keep monitoring. Patience beats overtrading.

# Output Format — SCAN REPORT + BEGINNER SUMMARY

Every full scan (SKILL.md §10) ends with this template. Fast-path / risk-only runs (no
deployable capital, or outside trading hours) use the short form at the bottom instead.

## Full SCAN REPORT template

```
=== GENESIS + EXODUS SCAN REPORT ===
Timestamp (ET):        <YYYY-MM-DD HH:MM ET>
Account:               <last 4 of account number, or "resolved via agentic_allowed">
Mode:                  <PAPER | LIVE>   Kill-switch: <ARMED | HALTED — reason>
Regime:                <NORMAL | CAUTIOUS | DEFENSIVE | CRASH>   (VIX: <value>)

--- PREFLIGHT ---
new_buys_allowed:      <true|false>
Reasons (if blocked):  <list, or "none">
NAV baseline (today):  <$value>        Current NAV: <$value>   Drawdown: <pct>%
Buys today:            <n> / <cap>

--- ACCOUNT ---
Portfolio value:       <$value>
Confirmed buying power:<$value>
Open positions:        <n>
Open orders:           <n>

--- POSITIONS ---
<SYMBOL>  qty=<n>  avg_cost=<$>  price=<$>  %_vs_entry=<pct>  state=<STATE_MACHINE_STATE>
  stop=<$level> (ratcheted <up|unchanged> from <$prior>)   target=<$level or "runner, trailing 25%">
  action_this_scan: <none | partial sell placed qty=<n> @ <$> | stop exit placed | ...>
... (one block per position)

--- EARNINGS GUARD ---
<SYMBOL>: next earnings <date> (<n> trading days) -> <clear | BLOCKED, watchlist only>
... (one line per holding + any candidate)

--- ROTATION (advisory) ---
<SYMBOL>: rotation_candidate=<true|false>  ret21d=<pct> (prior <pct>)
... (one line per holding)

--- BUY DISCOVERY ---
<if fast-pathed: "SKIPPED — <reason: $0 BP | BP below floor | daily cap reached | preflight blocked>">
<else:>
Candidates considered: <n> (Genesis: <n>, Exodus: <n>, Turtle: <n>)
Top candidate:         <SYMBOL>  score=<n>/10  R:R=<rr_ratio>:1 (<reward_method> from `fmp.py indicators`)
  Entry:  <$price>   Stop: <$level> (-10%)   Reward target used for R:R: <$level/description>
  Size:   <n> shares  (~$<value>, capped at lesser of $2,000 / 20% of equity, risk $<value> / <pct>% to stop)
  News check (mandatory): <PASS | FAIL — WATCHLIST>  keyword flag: <clean | flagged: [<keywords>]>
    Reason: <one-line judgment -- why this is/isn't a company-specific negative catalyst>
  Gates:  confidence>=7 <pass/fail>  R:R>=2:1 (rr_pass) <pass/fail>  market filter <pass/fail>
          price<=8% above ideal entry <pass/fail>  earnings clear <pass/fail>  news check <pass/fail>
          order review <clean/warned>  duplicate check <pass/fail>
Decision: <BUY PLACED | NO TRADE — <reason> | WATCHLIST — <reason>>

--- DECISION ---
Overall:  <NO TRADE | SELL(S) PLACED | BUY PLACED | HALTED>

=== BEGINNER SUMMARY ===
<2-5 plain-language sentences, explain-to-a-13-year-old, describing what happened this scan and
why — including WHY on a NO TRADE, not just "no trade.">
```

## Fast-path / risk-only short form

Used when: no deployable capital, outside trading hours, or preflight blocks all new buys and
there's nothing to report beyond position status.

```
=== GENESIS + EXODUS — QUICK STATUS ===
Timestamp (ET): <...>   Mode: <PAPER|LIVE>   Kill-switch: <ARMED|HALTED>
Regime: <...>           Buy discovery: SKIPPED (<reason>)

Positions (<n>):
<SYMBOL> %_vs_entry=<pct> state=<...> action=<none|...>
...

<1-2 sentence plain-language summary.>
```

## Rules for filling the template

- Never invent a number. Every price/level/quantity must come from a live Robinhood or FMP call
  made this scan (SKILL.md §1's honesty rule).
- If a field is unknown/unavailable, print `unknown` — never a placeholder value that looks real.
- The BEGINNER SUMMARY must explain the reasoning for a NO TRADE, not just restate it — e.g. "Two
  of our last three trades hit their stops, so we're pausing new buys until you review them."
- Every trade action (buy, sell, stop ratchet, halt) gets its own one-sentence plain-language line
  in addition to the structured block, per SKILL.md's ALERTS rule.

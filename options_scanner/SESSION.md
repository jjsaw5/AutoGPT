# The Session Runbook — how we run everything, every time

**Purpose.** "Run a full session" must mean the *same thing* every time, no
matter how the request is phrased. This file is the single definition of a
session. If a step isn't here, it isn't part of a session; if it is here, it
runs every time. Your trigger is one message — **"run a session"** — not a
checklist you have to remember.

---

## What a session is (fixed, ordered)

| # | Stage | Who runs it | Persisted? |
|---|-------|-------------|------------|
| 1 | Market regime | scanner (auto) | run manifest |
| 2 | New-entry scan → ranked GO / WATCH / PASS | scanner (auto) | `scan_candidates` |
| 3 | **Position review of the live book → grade + action** | scanner, from the pulled positions | `position_reviews` |
| 4 | Journal: shadow-track candidates | scanner (auto) | ledger JSON |
| 5 | Durable history + Turso — **candidates AND reviews** | scanner (auto) | JSONL + SQLite + Turso |
| 6 | Combined readout (new entries, then the book) | scanner (auto) | — |

Everything except the live-book pull is deterministic and automatic. The scan
also scans **every held underlying** (`extra_tickers`), so each review is graded
against a *fresh* thesis, never a stale one.

---

## The one human-gated step (never skip)

Option positions come from the **Robinhood MCP** (read-only, agent-driven) — a
headless CLI can't reach it. So a session always begins with the agent pulling
the live book and writing it to a positions file:

1. Pull option positions for **each account** via the Robinhood MCP
   (`get_option_positions`) — read-only; **no orders are ever placed**.
2. For each position, derive the broker facts into a row:
   - `ticker`, `account`
   - `direction` (+1 long-biased / −1 short-biased / 0 neutral)
   - `is_long_premium` (long option / debit spread = true; short premium = false)
   - `pnl_pct` (current P&L as a fraction of cost/risk)
   - `dte`, `days_to_earnings`
3. Write them to `runs/positions.json` as a JSON list.

Then run the session command below. If the positions file is omitted, the
session runs **scan-only** and prints a note that the book review was skipped —
so a missing review is loud, never silent (the failure mode we hit before).

---

## The command

```bash
set -a && . ./.env && set +a         # load FMP / UW / Turso creds (gitignored)

python -m options_scanner.cli session \
    --positions runs/positions.json \
    --history   history \
    --journal   runs/ledger.json
```

This performs stages 1–6 in one shot: regime, scan (universe ∪ held names),
per-holding review, shadow journal, durable history + Turso write-through, and a
combined readout. It prints how many candidate rows and position reviews were
persisted.

---

## After a session

- **Commit the durable history** so it survives the ephemeral container:
  `git add history/ && git commit && git push` (secrets never leave `.env`).
- **Inspect drift** any time:
  - candidate score over runs: `python -m options_scanner.cli history timeline --history history --ticker SPY`
  - a holding's grade over sessions: query `position_reviews` (same store).
- **Taken-trade reconcile** (realized P&L → calibration) is a *separate*,
  deliberate step via `journal resolve` — not part of the automatic session.

---

## The contract

- **Recommend-only.** Every GO and every review action (CLOSE/TRIM/…) is a
  hypothesis for a human to confirm. No order is placed anywhere in a session.
- **Nothing depends on phrasing.** "Run a session" = this runbook, verbatim.
- **A skipped stage is visible.** Missing positions → an explicit scan-only note,
  never a quietly incomplete run.

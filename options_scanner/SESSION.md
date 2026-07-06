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

## Cadence — when to run (3×/day + events)

Frequency is tuned to how fast our signals decay vs. how long our trades live.
Our structures are **7–46 DTE** (some LEAPS 500+ days), and intraday composite
scores are **noisy** (SPY swung 55→69→48→64 in one day). So a genuine edge does
not evaporate in an hour, and running *more* mostly samples noise, not
opportunity. Three well-timed looks catch any GO that's real (it persists across
snapshots) while filtering the intraday wiggle.

**Trading days — 3 scheduled sessions (times ET):**

| Time | Rationale |
|------|-----------|
| **~10:00** | Post-open settle — overnight gaps in, real flow established, past the open's chaos |
| **~12:45** | Midday lull — stable tape; catch intraday shifts + stop check |
| **~3:15**  | Pre-close — best read for *next-day* entries + final stop check |

**Event triggers (run an extra session, override the baseline):**

- The **morning of / day before earnings** for any held or top-WATCH name.
- Around scheduled **macro prints** (FOMC, CPI, jobs) — these are exactly what
  move a flow-only name's catalyst pillar (e.g. SPY's P4).

**Weekend / holiday — 1 maintenance pass (no live trading):**

- Resolve shadow trades (`journal resolve`), review calibration, and map the
  coming week's earnings / macro calendar so the event triggers are known ahead.

**Notes.**
- Only run during market hours — a scan on a closed market has no live flow.
- Reviewing the same digest 3× a day fits a human-in-the-loop decision rhythm;
  it is deliberately *not* a continuous firehose.

### Automating the cadence (the scan half)

The **scan** half runs unattended via GitHub Actions —
`.github/workflows/scheduled-scan.yml` (lives under `options_scanner/` in the
monorepo; **activates once the scanner is the repo root**, i.e. in
`AI-Trade-Agent`). It survives the ephemeral dev container because it runs on
GitHub's infrastructure, and reaches Turso/FMP/UW directly (no proxy).

- **DST-correct 3×/weekday** via an ET gate (fires exactly at the windows above,
  summer or winter); `workflow_dispatch` runs it on demand.
- **Scan-only** — persists candidates to Turso and publishes the readout to the
  Actions run summary + an artifact. The **book review is not automated** (it
  needs the human-gated Robinhood pull) and stays interactive.
- **To enable:** set four repo **Actions secrets** — `FMP_API_KEY`,
  `UW_API_KEY`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`.

**Event timing** — `event-scan.yml` adds one extra scan at **~2:15pm ET on FOMC
decision days** (read from `macro_calendar.yaml`). That's the only intraday
event the baseline misses: after-hours earnings hit the pre-close run,
before-open earnings and 8:30am CPI/NFP hit the 10:00 run, but the 2:00pm FOMC
decision falls between the 12:45 and 15:15 slots. Its gate requires *both* FOMC-
day and the 2:15 window, so it never collides with the regular schedule.

Weekend maintenance stays manual/interactive.

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

- **Sessions are recommend-only.** Every GO and every review action
  (CLOSE/TRIM/…) is a hypothesis for a human to confirm. **No session, scan,
  schedule, or CI run ever places an order.** Execution is a separate,
  explicitly-invoked action governed by **EXECUTION.md** — the agent may place a
  trade only when you explicitly ask for/approve that specific order, never
  automatically, and only in allow-listed (agentic-enabled) accounts.
- **Nothing depends on phrasing.** "Run a session" = this runbook, verbatim.
- **A skipped stage is visible.** Missing positions → an explicit scan-only note,
  never a quietly incomplete run.

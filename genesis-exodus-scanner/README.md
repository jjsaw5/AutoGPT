# Project Genesis + Exodus — Autonomous Robinhood Trading Scanner

A risk-first, long-only, cash-aware market scanner built as a Claude Code skill plus two
scheduled tasks. It reads a connected Robinhood account, classifies the market regime, manages
protective stops + profit-taking, and (only when strict rules pass) prepares the single best
momentum/rebound buy. **Default answer is NO TRADE.**

This directory is the portable, git-trackable source for the skill. Nothing here is financial
advice — it's a framework, and it ships defaulted to PAPER mode with live trading off.

## What's in here

```
genesis-exodus-scanner/
├── skills/genesis-exodus-scanner/
│   ├── SKILL.md                  # the brain: rules, gates, circuit breakers
│   ├── references/               # playbooks, output format, execution mechanics, FMP catalog
│   ├── scripts/
│   │   ├── ops.py                # deterministic safety core (kill-switch, halts, ledger, NAV)
│   │   ├── fmp.py                # FMP market-data layer
│   │   └── selftest.py           # regression suite -- run this before trusting a scan
│   └── state/                    # runtime state -- .gitignore'd except fmp.env.example
└── scheduled-tasks/
    ├── genesis-exodus-scan/      # hourly full scan (SKILL.md, cron: 45 9-15 * * 1-5)
    └── genesis-quick-check/      # lightweight position watcher (cron: 0,15,30 9-15 * * 1-5)
```

## Install into a Claude Code environment

This tree mirrors the layout Claude Code expects under `~/.claude`. To install:

```bash
mkdir -p ~/.claude/skills ~/.claude/scheduled-tasks
cp -r skills/genesis-exodus-scanner        ~/.claude/skills/genesis-exodus-scanner
cp -r scheduled-tasks/genesis-exodus-scan   ~/.claude/scheduled-tasks/genesis-exodus-scan
cp -r scheduled-tasks/genesis-quick-check   ~/.claude/scheduled-tasks/genesis-quick-check
```

(Or symlink instead of copy, if you want `git pull` here to update the live skill directly.)

## Setup checklist

1. **Robinhood MCP** must be connected to Claude Code, with an account that has
   `agentic_allowed=true`. The skill resolves the account at runtime via `get_accounts` — it is
   never hard-coded.
2. **FMP API key** — a paid Premium/Stable plan is assumed. Either:
   - set `FMP_API_KEY` as an environment variable in the session that runs the skill, or
   - `cp skills/genesis-exodus-scanner/state/fmp.env.example skills/genesis-exodus-scanner/state/fmp.env`
     and fill in your key (this file is `.gitignore`'d — it will never be committed).
3. **Python 3** on your PATH.
4. **A scheduler** that can fire the two scheduled tasks on the crons noted above.
5. Run the regression suite:
   ```bash
   python3 skills/genesis-exodus-scanner/scripts/selftest.py
   ```
   ops.py checks run fully offline. fmp.py's live checks (regime, screener) are skipped
   gracefully if no key is configured yet, and run for real once one is.
6. Review `skills/genesis-exodus-scanner/SKILL.md` §0/§7 — sizing (lesser of $2,000 / 20% of
   equity) and the R:R formula are filled in, tuned for an assumed ~$10,000 account funding level
   (see `references/playbooks.md`). Re-derive them if you fund at a meaningfully different amount,
   and backtest before trusting any of it.
7. Trigger one manual run and read the SCAN REPORT (`references/output-format.md`) to confirm
   every gate behaves as expected — **before** enabling live trading.
8. Only once you've done all of the above: `python3 skills/genesis-exodus-scanner/scripts/ops.py live on`
   to flip the master live-trading flag, and update SKILL.md §0's flags to match. Until you do
   this, `ops.py preflight` always returns `new_buys_allowed: false`.

## The kill-switch

```bash
python3 skills/genesis-exodus-scanner/scripts/ops.py halt "<reason>"   # pause immediately
python3 skills/genesis-exodus-scanner/scripts/ops.py resume            # re-arm
python3 skills/genesis-exodus-scanner/scripts/ops.py status            # check current state
```

The kill-switch lives in `state/control.json` and is checked by `ops.py preflight` on every scan
— it survives across runs and is independent of whatever the SKILL.md prose says. A tripped
consecutive-loss breaker (2 of the last 3 closed trades hit a stop) can only be cleared by you,
via `ops.py ack-losses "<note>"` — the scanner itself is never allowed to call this.

## Design principles

- **Deterministic safety, model judgment.** Hard gates (kill-switch, halts, NAV baseline, buy
  caps) live in `ops.py` as code, not in prose the model could talk itself around. The LLM still
  makes the final call, but only inside a box the code defines.
- **NO TRADE is the default and a valid output.** Most scans should do nothing.
- **Cash truth + fill truth.** Never spend pending capital; never infer a fill. The broker
  (`get_portfolio` / `get_equity_orders`) is the source of truth, reconciled every scan.
- **Survival before profit.** Position size is the real seatbelt — stops can gap. Partial-profit
  at the first target de-risks; a runner with a wide trailing stop captures the upside.
- **Append-only journal.** Every scan and decision is logged (`state/journal.jsonl`); the
  strategy is judged across many trades, never changed over a single win or loss.

⚠️ **This is a framework for a system that can place real orders with no human confirmation once
you enable live trading.** Understand the kill-switch and circuit breakers in
`skills/genesis-exodus-scanner/SKILL.md` before you flip `ops.py live on`. Run it in paper mode
first. Autonomous live trading can lose money fast.

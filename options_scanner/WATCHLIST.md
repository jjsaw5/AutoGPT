# Watchlist — carry-forward for next session

*Rolling "look at this next" list. Updated at the end of a session; cleared/
refreshed on the next run. Not a trade log — the journal is that.*

**Staged:** 2026-07-06 (after close) · **For:** 2026-07-07 morning (~10:00 ET)

---

## ⭐ Primary — the BAC play (confirmed GO)

**Bull Call Spread — BAC, expiry 2026-07-17.** The one clean, Robinhood-confirmed
GO from the EOD run.

- **Buy 60 call / Sell 62.5 call** · net debit ~$0.88 → **$88/spread**
- Max profit ~$162 · max loss $88 · **R:R 1.86:1** · breakeven **$60.88**
- BAC closed ~$59.71 → needs **+2.0%** by expiry
- It's a **pre-earnings bet** — BAC reports **7/14** (before the 7/17 expiry).

**Tomorrow-morning steps:**
1. Overnight resets pricing — **re-run the morning session first**, don't act on
   tonight's numbers.
2. If BAC still surfaces as a GO, **re-confirm against live Robinhood quotes**
   (the confirm layer) before entering.
3. If it still holds: **manual** entry in the app (Call Debit Spread, 2 legs),
   limit ~$0.88 debit, **size 1× ($88 risk)** — thin EV (+$30) + earnings binary,
   so keep it small. Send the fill and I'll log it + set exits.

## Also re-check on the re-run (don't act tonight)

- **NBIS** (GO, IC) — hot small-cap, IVR 100. Needs a Robinhood confirm before
  it's believable.
- **MU** (GO, IC) — almost certainly **UW mispricing** ($975 credit on a $10
  condor = "free money"). Expect it to **REJECT** on confirmation. Don't chase.

## Book — open items to reconcile

- **PFE (+10%) & NIO (-12%)** — both show HOLD but have **pending sell orders**
  working in the app. Reconcile: if those fill, the reviews are moot.
- **RR (-1%, CLOSE)** — **ignore this one.** It's the LEAPS twitchy-close (564
  DTE, barely-over-threshold 0.54 technicals reversal). No real trigger; a
  DTE-aware fix is in BACKLOG.
- **DKNG (+15%)** — ran up nicely intraday; let it work, watch for a trim signal.

## Calendar (next ~10d)

- **7/14** — CPI (verify) + BAC & JPM earnings
- **7/16** — NFLX & TSM earnings (the shelved NFLX condor lands here)
- **7/17** — Monthly OPEX

---

*Note: once the repo is at AI-Trade-Agent root with Actions secrets set, the
scheduled-scan workflow runs the ~10:00 ET scan automatically; until then, kick
off the morning session manually (or ask me to).*

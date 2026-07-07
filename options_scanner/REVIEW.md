# Reviewing an external / online-posted play

A tool-box utility for the "review what people post online" workflow: take
someone's posted options book and critique it **through our framework** —
structure, direction, premium regime, near-dated theta, and above all
**concentration / correlation** (our G12 gate), which is what usually sinks a
copied book.

## How it works

1. **The agent parses the post** (screenshot or list) into structured rows — one
   per leg — filling in `sector` (for the correlation cluster) and, when visible,
   `underlying_price` (for the lottery-ticket check). Vision is agent-side; the
   analysis is code.
2. **`review_external.review_book`** applies our lens and returns per-position
   flags + book-level findings + a verdict + "what our framework would do."

Run it directly on a JSON file:

```bash
python -m options_scanner.cli review --positions book.json
```

Each row: `{ticker, option_type, strike, expiry, quantity, side, premium,
sector, underlying_price}` (sector/underlying_price optional but improve the read).

## What it flags

- **Structure** — naked long/short vs. detected vertical spreads. Naked singles
  are called out (full premium at risk; our framework prefers defined-risk).
- **Direction concentration** — 100% one-directional (no hedge).
- **Premium regime** — entirely long premium is *vol-blind*: only justified if IV
  is cheap. Prompts an IV-rank check (rich → sell premium; cheap → buy spreads).
- **Correlation cluster (G12)** — positions in the same sector that win/lose
  together; our correlation cap would block most of them.
- **Near-dated theta** — ≤7 DTE legs; deep-OTM + near-dated = lottery tickets.

## Limits (what it does NOT do)

The structural read needs no live data — that's the point. It does **not** score
IV-fit, EV, POP, or catalysts (those need a live chain / IV rank). To turn a
critique into real GO/WATCH/PASS grades, run the named tickers through the
scanner. This tool tells you *how a book sits against our discipline*, not
whether any single leg is a good trade today.

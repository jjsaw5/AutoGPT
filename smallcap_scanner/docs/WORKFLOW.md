# How the scanner works — step by step

This document walks through exactly what happens at each stage, with the
current default numbers, so you can review the logic and know exactly what to
change (and where) if you want different behavior. It's a companion to the
code, not a replacement — file/function references are given throughout so
you (or I) can jump straight to the relevant spot.

The scanner is three independent steps. Each can be run on its own, and the
output of step 2 feeds into step 3.

```
STEP 1: FUNDAMENTALS          STEP 2: SOCIAL              STEP 3: COMBINED
(FMP only)                    (ApeWisdom only)            (Step 2's tickers, looked
                                                            up via FMP, re-scored)
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│ Screen FMP for    │         │ Pull ticker       │         │ Take step 2's     │
│ cheap, small,     │         │ mentions from 6   │         │ ranked list, look │
│ liquid stocks     │         │ subreddits        │         │ each ticker up    │
│        ↓          │         │        ↓          │         │ via FMP directly  │
│ Enrich with       │         │ Aggregate per     │         │        ↓          │
│ 50/200d averages, │         │ ticker: mentions, │         │ Score with the    │
│ 52w range         │         │ growth, upvotes   │         │ FULL blend:       │
│        ↓          │         │        ↓          │         │ fundamental +     │
│ Score: fundamental│         │ Sort by "mentions │         │ momentum + social │
│ + momentum only   │         │ growth" (heating  │         │        ↓          │
│        ↓          │         │ up right now)     │         │ Flag anything     │
│ List 1            │         │        ↓          │         │ outside the       │
│                    │         │ List 2            │         │ price/cap band    │
└──────────────────┘         └──────────────────┘         │        ↓          │
                                                            │ List 3            │
                                                            └──────────────────┘
```

---

## Step 1 — Fundamentals (FMP only)

**Command:** `python -m smallcap_scanner fundamentals`
**Code:** `pipeline.scan_fundamentals()` → `fmp_client.py` → `scoring.score_candidate_fmp_only()`

1. **Screen.** Call FMP's `/stable/company-screener` with these filters (all
   overridable via `.env`):

   | Filter | Default | Env var |
   |---|---|---|
   | Price | $0.50 – $8.00 | `PRICE_MIN` / `PRICE_MAX` |
   | Market cap | $30M – $2B | `MARKET_CAP_MIN` / `MARKET_CAP_MAX` |
   | Avg. volume | ≥ 500,000 shares/day | `AVG_VOLUME_MIN` |
   | Exchange | NASDAQ, NYSE, AMEX only (no OTC) | `EXCHANGES` |
   | Actively trading | yes | — |
   | ETF / fund | excluded | — |

   This typically returns several hundred candidates (502 in the last live
   test run).

2. **Enrich (quotes).** For up to `FMP_ENRICH_LIMIT` candidates (default 300,
   smallest-market-cap names prioritized), call FMP's `/stable/quote` to pull
   50-day average price, 200-day average price, 52-week high/low, and
   today's volume/% change. This is one HTTP request per symbol (FMP's batch
   quote endpoint isn't available on the current plan), so a broad screen can
   take ~30–60 seconds.

3. **Enrich (history) — the grind-up pass.** Candidates are ranked once on
   quote data, then the top `FMP_HISTORY_LIMIT` (default 50) get a second,
   deeper call to `/stable/historical-price-eod/light` (~6 months of daily
   price/volume). From that, `metrics.py` computes:
   - **true 30-day average volume** (excluding today, so a surge can't
     inflate its own baseline) — this made the `VOLx` column real; it used
     to read a meaningless 1.0 for everything
   - **1/3/6-month returns**
   - **up-week ratio** — fraction of recent weeks that closed higher; the
     "steady climb" signature that separates an SLS-style grind from a
     one-day pump (both can have big returns; only the grind has this)
   - **volume trend** — last 10 days' average volume vs. the prior 30's;
     >1 means volume is *building*, the other half of the thesis

   Everything is then re-ranked with these metrics included.

4. **Score.** Two sub-scores, each 0–100:

   - **Fundamental score** (`scoring.score_fundamental`): rewards a lower
     price within the band (more option leverage), higher liquidity (log
     scale, saturating around 10× the volume floor), and a market cap in the
     lower-middle of the configured band.
   - **Momentum score** (`scoring.score_momentum`), four families of
     evidence (max points): trend vs. moving averages (35), grind-up pattern
     from history — multi-month returns + week-over-week consistency (35),
     volume behaviour — building trend + today's surge vs. true average (20),
     and 52-week-range position — off the lows with room to the highs (10).
     Continuous scaling breaks the score ties the old step-function produced.
     History-based parts contribute 0 when history wasn't fetched, so scores
     degrade gracefully for candidates outside the history budget.

   These two combine into the composite using `WEIGHT_FUNDAMENTAL` (default
   0.30) and `WEIGHT_MOMENTUM` (default 0.30), renormalized so the missing
   social weight doesn't drag the score down — this list never sees social
   data at all.

5. **Flag.** Every candidate gets checked against `scoring.risk_flags()`:
   `SUB_$1` (delisting/illiquid-options risk), `THIN_VOLUME`,
   `ALREADY_PARABOLIC_TODAY` (>25% today — chasing risk).

**Output:** ranked list, sorted by composite score, descending. The table's
`R3M%` and `UPWK%` columns surface the grind-up evidence directly.

---

## Step 2 — Social (ApeWisdom only)

**Command:** `python -m smallcap_scanner social`
**Code:** `pipeline.scan_social()` → `apewisdom_client.py`

1. **Pull mentions.** Query [ApeWisdom](https://apewisdom.io/api/) (free,
   no-auth, licensed third party — does its own Reddit scanning so we don't
   have to) for each configured subreddit:

   `wallstreetbets`, `pennystocks`, `Shortsqueeze`, `SqueezePlays`, `SPACs`,
   `Daytrading` (env var `APEWISDOM_SUBREDDITS`)

   For each ticker ApeWisdom returns: total mentions, mentions 24 hours ago,
   and total upvotes.

2. **No FMP filtering here.** This step deliberately does *not* restrict
   results to step 1's universe — it can surface tickers that never passed
   the fundamental screen (wrong price, wrong cap, or just not in FMP's
   universe at all). That's intentional: it's "what's actually trending,"
   independent of what the fundamentals say.

3. **Compute "net-new mentions."** `mentions_recent = max(0, mentions_now -
   mentions_24h_ago)` — this is the "heating up right now" signal, distinct
   from raw popularity. A ticker can have 1000 total mentions but 0 net-new
   (steady chatter) or 50 total mentions but 40 net-new (just took off).

4. **Sort** by net-new mentions descending, total mentions as tiebreaker.

5. **Score** (`scoring.score_social`) for display only at this stage — no
   stock data exists yet to combine it with: net-new mention volume (log
   scale), +15 for appearing in 2+ of the configured subreddits, +20 scaled
   by author diversity (ApeWisdom doesn't expose per-post authors, so this
   defaults to a neutral full bonus rather than penalizing it — see "Known
   limitation" below), and engagement (upvotes, log scale).

6. **Persistence annotation (the trend layer).** If saved scans exist in
   `SCANS_DIR` (default `scans/` — every `--out` run adds one), each live
   ticker is annotated from them (`trend.py`):
   - **days_seen** — distinct scan-days it appeared (within
     `TREND_LOOKBACK_DAYS`, default 14)
   - **streak_days** — consecutive scan-days ending today; counted over
     *scan-days*, so weekends/missed days don't break a streak
   - **mention_growth** — today's mentions vs. its prior-day average

   The original SLS was "talked about for six months" — a claim about time,
   which no single scan can see. Persistence feeds the social score (a
   ticker trending 4 scan-days in a row beats an identical one-day wonder)
   and shows up in the `DAYS`/`STRK`/`GROW` columns.

   There's also a standalone report needing no API keys or live scan:
   `python -m smallcap_scanner trend` — "what has retail been consistently
   talking about lately," ranked by streak.

**Output:** ranked list of tickers with mention/upvote/subreddit data plus
persistence — no price or fundamental data yet.

**Known limitation:** ApeWisdom does its own ticker-detection. A handful of
short English words that are also real tickers (`ALL` = Allstate, `BE` =
Bloom Energy, `IT` = Gartner, `CC` = Chemours) occasionally show up as noise.
Step 3 usually makes it obvious which of these are real vs. coincidental.

---

## Step 3 — Combined (social tickers, looked up via FMP, fully scored)

**Command:** `python -m smallcap_scanner combined` (or `--from-file` to reuse
a saved step-2 result instead of re-scanning)
**Code:** `pipeline.scan_combined()` → `fmp_client.quote_symbols()` →
`scoring.score_candidate()`

1. **Pre-filter known large-caps** (`pipeline.filter_known_large_caps`,
   `known_largecaps.py`). Before spending any FMP lookups, drop tickers on a
   maintained list of ~150 widely-known large/mega-cap tickers and index ETFs
   (AAPL, SPY, AMD, MSTR, ...). ApeWisdom's raw rankings are dominated by the
   same handful of these every scan; without this step they'd eat the entire
   `SOCIAL_FMP_LIMIT` budget, crowding out genuinely small-cap names sitting
   further down the mention-growth ranking. Disable with `FILTER_LARGE_CAPS=false`,
   extend with `EXTRA_LARGE_CAP_EXCLUSIONS=TICKER1,TICKER2`. This list is
   deliberately not exhaustive — it doesn't need to be, because of step 4 below.

2. **Take the top N of what's left.** `N = SOCIAL_FMP_LIMIT` (default 50) —
   bounds how many FMP lookups happen, since a 6-subreddit ApeWisdom scan can
   surface hundreds of tickers and most won't be relevant.

3. **Look each one up directly via FMP** (`quote_symbols`) — one `/stable/quote`
   call per ticker, regardless of whether it passed step 1's screen. This is
   the reverse direction from step 1: instead of filtering FMP results by
   social mentions, we're filtering FMP lookups by what's socially relevant.
   Names that fit the price/cap band then get the same EOD-history pass as
   step 1 (grind-up metrics) — out-of-range names that would be hidden anyway
   don't waste history calls.

4. **Score with the full blend**, all three sub-scores combined using
   `WEIGHT_FUNDAMENTAL` (0.30) / `WEIGHT_MOMENTUM` (0.30) / `WEIGHT_SOCIAL`
   (0.40) — this is the only stage where social score actually affects
   ranking.

5. **Flag.** Same `risk_flags()` check used everywhere, but two of its checks
   become meaningful specifically here:
   - `OUTSIDE_PRICE_RANGE` / `OUTSIDE_MARKET_CAP_RANGE` — fires when a
     socially-trending ticker doesn't actually fit the configured small-cap
     band. This is the dynamic, accurate backstop for anything that slipped
     past step 1's static blocklist (a less-famous large-cap, a name that
     just IPO'd, etc.) — it's computed from the live FMP data just pulled,
     not a guess.
   - `LOW_AUTHOR_DIVERSITY` / `SUDDEN_SEEDED_SPIKE` (pump-and-dump
     signatures) — these only fire when the data source actually tracks
     per-post authors. Since the default social source (ApeWisdom) doesn't,
     they won't fire in the default config. They're live if you switch to
     `REDDIT_MODE=praw`.

6. **Hide out-of-range results by default** (`pipeline.hide_out_of_range`).
   Anything still flagged `OUTSIDE_PRICE_RANGE`/`OUTSIDE_MARKET_CAP_RANGE`
   after lookup is excluded from the displayed/saved combined list — this is
   a display filter, not a data-loss one: it only ever applies to step 3's
   output, and `--show-out-of-range` brings it back when you want to see
   everything that was checked (e.g. to sanity-check the pipeline itself).

**Output:** the final ranked list — this is the one closest to "stocks that
are both fundamentally interesting *and* gaining real attention," with the
obvious mega-cap noise removed by construction rather than left for you to
filter manually.

---

## Quick reference: what to change, and where

| Want to change... | Edit | Env var |
|---|---|---|
| Price/cap/volume band | `config.py` `ScreenThresholds` | `PRICE_MIN/MAX`, `MARKET_CAP_MIN/MAX`, `AVG_VOLUME_MIN` |
| Which subreddits | `config.py` `DEFAULT_APEWISDOM_SUBREDDITS` | `APEWISDOM_SUBREDDITS` |
| How much social vs. fundamentals matters in step 3 | `config.py` weights | `WEIGHT_FUNDAMENTAL`, `WEIGHT_MOMENTUM`, `WEIGHT_SOCIAL` |
| How many social tickers get FMP-checked in step 3 | `config.py` | `SOCIAL_FMP_LIMIT` |
| How many top names get the deep EOD-history pass | `config.py` | `FMP_HISTORY_LIMIT` |
| The grind-up metric definitions | `metrics.py` | — |
| Trend layer: where scans live / how far back it looks | `trend.py` | `SCANS_DIR`, `TREND_LOOKBACK_DAYS` |
| The large-cap blocklist (what gets skipped before lookup) | `known_largecaps.py` | `EXTRA_LARGE_CAP_EXCLUSIONS` (add); `FILTER_LARGE_CAPS=false` (disable) |
| Whether out-of-range tickers show in step 3's output | `pipeline.py` `hide_out_of_range` | CLI `--show-out-of-range` |
| The actual scoring formulas | `scoring.py` (`score_fundamental`, `score_momentum`, `score_social`) | — |
| What counts as a risk flag | `scoring.py` `risk_flags()` | — |
| Reach the 3 niche subs ApeWisdom doesn't track | `config.py` `reddit_mode` | `REDDIT_MODE=praw` + `REDDIT_CLIENT_ID`/`SECRET` |

See [`README.md`](../README.md) for full CLI usage and
[`docs/robinhood_validation.md`](robinhood_validation.md) for the next step
after a ticker looks interesting (checking whether a usable LEAPS call
actually exists).

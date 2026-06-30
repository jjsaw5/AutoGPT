# Small-Cap Long-Call Scanner

A research scanner that hunts for **low-priced, optionable small-cap stocks**
showing the early-stage "grind up" pattern (rising price on rising volume from a
low base) **that are also gaining traction on retail trading subreddits** — the
profile of a stock that could support a long-dated (LEAPS) call play like the
`SLS $1.5 Call` example.

It runs as **three independent, chainable stages** rather than one merged list:

| Stage | Command | Source | Question it answers |
|-------|---------|--------|----------------------|
| 1. Fundamentals | `fundamentals` | FMP screener + quotes only | What does the market data alone say is a promising small-cap, optionable, grinding-up prospect? |
| 2. Social | `social` | ApeWisdom only | What tickers are actually heating up on the tracked subreddits right now — regardless of whether they fit the small-cap profile? |
| 3. Combined | `combined` | Stage 2's tickers, looked up via FMP | Now that we know what's trending, what does the fundamental/momentum data say about it? |

`all` runs all three in one pass. Each stage can be saved to JSON and the
social list can be reused later (`combined --from-file`) instead of re-scanning.

Tracked subreddits: `r/wallstreetbets`, `r/pennystocks`, `r/Shortsqueeze`,
`r/SqueezePlays`, `r/SPACs`, `r/Daytrading` (all via ApeWisdom, no credentials
needed — see "Social data source" below for how this list was chosen and the
option to reach more subreddits via official Reddit OAuth).

> ⚠️ **Read this first.** Reddit-driven penny stocks are *overwhelmingly*
> pump-and-dumps. The SLS-style 10x is **survivorship bias** — for every one,
> hundreds quietly go to zero. This tool surfaces *ideas and risk flags*, not
> recommendations. It deliberately flags coordinated-pump signatures
> (`LOW_AUTHOR_DIVERSITY`, `SUDDEN_SEEDED_SPIKE`) so a high score is never read
> uncritically. It does **not** place trades. Do your own due diligence and
> never risk money you can't lose.

## Social data source: ApeWisdom only

Reddit's official Data API requires OAuth app registration, which wasn't
available when this was built. Direct RSS scraping was tried as a stopgap but
removed — Reddit's `robots.txt` is `Disallow: /` for every path, including
those feeds, so it conflicted with Reddit's stated crawl policy and was
rate-limited unreliably in practice.

The default (`REDDIT_MODE=auto`) now uses only
[ApeWisdom](https://apewisdom.io/api/) — a free, no-auth, licensed
third-party aggregator with no scraping or ToS conflict. ApeWisdom tracks
~17 subreddits total; this scanner uses six of them, chosen by checking each
one's live data:

- **Used**: `wallstreetbets`, `pennystocks` (the original ask), plus
  `Shortsqueeze`, `SqueezePlays`, `SPACs`, `Daytrading` — added because
  short-squeeze and SPAC communities skew toward exactly the small/micro-cap,
  high-volatility profile this scanner targets, and Daytrading's top mentions
  overlapped with names already surfacing from wallstreetbets/pennystocks.
- **Deliberately excluded**: `stocks`, `investing`, `options`, `StockMarket`,
  `WallStreetbetsELITE`, `Wallstreetbetsnew` — verified live and all are
  dominated by mega-cap mentions (MSFT/AAPL/AMZN/SPY topped every one), which
  would just dilute the small-cap signal.

ApeWisdom doesn't track `TheRaceTo10Million`, `raceto10000`, or
`smallstreetbets` — the only way to reach those is official Reddit OAuth.
Set `REDDIT_MODE=praw` plus `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` (create
a "script" app at https://www.reddit.com/prefs/apps) to use it; `subreddits`
in `.env.example` lists the full original five for that mode.

One caveat worth knowing: ApeWisdom does its own ticker detection server-side,
so a handful of common short English words that also happen to be real
tickers (`ALL` — Allstate, `BE` — Bloom Energy, `IT` — Gartner, `CC` —
Chemours) can show up as noise in the `social` stage. The `combined` stage's
fundamental/momentum data usually makes it obvious which of these are real.

## Quick start

```bash
cd smallcap_scanner
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Try all three stages on bundled sample data — no API keys needed:
python -m smallcap_scanner all --mock

# Real run: copy .env.example -> .env, add FMP_API_KEY (Reddit needs no key), then:
python -m smallcap_scanner fundamentals --top 20      # stage 1
python -m smallcap_scanner social --top 40             # stage 2
python -m smallcap_scanner combined --top 20           # stage 3
```

Example stage-1 (`fundamentals --mock`) output:

```
TICKER   PRICE     SCORE    FUND    MOM     SOCIAL   RDT    VOLx    FLAGS
PMPD     0.78      85.0     84.9    85.0    0.0      0      27.5    SUB_$1...;ALREADY_PARABOLIC_TODAY
SLS      1.85      81.3     86.5    76.1    0.0      0      3.67
GRND     2.40      79.1     88.7    69.5    0.0      0      2.14
```

Example stage-2 (`social --mock`) output:

```
TICKER   MENT    NEW    SCORE   AUTH   UPVOTES   SUBREDDITS
PMPD     4       4      35.7    1      11        pennystocks
MOONX    2       2      66.8    2      480       wallstreetbets,Shortsqueeze
SLS      1       1      45.6    1      540       pennystocks
```

Example stage-3 (`combined --mock`) output — note MOONX, which never passed
the stage-1 screen, shown here with flags explaining why:

```
TICKER   PRICE     SCORE    FUND    MOM     SOCIAL   RDT    VOLx    FLAGS
SLS      1.85      67.0     86.5    76.1    45.6     1      3.67
PMPD     0.78      65.3     84.9    85.0    35.7     4      27.5    SUB_$1...;LOW_AUTHOR_DIVERSITY...
MOONX    42.5      59.7     50.0    60.0    66.8     2      1.0     OUTSIDE_PRICE_RANGE;OUTSIDE_MARKET_CAP_RANGE
```

Real (no Reddit credentials needed) combined run against live data:

```
TICKER   PRICE   SCORE   FUND   MOM    SOCIAL   RDT   FLAGS
LINK     4.82    65.4    64.9   60.0   69.8     5     THIN_VOLUME
KEEL     5.72    59.7    59.1   45.0   71.2     6     OUTSIDE_MARKET_CAP_RANGE
UMAC     22.30   67.9    66.9   75.0   63.4     11    OUTSIDE_PRICE_RANGE
```
(Most of the raw social list each run skews mega-cap — AMD, SPY, MSTR — which
is why they show `OUTSIDE_PRICE_RANGE`/`OUTSIDE_MARKET_CAP_RANGE`; the
small-cap-fitting names are the ones without those flags.)

## Getting API keys

- **FMP** (market data, required): https://site.financialmodelingprep.com/developer/docs
  — the `/stable/company-screener` endpoint builds the universe and
  `/stable/quote` enriches it. FMP retired the legacy `/api/v3` endpoints
  (including batch quote) in 2025; this tool already targets `/stable` and
  fetches quotes one symbol per request since batch isn't available on
  every plan tier.
- **Reddit** (social, optional): nothing to set up by default — `auto` mode
  uses ApeWisdom, which needs no signup. See "Social data source" above for
  the official-OAuth alternative if you want the niche subs ApeWisdom
  doesn't track.

Put keys in `.env` (see `.env.example`). All thresholds and score weights are
env-configurable too.

## CLI

```
python -m smallcap_scanner fundamentals [--mock] [--top N] [--json] [--out FILE]
python -m smallcap_scanner social       [--mock] [--top N] [--json] [--out FILE]
python -m smallcap_scanner combined     [--mock] [--top N] [--json] [--out FILE]
                                         [--from-file FILE] [--social-limit N]
python -m smallcap_scanner all          [--mock] [--top N] [--json] [--out FILE]
                                         [--social-limit N]
```

- `--mock` — run on bundled offline sample data (no keys).
- `--top N` — max rows to show (default 25 for fundamentals/combined/all, 40 for social).
- `--json` — machine-readable output (for piping / scheduling).
- `--out FILE` — also save the result as JSON. For `social`, this file can be
  fed back in via `combined --from-file FILE` to skip re-scanning.
- `--from-file FILE` (combined only) — reuse a previously saved `social --out`
  result instead of running a fresh social scan.
- `--social-limit N` (combined/all) — how many top trending tickers (by
  mention growth) get cross-referenced against FMP. Default: `SOCIAL_FMP_LIMIT`
  env var, 50.
- `--quiet` — suppress the banner. `-v`/`--verbose` — debug logging.

## How scoring works

See [`smallcap_scanner/scoring.py`](smallcap_scanner/scoring.py). Each sub-score
is 0–100. `fundamentals` re-weights across just fundamental+momentum (no
phantom social score diluting it); `combined` uses the full configurable blend
(default 30% fundamental / 30% momentum / 40% social). Crucially, **author
diversity** is rewarded where it's knowable (PRAW) — a ticker pushed by many
distinct redditors scores higher than one spammer repeating a cashtag, which
instead earns a risk flag. ApeWisdom-sourced mentions don't carry author data,
so that check is skipped rather than misfiring (see `author_diversity_known`
on `RedditSignal`).

## The options / LEAPS validation step

The scanner finds the **underlying stock**. The actual play in the example is a
*long-dated call*. FMP's free tier doesn't cover full option chains, and many
micro-caps have **no listed options at all** — so chain validation is a separate
step:

1. Take the top tickers from the scan.
2. Pull the option chain and pick a LEAPS expiration (9–18+ months out).
3. Check that low strikes exist with real **open interest** and a tradable
   **bid/ask spread** (illiquid options will eat you alive on the spread).

If you run this through Claude with the **Robinhood MCP** connected, this step is
automatable with the live tools — see
[`docs/robinhood_validation.md`](docs/robinhood_validation.md).

## Scheduling ("scan consistently")

Run `all` on a cron and save the full three-list snapshot:

```cron
# top of every hour during market hours, weekdays
0 13-21 * * 1-5  cd /path/to/smallcap_scanner && \
  /path/to/.venv/bin/python -m smallcap_scanner all --quiet \
  --out scans/$(date +\%Y-\%m-\%d_\%H).json >> scans/cron.log 2>&1
```

## Tests

```bash
pip install pytest
pytest -q
```

## Layout

```
smallcap_scanner/
  __main__.py           CLI entry point (fundamentals/social/combined/all subcommands)
  config.py             env-driven config + thresholds
  models.py             dataclasses passed between stages
  fmp_client.py         FMP /stable screener + quote wrapper
  apewisdom_client.py   no-auth ApeWisdom mention/upvote aggregator
  reddit_client.py      PRAW OAuth scan — for subs ApeWisdom doesn't track
  reddit_aggregate.py   shared post-aggregation logic (PRAW + mock data)
  ticker_extract.py     cashtag/bare-ticker parsing with stopwords
  scoring.py            sub-scores, composite, risk flags (FMP-only + full-blend variants)
  pipeline.py           the three scan stages + table/JSON formatting
  mock_data.py          offline sample data
docs/robinhood_validation.md   how to validate LEAPS chains via Robinhood MCP
tests/               unit tests (no network)
```

## Disclaimer

For educational and informational purposes only. Not financial advice. Options
trading carries a high risk of total loss. You are solely responsible for your
trades.

# Small-Cap Long-Call Scanner

A research scanner that hunts for **low-priced, optionable small-cap stocks**
showing the early-stage "grind up" pattern (rising price on rising volume from a
low base) **that are also gaining traction on retail trading subreddits** — the
profile of a stock that could support a long-dated (LEAPS) call play like the
`SLS $1.5 Call` example.

It blends three signals into one ranked list:

| Layer | Source | What it measures |
|-------|--------|------------------|
| **Fundamental** | FMP screener + quotes | Cheap enough for leverage, small cap, liquid enough to have options |
| **Momentum** | FMP quotes (50/200d avg, 52w range, volume) | Is it grinding *up* on *rising* volume? |
| **Social** | ApeWisdom + Reddit RSS (default) or PRAW OAuth | Is retail attention building across the tracked subreddits? |

Tracked subreddits (configurable): `r/wallstreetbets`, `r/pennystocks`,
`r/TheRaceTo10Million`, `r/raceto10000`, `r/smallstreetbets`.

> ⚠️ **Read this first.** Reddit-driven penny stocks are *overwhelmingly*
> pump-and-dumps. The SLS-style 10x is **survivorship bias** — for every one,
> hundreds quietly go to zero. This tool surfaces *ideas and risk flags*, not
> recommendations. It deliberately flags coordinated-pump signatures
> (`LOW_AUTHOR_DIVERSITY`, `SUDDEN_SEEDED_SPIKE`) so a high score is never read
> uncritically. It does **not** place trades. Do your own due diligence and
> never risk money you can't lose.

> ⚠️ **Reddit data source tradeoff — read before relying on this.** Reddit's
> official Data API requires OAuth app registration, which wasn't available
> when this was built. The default `REDDIT_MODE=auto` instead uses two
> sources: [ApeWisdom](https://apewisdom.io/api/) (a free, licensed,
> no-auth aggregator — fully clean) for `wallstreetbets`/`pennystocks`, and
> **direct RSS scraping** for the three niche subs ApeWisdom doesn't track
> (`TheRaceTo10Million`, `raceto10000`, `smallstreetbets`). Reddit's
> `robots.txt` is `Disallow: /` for every path, including those RSS feeds —
> they respond without an API key, but using them for sustained automated
> polling is outside Reddit's stated crawl policy, not a sanctioned gray
> area. It's rate-limited aggressively and can silently return partial data
> on any given run. **The fully compliant alternative is `REDDIT_MODE=praw`**
> with real OAuth credentials (see below) — use it if you can get API access,
> since it reliably covers all five subreddits with no policy conflict.
> See [`smallcap_scanner/reddit_rss_client.py`](smallcap_scanner/reddit_rss_client.py)
> for the full reasoning.

## Quick start

```bash
cd smallcap_scanner
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Try it immediately on bundled sample data — no API keys needed:
python -m smallcap_scanner --mock

# Real run: copy .env.example -> .env, add your keys, then:
python -m smallcap_scanner --require-social --top 20
```

Example (`--mock`) output:

```
TICKER   PRICE     SCORE    FUND    MOM     SOCIAL   RDT    VOLx    FLAGS
SLS      1.85      78.4     ...     ...     ...      3      3.7
GRND     2.40      54.1     ...     ...     ...      1      2.1
PMPD     0.78      41.2     ...     ...     ...      4      27.5    SUB_$1...;LOW_AUTHOR_DIVERSITY (possible coordinated pump)
```

Real (`--mock`-free) run against live data, no Reddit credentials needed
(`REDDIT_MODE=auto`, the default):

```
TICKER   PRICE   SCORE   FUND   MOM    SOCIAL   RDT   FLAGS
EDIT     3.24    63.3    84.5   75.0   38.6     1
RR       2.11    51.5    92.4   15.0   48.3     1
SOC      3.08    48.8    86.9   15.0   45.6     3
AMC      1.90    47.1    79.7   0.0    57.9     2
```

## Getting API keys

- **FMP** (market data, required): https://site.financialmodelingprep.com/developer/docs
  — the `/stable/company-screener` endpoint builds the universe and
  `/stable/quote` enriches it. FMP retired the legacy `/api/v3` endpoints
  (including batch quote) in 2025; this tool already targets `/stable` and
  fetches quotes one symbol per request since batch isn't available on
  every plan tier.
- **Reddit** (social, optional): nothing to set up by default — `auto` mode
  uses ApeWisdom (no signup) plus RSS scraping. To switch to the fully
  compliant OAuth path instead, set `REDDIT_MODE=praw` and create a
  "script" app at https://www.reddit.com/prefs/apps for the client id/secret.

Put keys in `.env` (see `.env.example`). All thresholds and score weights are
env-configurable too.

## CLI

```
python -m smallcap_scanner [--mock] [--require-social] [--top N] [--json] [--quiet]
```

- `--mock` — run on offline sample data (no keys).
- `--require-social` — only show names with at least one Reddit mention.
- `--top N` — limit rows (default 25).
- `--json` — machine-readable output (for piping / scheduling).

## How scoring works

See [`smallcap_scanner/scoring.py`](smallcap_scanner/scoring.py). Each sub-score is
0–100; the composite is a configurable weighted blend (default 30% fundamental /
30% momentum / 40% social). Crucially, **author diversity** is rewarded — a
ticker pushed by many distinct redditors across multiple subs scores higher than
one spammer repeating a cashtag, which instead earns a risk flag.

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

Run it on a cron and append JSON output to a log:

```cron
# top of every hour during market hours, weekdays
0 13-21 * * 1-5  cd /path/to/smallcap_scanner && \
  /path/to/.venv/bin/python -m smallcap_scanner --require-social --json \
  >> scans/$(date +\%Y-\%m-\%d).jsonl 2>&1
```

## Tests

```bash
pip install pytest
pytest -q
```

## Layout

```
smallcap_scanner/
  __main__.py           CLI entry point
  config.py             env-driven config + thresholds
  models.py             dataclasses passed between stages
  fmp_client.py         FMP /stable screener + quote wrapper
  apewisdom_client.py   no-auth ApeWisdom mention/upvote aggregator
  reddit_rss_client.py  RSS scraper for subs ApeWisdom doesn't cover (see ToS note)
  reddit_client.py      PRAW OAuth scan — the fully compliant alternative
  reddit_aggregate.py   shared post-aggregation + multi-provider merge logic
  ticker_extract.py     cashtag/bare-ticker parsing with stopwords
  scoring.py            sub-scores, composite, risk flags
  pipeline.py           orchestration + table formatting
  mock_data.py          offline sample data
docs/robinhood_validation.md   how to validate LEAPS chains via Robinhood MCP
tests/               unit tests (no network)
```

## Disclaimer

For educational and informational purposes only. Not financial advice. Options
trading carries a high risk of total loss. You are solely responsible for your
trades.

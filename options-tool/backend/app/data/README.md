# Data Providers

Every provider implements `app.data.base.DataProvider`. Three are shipped:

| Provider  | Intended use                  | Cost (2026)                          | Notes                                                                                    |
| --------- | ----------------------------- | ------------------------------------ | ---------------------------------------------------------------------------------------- |
| Mock      | Tests, offline demos          | Free                                 | Deterministic chain from a local BSM pricer. No network.                                 |
| YFinance  | Local dev, rough exploration  | Free (undocumented rate limits)      | Delayed EOD-ish data. IV history is approximated with 21-day realized vol — **not real IV.** |
| Polygon   | Production chains + IV history | Options Starter ~$29/mo, Advanced $199/mo | Real intraday chains and a proper vol surface. Stub-only until Phase 2.                 |

## Rate limits to respect

- **yfinance**: Undocumented. In practice, >5 requests/second starts returning empty
  frames. All calls go through `ChainCache` so a single analysis run hits upstream
  at most once per (ticker, kind).
- **Polygon**: 5 req/min on the free tier, unlimited on paid. Implementation should
  still cache to SQLite so re-analysing the same ticker within the TTL window is free.

## Adding a new provider

1. Implement `DataProvider` in a new file under `app/data/`.
2. Export it from `app/data/__init__.py`.
3. Register it in the FastAPI dependency in `app/api/deps.py`.
4. Add a unit test using the protocol compliance fixture in `tests/test_data_providers.py`.

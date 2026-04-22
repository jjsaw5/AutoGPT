# Options Analysis Tool

> **Educational tool. Not financial advice. Paper trading only in v1.**

A multi-strategy research and paper-trading tool that evaluates option-trade
ideas through five distinct philosophies. Every output surfaces **risk before
reward** by design.

This directory is a self-contained monorepo (`backend/`, `frontend/`,
`notebooks/`, `docs/`) that lives inside the broader AutoGPT workspace but has
no runtime dependency on it.

## Status

| Phase | Scope                                                                     | Status        |
| ----- | ------------------------------------------------------------------------- | ------------- |
| 1     | Data layer + Sosnoff (Tastytrade) module + single Trade Card in React UI  | **shipped**   |
| 2     | Thorp (quant edge) + Saliba (defined-risk) + unified side-by-side card    | **shipped**   |
| 3     | High-volume + 0DTE modules with their own guardrails                      | **shipped**   |
| 4     | Backtest harness                                                          | not started   |
| 5     | Trade journal + analytics + risk-dashboard polish                         | not started   |

## Architecture

```
options-tool/
├── backend/              # FastAPI + pandas/numpy/scipy + SQLite
│   └── app/
│       ├── core/         # pydantic models + BSM pricing + vol-surface fit
│       ├── data/         # DataProvider protocol + Mock / YFinance / Polygon
│       ├── risk/         # RiskGuard service (caps + session circuit breaker)
│       ├── journal/      # TradeJournal (SQLite) + analytics
│       ├── strategists/  # Sosnoff, Thorp, Saliba, HighVolume, ZeroDTE
│       ├── api/          # FastAPI routes + DI
│       ├── portfolio.py  # Greeks aggregator
│       └── main.py       # uvicorn entrypoint
├── frontend/             # React + Vite + TypeScript + Tailwind + Recharts
│   └── src/
│       ├── components/   # Banner, TradeCard, PayoffChart
│       ├── lib/          # typed API client + payoff builder
│       └── App.tsx
├── notebooks/            # scratch analysis (ignored by CI)
└── docs/
    └── screenshots/      # UI snapshots per phase
```

Every strategist implements a common `Strategist` protocol
(`backend/app/strategists/base.py`) with four methods: `screen`, `analyze`,
`size`, and `manage`. Later phases plug in more implementations without
touching the trade-card surface.

## Running it

### Backend

```bash
cd options-tool/backend
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
PYTHONPATH=. pytest -q        # 26 tests; all should pass
PYTHONPATH=. uvicorn app.main:app --reload --port 8001
```

Point at a different data provider with:

```bash
OPTIONS_TOOL_PROVIDER=yfinance uvicorn app.main:app --reload --port 8001
# or (Phase 2):
POLYGON_API_KEY=xxx OPTIONS_TOOL_PROVIDER=polygon uvicorn app.main:app ...
```

### Frontend

```bash
cd options-tool/frontend
npm install
npm run dev        # http://localhost:5173 (proxies /api to :8001)
```

Type-check: `npm run build`. Lint: `npm run lint`.

## Methodology citations

### High-volume / "Elite Options Trader" (Phase 3)

This module is a **volume-and-journaling wrapper**, not an endorsement of
stop-less trading. Design intent:

- Wide (~0.08-delta) short strangles sold for premium.
- `RiskGuard` enforces: per-ticker contract cap, daily realized-loss cap,
  weekly realized-loss cap. Any breach → setup returns `skip`.
- Scale-in on losing positions is *permitted by the manage() rules*, but only
  up to the per-ticker cap and only when the guard approves the additional
  contracts.
- `max_theoretical_loss` is always surfaced at entry because there is no
  hard stop — that's the module's explicit departure from stop-based discipline.
- Every action includes a journaling hint so `Kelly-implied` vs `actual` size
  shows up in the analytics panel.

### 0DTE / Sang-Lucci-style intraday (Phase 3)

- Universe restricted to SPY / SPX / QQQ / SPXW / XSP.
- Signal score is the sum of three votes:
  1. **ORB** — close beyond first 30-minute range.
  2. **VWAP** — relationship of current price to session VWAP.
  3. **Dealer-gamma proxy** — intraday realized-vol differential (rough SVI
     shortcut for real GEX, which requires paid data).
- Every returned setup carries a **mandatory hard stop-loss**, overriding the
  high-volume module's no-stop behavior.
- `RiskGuard` in `session_only=True` mode halts new entries after N
  consecutive losses or once session drawdown exceeds a % of cash.

### Thorp — quantitative edge (Phase 2)

- **Fractional Kelly sizing**: Edward O. Thorp, _A Man for All Markets_
  (Random House, 2017), and _The Kelly Capital Growth Investment Criterion_
  (World Scientific, 2011). Default multiplier 0.25× of full Kelly.
- **Vol surface edge**: market IV compared to a fitted per-expiry quadratic
  smile σ(k) ≈ a₀ + a₁·k + a₂·k² in log-moneyness — the textbook polynomial
  SVI surrogate from Jim Gatheral, _The Volatility Surface_ (Wiley, 2006).
- **Delta-neutral pair construction**: primary option plus an opposite-right
  contract near −delta. Stock-hedged variant deferred to Phase 4.

### Saliba — defined-risk structures (Phase 2)

- Anthony Saliba, _Managing Expectations_ (Oxford Futures, 1996) and
  _Options: Trading Strategies That Work_ (Marketplace Books, 2008).
- Iron condor / iron butterfly / long butterfly / broken-wing fly enumerated
  and scored by composite `(R:R, POP, 1 − PoT)`. Candidates below a configurable
  `min_reward_risk` are rejected.
- POP computed from the risk-neutral lognormal density; PoT from the
  reflection-principle first-passage formula (Shreve, _Stochastic Calculus for
  Finance II_, Theorem 7.2.1).

### Sosnoff — premium selling (Phase 1)

The Sosnoff module encodes rules publicly documented by the Tastytrade team:

- **IV Rank / IV Percentile**: Sosnoff & Battista, _The tastytrade Guide to
  Options_ (Tastyworks, 2015+); Tom Sosnoff, _Market Measures_ segments on IVR
  ≥ 30 as an entry gate.
- **Short strangle selection at ~16 delta**: Tastytrade research segment
  _"Strangle Strike Selection"_ (2019), showing ~1σ shorts historically
  balanced POP and premium.
- **Iron condor at ~20 delta with defined wings**: standard Tastytrade
  mechanical rules; see _"Trade Mechanics"_ curriculum.
- **Manage at 50% of max profit, exit/roll at 21 DTE**: documented in
  Tastytrade's _"Managing Winners"_ and _"21 DTE Rule"_ research, and used
  throughout the _tastylive_ curriculum.
- **Fractional Kelly sizing** (Thorp module, coming in Phase 2): Edward O.
  Thorp, _A Man for All Markets_ (2017) and _The Kelly Capital Growth
  Investment Criterion_ (2011).

## Non-negotiable guardrails

- App banner is rendered on every page: _"Educational tool. Not financial
  advice. Paper trading only in v1."_ — see `frontend/src/components/Banner.tsx`
  and the `/` API root.
- Every trade card renders **max loss before max profit**. Undefined-risk
  structures (short strangle) carry an explicit `UNDEFINED RISK` note.
- `SosnoffStrategist.size` caps capital at risk at the lower of the Kelly
  fraction and `Account.max_pct_per_trade`. Unit-tested in
  `tests/test_sosnoff.py::test_size_caps_at_max_pct_per_trade`.
- No broker integration. Even when paid data providers are configured, nothing
  in this repo places orders.

## Data-provider cost notes

See [`backend/app/data/README.md`](backend/app/data/README.md) for per-provider
cost, rate limits, and notes on when each is appropriate.

## Definition of done (Phase 1)

- [x] `app.data.DataProvider` protocol with Mock, YFinance (approx IV),
      Polygon (stub) implementations
- [x] `SosnoffStrategist` with IVR/IVP, strategy picker, 50%/21-DTE management
- [x] FastAPI routes: `/api/health`, `/api/chain/{ticker}`, `/api/analyze`,
      `/api/size`
- [x] React trade card with banner, risk-first metrics, P/L diagram, sizing
- [x] 26 pytest cases (domain models, providers, IVR/IVP math, picker, sizing,
      management, API smoke)
- [x] README with architecture, run instructions, and methodology citations

## Definition of done (Phase 3)

- [x] `app.risk.RiskGuard` — per-ticker contract cap, daily + weekly realized-loss
      caps, plus `session_only` mode for the 0DTE circuit breaker
      (N-consecutive losses and drawdown %)
- [x] `app.journal.TradeJournal` — SQLite-backed paper-fill ledger
      (record, close, list, export) keyed on ticker/strategist/opened_at
- [x] `app.journal.compute_analytics` — win rate, avg winner/loser,
      profit factor, expectancy, R-multiple distribution, Kelly-implied vs
      actual drift, per-strategist breakdown
- [x] `HighVolumeStrategist` — wide ~8-delta strangle, enforces caps via
      `RiskGuard`, always surfaces `max_theoretical_loss`, scale-in in
      `manage()` only inside the per-ticker cap
- [x] `ZeroDTEStrategist` — SPY/SPX/QQQ only, ORB + VWAP + GEX-proxy signal
      scoring, **mandatory** `stop_loss` on every setup, session circuit
      breaker halts new entries
- [x] `/api/unified-analyze` runs all five strategists side-by-side
- [x] `/api/journal/{entries,close,analytics}` and `/api/risk/check` endpoints
- [x] `/api/zero-dte/signals/{ticker}` exposes the session signal log
- [x] React `JournalPanel` (analytics + Kelly-drift chips + recent fills) and
      `ZeroDTEPanel` (session signal + vote chips). Tabs on the main app.
- [x] 74 pytest cases; `mypy --strict` clean across 28 source files

## Definition of done (Phase 2)

- [x] `app.core.bsm` — dependency-free BSM pricing, Greeks, implied-vol
      Newton–Raphson with bisection fallback, lognormal POP, and
      reflection-principle PoT
- [x] `app.core.vol_surface` — per-expiry quadratic smile fit with RMSE report
- [x] `ThorpStrategist` — flags contracts whose market IV deviates from the
      fitted smile, builds a delta-neutral pair, sizes with fractional Kelly
      capped by `max_pct_per_trade`
- [x] `SalibaStrategist` — enumerates iron condor (two wing widths), iron
      butterfly, long-call butterfly, broken-wing put fly; scores by
      `(R:R, POP, PoT)`; rejects below `min_reward_risk`
- [x] `POST /api/unified-analyze` runs all three strategists on one ticker
      and returns their verdicts side-by-side
- [x] `UnifiedCard` React component — one row per strategist with verdict
      chip, one-line headline, expandable full `TradeCard`
- [x] 48 pytest cases (Phase 1's 26 plus BSM sanity, vol surface, Thorp,
      Saliba, and the unified endpoint)
- [x] `mypy --strict` clean on 21 source files

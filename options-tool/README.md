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
| 2     | Thorp (quant edge) + Saliba (defined-risk) + unified side-by-side card    | not started   |
| 3     | High-volume + 0DTE modules with their own guardrails                      | not started   |
| 4     | Backtest harness                                                          | not started   |
| 5     | Trade journal + analytics + risk-dashboard polish                         | not started   |

## Architecture

```
options-tool/
├── backend/              # FastAPI + pandas/numpy/scipy + SQLite
│   └── app/
│       ├── core/         # pydantic domain models (OptionChain, TradeSetup, …)
│       ├── data/         # DataProvider protocol + Mock / YFinance / Polygon
│       ├── strategists/  # Strategist protocol + SosnoffStrategist
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

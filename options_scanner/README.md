# Options Opportunity Scanner (v0.2)

A **recommend-only** options decision-support engine. It ingests market,
options-flow, volatility, and catalyst data; filters and scores optionable
candidates; selects a best-fit structure (call / put / debit or credit spread /
0DTE / LEAPS); and produces a ranked, human-reviewable readout with an explicit
**GO / WATCH / PASS** decision on each.

> **This is decision support, not an auto-trader. A human confirms every order.**
> The scoring model is a hypothesis — its weights are placeholders until
> calibrated against your own logged outcomes (§9). **Not investment advice.**

This directory implements [Build Spec v0.2](#spec-mapping). It is self-contained
and unrelated to the rest of the AutoGPT repository it lives in.

## Pipeline

```
[1 Universe] → enrich → [4 Thesis] → [4 Structure] → [2 Gate]
    → [3 Score] → [5 Rank/Decide] → [6 Readout] → [human GO/NO-GO] → [7 Log]
                                                                        │
                                             [8 Calibration loop] ◄─────┘
```

Data layer: **FMP** (backbone: profile / quote / earnings), **Unusual Whales**
(edge: flow, dark pool, net premium, IV rank, term structure, realized vol,
GEX, max pain, market-wide idea feeds, **per-contract chain + greeks**),
**Robinhood** (live-quote confirmation, buying power, and human-gated execution
— accessed via the Robinhood MCP tools, not this package).

**Live chain (real strikes, not placeholders).** When UW is wired, each
candidate's structure is built against the actual option chain
(`option-contracts` for per-strike OI / volume / NBBO / IV, `greeks` for
per-strike delta) at the expiry nearest its horizon. This makes structure
selection use real strikes and premiums, and makes gates **G1** (contract
liquidity), **G2** (spread width) and **G9** (short-leg assignment) plus **POP**
evaluate on real contracts instead of proxies/placeholders. If the chain can't
be built (offline / gated / missing data), the scanner falls back to nominal
placeholders and those gates defer to live confirmation. Robinhood still
confirms live quotes at execution time.

## Install

```bash
cd options_scanner
pip install -r requirements.txt        # or: pip install -e .
```

## Configure secrets

API keys are read from the environment (never committed). Copy the template:

```bash
cp .env.example .env
# edit .env and fill in FMP_API_KEY and UW_API_KEY
```

`.env` is gitignored. Non-secret knobs (account size, risk caps, gate
thresholds, scoring weights, universe) live in [`config.yaml`](config.yaml).

## Run

```bash
# Scan the config Tier-A universe (+ reachable Tier-B feeds):
python -m options_scanner.cli scan

# Scan specific tickers, accounting for existing open risk/positions:
python -m options_scanner.cli scan --tickers AAPL,NVDA,AMD \
    --open-risk 400 --open-positions 2 --zerodte-used 1 \
    --log runs/scan.jsonl -v

# Offline (no API calls) — useful for tests/dev:
python -m options_scanner.cli scan --tickers AAPL --offline
```

The readout has three sections: **[1] core book** (GO first, then WATCH),
**[2] a separated speculative / 0DTE bucket** held to a higher quality bar and
never counted against core risk, and **[3] a portfolio summary** (open risk,
remaining budget, positions vs cap, 0DTE used, sector concentration).

## Programmatic use

```python
from options_scanner import load_config, Scanner

scanner = Scanner.from_config(load_config())
result = scanner.scan(tickers=["AAPL", "NVDA"],
                      context={"open_risk": 400, "open_positions": 2},
                      log_path="runs/scan.jsonl")
print(result.readout)
for ec in result.evaluated:
    print(ec.ticker, ec.decision.value, ec.score.composite, ec.suggested_size)
```

## Decision rules

A candidate is **GO** only when **all three** hold (spec §6b): composite
≥ `go_threshold` (72), **all hard gates pass**, and **EV > 0**. Otherwise it's
WATCH (≥ 58) or PASS. GO size scales with the score above the GO line, capped by
the tiered per-trade ceilings (G6: $200 standard, $500 high-conviction) and the
aggregate cap (G7: $2,000 / 6 positions).

## Guardrails (spec §11)

- **Human-in-the-loop:** `execution.mode = recommend_only`. This package never
  places an order; it only recommends. Execution flows through Robinhood MCP on
  explicit per-order confirmation.
- **Tiered sizing + aggregate cap are hard stops** (gates G6 / G7).
- **Graceful degradation:** on the base UW API tier, market-wide feeds
  (movers, optionable-tickers, …) require the Advanced tier; those simply yield
  nothing and the scan proceeds on Tier A + per-ticker signals. Missing keys
  degrade the affected pillars rather than crashing.
- **Stale-data protection** (G8): pass `context={"data_stale": True}` on
  weekends/holidays/halts to block.
- **Live-chain deferral:** gates that need the live option chain (spread width
  G2, short-leg moneyness G9) are marked *deferred* — surfaced for the human to
  confirm on Robinhood — rather than guessed.
- **Model humility:** the §6 weights and every heuristic (POP, expected move,
  nominal strikes/premiums) are **priors**. They are logged on every scan (§9)
  so the calibration loop can re-derive them from realized outcomes.

## Logging & calibration (spec §9)

Every candidate on every scan is appended to a JSONL log (`--log`), not just
taken trades — the row schema matches §9a. That record is the substrate for the
weekly/monthly calibration loop (POP Brier score, score-bucket attribution,
per-pillar logistic re-fit once ≥ 100 outcomes, regime/strategy and execution
audits). Fill / exit / PnL fields are appended per §9a when a trade is taken.

## Tests

```bash
python -m pytest -q          # 32 tests, fully offline (no network)
```

## Layout

```
options_scanner/
  config.yaml              # all non-secret knobs (spec §10)
  .env.example             # secret template (copy to .env)
  options_scanner/
    config.py              # YAML + env loading
    models.py              # domain dataclasses / enums
    clients/               # FMP, Unusual Whales, base HTTP (per-scan cache)
    pipeline/
      universe.py          # §3 two-tier universe + enrichment
      thesis.py            # §4 thesis construction
      chain.py             # live UW option chain (OCC parse, contracts+greeks)
      gates.py             # §5 hard gates G1–G10
      scoring.py           # §6 six-pillar composite
      structure.py         # §7 structure decision + placeholder realization
      structure_chain.py   # §7 realize structures from the live chain
      rank.py              # §6b decisions + tiered sizing
      readout.py           # §8 three-section readout
      logbook.py           # §9 candidate logging
    scanner.py             # orchestrator
    cli.py                 # `python -m options_scanner.cli scan`
  tests/
```

<a name="spec-mapping"></a>
## Spec mapping

| Spec § | Where |
|---|---|
| §2 Data source mapping | `clients/fmp.py`, `clients/unusual_whales.py` |
| §3 Two-tier universe | `pipeline/universe.py` |
| §4 Thesis construction | `pipeline/thesis.py` |
| §5 Hard gates G1–G10 | `pipeline/gates.py` |
| §6 Scoring (6 pillars) | `pipeline/scoring.py` |
| §6b Thresholds + sizing | `pipeline/rank.py` |
| §7 Structure selection | `pipeline/structure.py` |
| §8 Readout | `pipeline/readout.py` |
| §9 Logging | `pipeline/logbook.py` |
| §10 Config | `config.yaml`, `config.py` |
| §11 Guardrails | enforced across gates + `recommend_only` |

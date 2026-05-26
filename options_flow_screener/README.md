# options_flow_screener

A standalone Python CLI that screens institutional options flow with plain-English
prompts. Inspired by the "Xynth → $10K → $22K" workflow from r/optionstrading.

You type the screen you want. Claude turns it into a structured filter spec. The tool
pulls flow alerts from Unusual Whales, aggregates per ticker (bullish vs. bearish
premium, open interest, IV rank, vol/OI), and prints a ranked table. Optional follow-up:
Claude reads news + earnings for the top pick and writes a trade plan.

This is a research tool. Not investment advice. The original poster paper-traded for two
months before going live; do the same.

## Setup

```bash
cd options_flow_screener
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with your keys
```

You need:
- `UNUSUAL_WHALES_API_KEY` — https://unusualwhales.com/pricing (~$48–$100/mo)
- `ANTHROPIC_API_KEY` — https://console.anthropic.com/

## Usage

Run the canonical morning screen (no args):

```bash
python -m options_flow_screener
```

Run a custom screen:

```bash
python -m options_flow_screener "Mid-caps $1B-$50B, $25K premium, 70%+ bullish, \
DTE 15-60, IV rank above 80%, vol/OI under 0.5. Rank by open interest descending."
```

Add `--plan` to chain the trade-plan prompt on the top pick:

```bash
python -m options_flow_screener --plan
```

Override the model (defaults to `claude-sonnet-4-6`):

```bash
python -m options_flow_screener --model claude-opus-4-7 --plan
```

## How it works

```
prompt → Claude (tool_use: run_screen) → FilterSpec
                                           │
                                           ▼
            Unusual Whales /flow-alerts ──→ aggregate per ticker ──→ filter + rank
                                                                          │
                                                                          ▼
                                            (--plan) Claude → news + earnings → trade plan
```

The screen tool definition lives in `options_flow_screener/llm.py:SCREEN_TOOL`.
Aggregation rules — what counts as "bullish premium" — live in
`options_flow_screener/screener.py:_bullish_bearish_split` (call bought at ask, or put
sold at bid = bullish). Adjust either to match your conventions.

## A note on UW endpoints

I built the UW client against the API conventions documented at
`https://api.unusualwhales.com/docs` as of 2026. Endpoint paths are centralized at the
top of `options_flow_screener/unusual_whales.py` — if UW renames a path or a field, edit
the constant and the field-name fallback list in the corresponding method. Nothing else
should need to change.

If `flow_alerts()` returns nothing useful, the most likely causes are: (a) the wrapping
envelope shape differs (we strip a top-level `"data"` key — adjust `_unwrap`), or (b)
the field names for bid/ask premium differ from `total_bid_side_prem` /
`total_ask_side_prem` (adjust `_bullish_bearish_split` in `screener.py`).

## What's deliberately not here

- **No order placement.** Manual on-demand only. Bring your own broker.
- **No stop-loss logic.** The original post tested a -5% hard stop and it made
  performance worse on mid-caps that dip then recover. Time-based exit only (5 trading
  days default).
- **No backtest harness.** Run it live with paper money for a few weeks first.
- **No prompt caching.** Each CLI invocation is independent; cache TTL is 5 minutes;
  the shared prefix is small. Not worth the complexity at v1.

## Disclaimer

You will lose money trading. The Reddit post that inspired this had a 70% win rate
over 7 months in a bull market and the author explicitly noted they have no idea how
the strategy holds up in a real drawdown. Size accordingly.

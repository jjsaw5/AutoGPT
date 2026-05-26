# Options Flow Screener

Type plain-English screens like *"mid-caps, premium above $30K, IV rank above 80%, bullish only, DTE 15-60"* and get a ranked table of institutional options flow candidates. Optionally chain a trade-plan prompt for the top pick. Inspired by the Xynth/Reddit workflow.

**This is a research tool, not investment advice.** Paper-trade for a couple of months before going live with real money.

---

## Quick start (no terminal required)

### What you need first

1. **Python 3.10 or newer.** Install from [python.org/downloads](https://www.python.org/downloads/) if you don't have it. On Windows, **tick "Add python.exe to PATH"** in the installer. On Mac, Python 3 is usually pre-installed but get the latest version anyway.
2. **An Unusual Whales API key** — [unusualwhales.com/pricing](https://unusualwhales.com/pricing) (~$48/mo).
3. **An Anthropic API key** — [console.anthropic.com](https://console.anthropic.com/).

### Get the project

Download the branch as a zip:

👉 **[Download the zip](https://github.com/jjsaw5/AutoGPT/archive/refs/heads/claude/awesome-cannon-dCZZF.zip)**

Unzip it. You'll get a folder called something like `AutoGPT-claude-awesome-cannon-dCZZF`. Open it and navigate into `options_flow_screener/`.

### Run it

**Mac/Linux:** Double-click `launch.command`.

> If macOS blocks it with *"cannot be opened because the developer cannot be verified"*: right-click the file → **Open** → **Open** in the dialog. You only need to do this once.
> If double-clicking does nothing at all, open Terminal, drag the file into the window, and press Enter.

**Windows:** Double-click `launch.bat`.

> Windows SmartScreen may warn you. Click **More info** → **Run anyway**.

### What happens

**First run** — the launcher installs everything it needs (takes a couple of minutes), then opens a file called `.env` in TextEdit / Notepad. Paste your two API keys in:

```
UNUSUAL_WHALES_API_KEY=uw_paste_your_actual_key_here
ANTHROPIC_API_KEY=sk-ant-paste_your_actual_key_here
ANTHROPIC_MODEL=claude-sonnet-4-6
```

Save and close the file. Double-click the launcher again.

**Every run after that** — the launcher opens a browser tab pointed at `http://localhost:8501` with the screener UI. Type your screen, click **Run screen**, see the table.

To stop the app: go back to the terminal window the launcher opened and press `Ctrl+C`, or just close it.

---

## What the UI looks like

```
┌──────────────────────────────────────────────────────────┐
│ 📈 Institutional Options Flow Screener                   │
├──────────────────────────────────────────────────────────┤
│ Your screen:                                             │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ Mid-caps $1B-$10B, premium above $30K, IV rank...   │ │
│ └──────────────────────────────────────────────────────┘ │
│ ☐ Also generate a trade plan for the top pick           │
│ Claude model: [claude-sonnet-4-6 ▾]                     │
│ [ Run screen ]                                           │
├──────────────────────────────────────────────────────────┤
│ Ranked candidates                                        │
│ Ticker  Sector    Mkt Cap  Bull$  Bull%  IV  Largest... │
│ ────────────────────────────────────────────────────── │
│ IDYA    Health    $1.2B    $240K  100%   95  $240K     │
│ AU      Mining    $14B     $101K  100%  100  $101K     │
│ ...                                                      │
└──────────────────────────────────────────────────────────┘
```

---

## Power-user mode (terminal CLI)

If you'd rather skip the browser:

```bash
cd options_flow_screener
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then edit .env with your keys

python -m options_flow_screener                                    # default screen
python -m options_flow_screener "your custom prompt here"
python -m options_flow_screener --plan                             # chain trade plan
python -m options_flow_screener --plan --model claude-opus-4-7     # smarter model
```

---

## How it works

```
your prompt → Claude (tool_use: run_screen) → structured filter spec
                                                       │
                                                       ▼
              Unusual Whales /flow-alerts ── aggregate per ticker ── filter + rank
                                                                          │
                                                                          ▼
                                        (optional) Claude → news + earnings → trade plan
```

- **`app.py`** — Streamlit web UI.
- **`options_flow_screener/llm.py`** — Claude calls. Tool definition for `run_screen` lives here.
- **`options_flow_screener/unusual_whales.py`** — UW REST client. Endpoint paths are constants at the top — easy to swap if UW renames anything.
- **`options_flow_screener/screener.py`** — aggregation and ranking. The "bullish vs bearish" rule (call bought at ask, or put sold at bid → bullish) lives in `_bullish_bearish_split`.
- **`options_flow_screener/cli.py`** — terminal entry point.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Launcher says "Python is not installed" | Install from python.org. On Windows, re-run the installer and tick "Add python.exe to PATH". |
| Browser doesn't open automatically | Manually go to http://localhost:8501 |
| UI shows "Missing API keys" | Re-open `.env`, double-check there are no quotes around the keys and no extra spaces. Save. Restart the launcher. |
| "GET /api/option-trades/flow-alerts → 401" | Your UW key is wrong or expired. |
| "GET ... → 403" or "404" | UW may have renamed an endpoint. Edit the path constants at the top of `options_flow_screener/unusual_whales.py`. |
| No tickers pass the screen | Try loosening filters (lower IV rank min, raise vol/OI cap). Some days nothing passes — that's expected and the original Reddit author treats it as fine. |

---

## What's deliberately not in this tool

- **No order placement.** Manual on-demand only. Bring your own broker.
- **No stop-loss logic.** The Reddit author tested a hard -5% stop and it made performance worse on mid-caps. Time-based exit only.
- **No backtest harness.** Paper-trade live first.
- **No prompt caching.** Each run is independent; not worth the complexity.

---

## Disclaimer

You will lose money trading. The strategy that inspired this had a 70% win rate over 7 months *in a generally bullish market* and the original author explicitly noted they have no idea how it holds up in a real drawdown. Size accordingly.

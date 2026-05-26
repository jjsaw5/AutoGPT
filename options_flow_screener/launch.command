#!/usr/bin/env bash
# Double-click launcher for Mac/Linux.
# First run: sets up Python venv + installs dependencies (~2 min).
# Every run after that: starts the screener; browser opens automatically.

set -e
cd "$(dirname "$0")"

echo "================================================"
echo "  Options Flow Screener — launcher"
echo "================================================"
echo ""

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is not installed on this Mac."
    echo ""
    echo "Install it from: https://www.python.org/downloads/"
    echo "Pick the latest 3.x version. Run the installer. Then double-click this again."
    echo ""
    read -r -p "Press enter to close..."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "First-time setup. Installing dependencies (this takes a couple of minutes)..."
    python3 -m venv .venv
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet -r requirements.txt streamlit
    echo "Setup complete."
    echo ""
fi

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "================================================================"
    echo "  ACTION REQUIRED — paste your API keys"
    echo "================================================================"
    echo ""
    echo "I just opened a file called .env in TextEdit."
    echo "Replace the placeholder values with your real keys, then save."
    echo ""
    echo "  UNUSUAL_WHALES_API_KEY = your Unusual Whales key"
    echo "  ANTHROPIC_API_KEY      = your Anthropic key"
    echo ""
    echo "After saving, double-click this launcher again to start the app."
    echo ""
    open -e .env 2>/dev/null || true
    read -r -p "Press enter to close..."
    exit 0
fi

echo "Starting screener — your browser should open in a few seconds."
echo "To stop the app: come back to this window and press Ctrl+C."
echo ""
.venv/bin/streamlit run app.py

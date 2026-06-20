#!/usr/bin/env bash
# Start the game backend with live reload.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt
exec uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

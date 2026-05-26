@echo off
REM Double-click launcher for Windows.
REM First run: sets up Python venv + installs dependencies (~2 min).
REM Every run after that: starts the screener; browser opens automatically.

cd /d "%~dp0"

echo ================================================
echo   Options Flow Screener -- launcher
echo ================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo Python is not installed on this PC.
    echo.
    echo Install it from: https://www.python.org/downloads/
    echo IMPORTANT: tick "Add python.exe to PATH" in the installer.
    echo Then double-click this launcher again.
    echo.
    pause
    exit /b 1
)

if not exist ".venv\" (
    echo First-time setup. Installing dependencies (this takes a couple of minutes)...
    python -m venv .venv
    .venv\Scripts\pip install --quiet --upgrade pip
    .venv\Scripts\pip install --quiet -r requirements.txt streamlit
    echo Setup complete.
    echo.
)

if not exist ".env" (
    copy .env.example .env >nul
    echo.
    echo ================================================================
    echo   ACTION REQUIRED -- paste your API keys
    echo ================================================================
    echo.
    echo I just opened a file called .env in Notepad.
    echo Replace the placeholder values with your real keys, then save.
    echo.
    echo   UNUSUAL_WHALES_API_KEY = your Unusual Whales key
    echo   ANTHROPIC_API_KEY      = your Anthropic key
    echo.
    echo After saving, double-click this launcher again to start the app.
    echo.
    notepad .env
    pause
    exit /b 0
)

echo Starting screener -- your browser should open in a few seconds.
echo To stop the app: come back to this window and press Ctrl+C.
echo.
.venv\Scripts\streamlit run app.py

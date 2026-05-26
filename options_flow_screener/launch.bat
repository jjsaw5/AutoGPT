@echo off
REM Double-click launcher for Windows.
REM First run: sets up Python venv + installs dependencies. About 2 minutes.
REM Every run after that: starts the screener; browser opens automatically.

setlocal
cd /d "%~dp0"

echo ================================================
echo   Options Flow Screener -- launcher
echo ================================================
echo.

where python >nul 2>&1
if errorlevel 1 goto :no_python

if not exist ".venv\" goto :setup_venv
goto :check_env

:setup_venv
echo First-time setup. Installing dependencies, this takes about 2 minutes...
python -m venv .venv
if errorlevel 1 goto :venv_failed
.venv\Scripts\pip install --quiet --upgrade pip
.venv\Scripts\pip install --quiet -r requirements.txt streamlit
if errorlevel 1 goto :pip_failed
echo Setup complete.
echo.
goto :check_env

:check_env
if not exist ".env" goto :create_env
goto :launch

:create_env
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

:launch
echo Starting screener -- your browser should open in a few seconds.
echo To stop the app: come back to this window and press Ctrl+C.
echo.
.venv\Scripts\streamlit run app.py
goto :end

:no_python
echo Python is not installed on this PC, or it is not on the PATH.
echo.
echo Install Python from: https://www.python.org/downloads/
echo IMPORTANT: tick the box that says "Add python.exe to PATH"
echo at the bottom of the first installer screen.
echo.
echo Then double-click this launcher again.
echo.
pause
exit /b 1

:venv_failed
echo.
echo ERROR: failed to create the Python virtual environment.
echo Make sure you have Python 3.10 or newer installed.
echo.
pause
exit /b 1

:pip_failed
echo.
echo ERROR: failed to install dependencies.
echo Check your internet connection and try again.
echo.
pause
exit /b 1

:end
echo.
pause
endlocal

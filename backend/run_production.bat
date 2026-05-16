@echo off
REM FairTax Production Server - Windows CMD
REM Usage: run_production.bat

setlocal enabledelayedexpansion

set FLASK_DEBUG=false
set PORT=5000

echo ========================================
echo   FairTax Production Server
echo ========================================
echo.
echo Starting production server on http://0.0.0.0:5000
echo Press Ctrl+C to stop the server
echo.

python -m waitress --host=0.0.0.0 --port=5000 app:app

echo.
echo Server stopped.
pause

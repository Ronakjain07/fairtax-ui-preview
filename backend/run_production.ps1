# FairTax Production Server - Windows
# Usage: .\run_production.ps1

# Set environment variables
$env:FLASK_DEBUG = "false"
$env:PORT = 5000

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  FairTax Production Server" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Starting production server on http://0.0.0.0:5000" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host ""

# Run with waitress (Windows-compatible WSGI server)
python -m waitress --host=0.0.0.0 --port=5000 app:app

Write-Host ""
Write-Host "Server stopped." -ForegroundColor Red

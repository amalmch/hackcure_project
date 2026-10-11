# Launcher for HackCure Mobile Patient API Backend (Port 8001)
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $ScriptDir "mobile_backend")

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " HackCure - Mobile Patient API Backend (Port 8001)        " -ForegroundColor Green
Write-Host " Swagger Docs: http://localhost:8001/docs                 " -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan

python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload


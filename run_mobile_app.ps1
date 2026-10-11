# Launcher for HackCure Mobile Patient Application (Expo React Native)
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $ScriptDir "mobile")

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " HackCure - Mobile Patient Application (Expo)             " -ForegroundColor Green
Write-Host " Web preview: press 'w' in terminal or run 'npm run web'  " -ForegroundColor Yellow
Write-Host " Mobile: scan QR code with Expo Go app                    " -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan

npx expo start

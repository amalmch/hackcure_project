# Lance la démo Hospital Copilot (Windows PowerShell) : serveur + simulateur embarqué + agents, sans Pi, sans broker, sans clé LLM.
#   Set-ExecutionPolicy -Scope Process Bypass ; .\scripts\run-demo.ps1 [-Port 8000] [-Edge] [-Reset]
param(
    [int]$Port = 8000,
    [switch]$Edge,      # lance aussi l'edge en mode --fake (chambre 101 pilotée par un faux Raspberry Pi)
    [switch]$Reset      # supprime la base SQLite (repart des données de démo)
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Création de l'environnement virtuel…"
    python -m venv .venv
    .\.venv\Scripts\python -m pip install -q -r requirements.txt
}
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
if ($Reset) { Remove-Item -Force -ErrorAction SilentlyContinue "dashboard\clinic.db", "dashboard\clinic.db-wal", "dashboard\clinic.db-shm" }

$env:EMBEDDED_SIM = "1"
$env:FOLLOWUP_RECHECK_S = "30"      # re-vérification 30 s après la sortie de l'infirmier (démo)
$env:ESCALATION_CRITICAL_S = "120"
# V2 : delais de demonstration (trajet d'ambulance accelere, resultats du bilan en 30 s, relance de medicament a 2 min)
$env:AMBULANCE_TIME_SCALE = "6"
$env:FEVER_LAB_DELAY_S = "30"
$env:MED_RELAUNCH_S = "120"
$env:MED_ESCALATE_S = "240"
$env:PSYCH_TICK_S = "10"
$env:PREDICTION_TICK_S = "5"
$env:THERMAL_RECHECK_S = "60"
$env:PLATFORM_URL = "http://localhost:$Port"   # URL que n8n rappelle (plan, escalade, resolution)

Write-Host "`n=== Hospital Copilot — démo ===" -ForegroundColor Cyan
Write-Host "Tableau de bord : http://localhost:$Port   (owner / hackcure2026, voir .env.example pour les autres rôles)"
Write-Host "Bouton « Lancer la démo » → full_demo (3 min) ou fall_demo puis nurse_resolves."
if ($Edge) {
    Start-Process -NoNewWindow -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "edge/main.py --fake --server http://localhost:$Port --no-thermal --stream-port 0"
    Write-Host "Edge --fake démarré (chambre 101)."
}
Set-Location "$Root\dashboard"
& "$Root\.venv\Scripts\python.exe" serve.py --port $Port   # IPv4 + IPv6 : http://localhost repond sans delai

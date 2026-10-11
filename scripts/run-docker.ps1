# Hospital Copilot - lancement conteneurise (Windows PowerShell).
#   .\scripts\run-docker.ps1            plateforme + broker MQTT  -> http://localhost:8000
#   .\scripts\run-docker.ps1 -N8n       + n8n                    -> http://localhost:5678
#   .\scripts\run-docker.ps1 -Down      arret (les volumes sont conserves)
#   .\scripts\run-docker.ps1 -Reset     arret + suppression de la base (volume hackcure-data)
param(
    [switch]$N8n,
    [switch]$Down,
    [switch]$Reset
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ($Down -or $Reset) {
    docker compose --profile n8n --profile mssql down
    if ($Reset) {
        $vol = ((Split-Path -Leaf $Root).ToLower() -replace '[^a-z0-9_-]', '') + "_hackcure-data"
        docker volume rm -f $vol | Out-Null
        Write-Host "Base supprimee ($vol)."
    }
    exit 0
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker ne repond pas : demarrer Docker Desktop, attendre qu'il soit pret, puis relancer." -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env cree a partir de .env.example (a completer : cles, secrets)."
}

if ($N8n) { docker compose --profile n8n up -d --build } else { docker compose up -d --build }
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$port = if ($env:PLATFORM_PORT) { $env:PLATFORM_PORT } else { "8000" }
Write-Host "Attente de la plateforme..."
$state = "starting"
for ($i = 0; $i -lt 60; $i++) {
    $state = (docker inspect -f "{{.State.Health.Status}}" hackcure-platform 2>$null)
    if ($state -eq "healthy") { break }
    Start-Sleep -Seconds 2
}
docker compose ps
Write-Host "Plateforme : http://localhost:$port   (owner / hackcure2026)   etat : $state"
if ($N8n) { Write-Host "n8n : http://localhost:5678  (puis .\n8n\import.ps1 pour importer les workflows)" }
Write-Host "Journal : docker compose logs -f platform"

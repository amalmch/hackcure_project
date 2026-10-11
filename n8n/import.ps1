# Hospital Copilot - installe l'orchestration n8n : credentials + 4 workflows, importes et ACTIVES.
#   Set-ExecutionPolicy -Scope Process Bypass ; .\n8n\import.ps1 [-PlatformUrl http://localhost:8000] [-Check] [-Cli]
# Par defaut : API publique de n8n (N8N_BASE_URL + N8N_API_KEY de .env) via n8n/setup_n8n.py.
# -Cli : import brut par la ligne de commande n8n (sans cle d'API) ; les credentials sont alors a creer a la main (voir n8n/README.md).
param(
    [string]$PlatformUrl = "",
    [switch]$Check,
    [switch]$Cli
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if ($Cli) {
    npx n8n import:workflow --separate --input="$Root\n8n\workflows"
    Write-Host "Workflows importes (inactifs). Creer les 4 credentials puis activer chaque workflow : voir n8n\README.md."
    exit $LASTEXITCODE
}
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }
$PyArgs = @((Join-Path $Root "n8n\setup_n8n.py"))
if ($PlatformUrl) { $PyArgs += @("--platform-url", $PlatformUrl) }
if ($Check) { $PyArgs += "--check" }
& $Py @PyArgs
if ($LASTEXITCODE -eq 2) { Write-Host "API n8n indisponible : lancer n8n (npx n8n), verifier N8N_API_KEY, ou utiliser .\n8n\import.ps1 -Cli" }
exit $LASTEXITCODE

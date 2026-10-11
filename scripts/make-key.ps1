# Hospital Copilot - cles AES-256 (DATA_ENCRYPTION_KEY) et HMAC (EDGE_HMAC_KEY). Les arguments sont passes au script Python (voir --help).
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }
& $Py (Join-Path $Root "scripts\make_key.py") @args
exit $LASTEXITCODE

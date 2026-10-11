# Hospital Copilot - certificat TLS auto-signe (dashboard/certs/server.crt + server.key). Les arguments sont passes au script Python (voir --help).
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }
& $Py (Join-Path $Root "scripts\make_cert.py") @args
exit $LASTEXITCODE

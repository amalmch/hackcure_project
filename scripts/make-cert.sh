#!/usr/bin/env bash
# Hospital Copilot - certificat TLS auto-signe (dashboard/certs/server.crt + server.key). Les arguments sont passes au script Python (voir --help).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"; [ -x "$PY" ] || PY=".venv/Scripts/python.exe"; [ -x "$PY" ] || PY="python3"
exec "$PY" scripts/make_cert.py "$@"

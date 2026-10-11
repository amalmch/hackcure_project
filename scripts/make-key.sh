#!/usr/bin/env bash
# Hospital Copilot - cles AES-256 (DATA_ENCRYPTION_KEY) et HMAC (EDGE_HMAC_KEY). Les arguments sont passes au script Python (voir --help).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"; [ -x "$PY" ] || PY=".venv/Scripts/python.exe"; [ -x "$PY" ] || PY="python3"
exec "$PY" scripts/make_key.py "$@"

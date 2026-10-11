#!/usr/bin/env bash
# Hospital Copilot — installe l'orchestration n8n : credentials + 4 workflows, importés et ACTIVÉS.
#   ./n8n/import.sh [--platform-url http://localhost:8000] [--check] [--cli]
# Par défaut : API publique de n8n (N8N_BASE_URL + N8N_API_KEY de .env) via n8n/setup_n8n.py.
# --cli : import brut par la ligne de commande n8n (sans clé d'API) ; les credentials sont alors à créer à la main (voir n8n/README.md).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$1" = "--cli" ]; then
  npx n8n import:workflow --separate --input="$ROOT/n8n/workflows"
  echo "Workflows importés (inactifs). Créer les 4 credentials puis activer chaque workflow : voir n8n/README.md."
  exit 0
fi
PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || PY="$ROOT/.venv/Scripts/python.exe"; [ -x "$PY" ] || PY=python3
set +e
"$PY" "$ROOT/n8n/setup_n8n.py" "$@"
code=$?
[ "$code" = "2" ] && echo "API n8n indisponible : lancer n8n (npx n8n), vérifier N8N_API_KEY, ou utiliser ./n8n/import.sh --cli"
exit $code

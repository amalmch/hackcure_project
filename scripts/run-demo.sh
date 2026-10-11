#!/usr/bin/env bash
# Lance la démo Hospital Copilot (Linux/macOS) : serveur + simulateur embarqué + agents, sans Pi, sans broker, sans clé LLM.
#   ./scripts/run-demo.sh [PORT] [--edge] [--reset]
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT=8000; EDGE=0; RESET=0
for a in "$@"; do
  case "$a" in
    --edge) EDGE=1 ;;
    --reset) RESET=1 ;;
    [0-9]*) PORT="$a" ;;
  esac
done
if [ ! -x ".venv/bin/python" ]; then
  echo "Création de l'environnement virtuel…"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
[ -f .env ] || cp .env.example .env
[ "$RESET" = "1" ] && rm -f dashboard/clinic.db dashboard/clinic.db-wal dashboard/clinic.db-shm
export EMBEDDED_SIM=1 FOLLOWUP_RECHECK_S=30 ESCALATION_CRITICAL_S=120
# V2 : délais de démonstration (trajet d'ambulance accéléré, résultats du bilan en 30 s, relance de médicament à 2 min)
export AMBULANCE_TIME_SCALE=6 FEVER_LAB_DELAY_S=30 MED_RELAUNCH_S=120 MED_ESCALATE_S=240 PSYCH_TICK_S=10 PREDICTION_TICK_S=5 THERMAL_RECHECK_S=60
export PLATFORM_URL="http://localhost:$PORT"   # URL que n8n rappelle (plan, escalade, résolution)
echo
echo "=== Hospital Copilot — démo ==="
echo "Tableau de bord : http://localhost:$PORT   (owner / hackcure2026)"
echo "Bouton « Lancer la démo » → full_demo (3 min) ou fall_demo puis nurse_resolves."
if [ "$EDGE" = "1" ]; then
  .venv/bin/python edge/main.py --fake --server "http://localhost:$PORT" --no-thermal --stream-port 0 &
  echo "Edge --fake démarré (chambre 101)."
fi
cd dashboard
exec "$ROOT/.venv/bin/python" serve.py --port "$PORT"

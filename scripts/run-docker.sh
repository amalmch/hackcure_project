#!/usr/bin/env bash
# Hospital Copilot - lancement conteneurise.
#   ./scripts/run-docker.sh            plateforme + broker MQTT  -> http://localhost:8000
#   ./scripts/run-docker.sh --n8n      + n8n                    -> http://localhost:5678
#   ./scripts/run-docker.sh --down     arret (les volumes sont conserves)
#   ./scripts/run-docker.sh --reset    arret + suppression de la base (volume hackcure-data)
set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE=()
case "${1:-}" in
  --n8n) PROFILE=(--profile n8n) ;;
  --down) docker compose --profile n8n --profile mssql down; exit 0 ;;
  --reset) docker compose --profile n8n --profile mssql down; docker volume rm -f "$(basename "$PWD" | tr '[:upper:]' '[:lower:]')_hackcure-data" 2>/dev/null || true; echo "Base supprimee."; exit 0 ;;
esac
if ! docker info >/dev/null 2>&1; then
  echo "Docker ne repond pas : demarrer Docker Desktop (ou le service docker), puis relancer." >&2
  exit 1
fi
[ -f .env ] || { cp .env.example .env; echo ".env cree a partir de .env.example (a completer : cles, secrets)."; }
docker compose "${PROFILE[@]}" up -d --build
PORT="${PLATFORM_PORT:-8000}"
echo "Attente de la plateforme..."
for _ in $(seq 1 60); do
  s="$(docker inspect -f '{{.State.Health.Status}}' hackcure-platform 2>/dev/null || echo starting)"
  [ "$s" = "healthy" ] && break
  sleep 2
done
docker compose ps
echo "Plateforme : http://localhost:${PORT}   (owner / hackcure2026)   etat : ${s}"
[ ${#PROFILE[@]} -gt 0 ] && echo "n8n : http://localhost:5678  (puis ./n8n/import.sh pour importer les workflows)"
echo "Journal : docker compose logs -f platform"

# Hospital Copilot — HackCure

Plateforme de supervision de clinique autour d'un **jumeau numérique 3D** (Three.js), d'une **chambre réelle instrumentée**
(Raspberry Pi 5 + vision), d'**appareils médicaux simulés** et de **6 agents IA** (aide à la décision validée par un humain).

> Données patients fictives. Les suggestions IA sont une aide à la décision : un soignant valide toujours.

## Démarrage rapide (un seul processus, sans Pi, sans broker, sans clé LLM)

```powershell
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
cd dashboard
..\.venv\Scripts\uvicorn server:app --host 0.0.0.0 --port 8000
```
```bash
# Linux / macOS
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
cd dashboard && ../.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000
```
Ouvrir <http://localhost:8000> → page de connexion. Comptes de démo (mot de passe `hackcure2026`, voir `.env.example`) :
`owner`, `medecin`, `medecin_garde`, `infirmier`, `receptionniste`, `pharmacien`.

Le simulateur embarqué alimente les appareils des 4 chambres et les chambres virtuelles 102–104 ; le bouton
**« Lancer la démo »** joue les scénarios (`fall_demo`, `nurse_resolves`, `fever_101`, …).

## Lancer avec Docker (environnement conteneurisé autonome)
```powershell
.\scripts\run-docker.ps1            # plateforme + broker MQTT  → http://localhost:8000
.\scripts\run-docker.ps1 -N8n       # + n8n                    → http://localhost:5678
.\scripts\run-docker.ps1 -Down      # arrêt (base et données n8n conservées) ; -Reset supprime la base
```
```bash
./scripts/run-docker.sh [--n8n | --down | --reset]      # ou : docker compose up -d --build
```
- `Dockerfile` : Python 3.11 slim, dépendances de `requirements.txt`, **utilisateur non-root** (`hackcure`), `HEALTHCHECK` sur `/health`.
- `docker-compose.yml` : services `platform`, `mosquitto`, `n8n` (profil `n8n`), `sqlserver` (profil `mssql`) ; volumes `hackcure-data`
  (base SQLite, certificats) et `n8n-data` ; le `.env` de l'hôte est lu s'il existe (rien n'est copié dans l'image) ; `restart: unless-stopped`.
- Dans le réseau Docker, la plateforme joint le broker par `mosquitto:1883` et n8n par `http://n8n:5678` (réglé par le compose).
- Port différent : `PLATFORM_PORT=8010 docker compose up -d`. Journal : `docker compose logs -f platform`.
- **État de la vérification** : sur la machine de développement le démon Docker ne répondait pas ; le fichier compose est validé par
  `docker compose config`, l'image n'a pas été construite. Test à faire sur une machine avec Docker : `run-docker`, attendre « healthy »,
  ouvrir http://localhost:8000, lancer `full_demo_v2`.

## V3 — conformité (sécurité, interopérabilité, aide à la décision)
Actif par défaut : pseudonymisation de tout ce qui sort (LLM, n8n, Telegram, journaux), identité réservée aux rôles autorisés, journal
d'audit avec IP, API **HL7 FHIR R4** en lecture (`/fhir/...`), SADM (indice de confiance, déclencheurs, Valider / Rejeter).
À activer par `.env` : **HTTPS TLS 1.3** (`HTTPS=true`, `scripts/make-cert`), **chiffrement au repos AES-256-GCM** et **intégrité des trames
HMAC-SHA256** (`scripts/make-key --write`). Sans clé ni certificat, la plateforme démarre quand même et l'indique (`GET /health`, champ `security`).
Documents : [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/CONFORMITE.md`](docs/CONFORMITE.md), [`docs/DEPLOIEMENT.md`](docs/DEPLOIEMENT.md),
[`docs/QA_JURY.md`](docs/QA_JURY.md), [`docs/securite.md`](docs/securite.md), [`docs/interoperabilite.md`](docs/interoperabilite.md),
[`docs/integrite-trames.md`](docs/integrite-trames.md), [`docs/ergonomie.md`](docs/ergonomie.md), [`docs/biais.md`](docs/biais.md).
État réel et limites : `MORNING_REPORT.md`, section V3.

## Options
| Besoin | Commande |
|---|---|
| Broker MQTT (Mosquitto) | `docker compose up -d` — le serveur s'y connecte automatiquement, sinon repli HTTP `POST /api/ingest` |
| SQL Server | `docker compose --profile mssql up -d` + `DATABASE_URL=mssql+pyodbc://...` dans `.env` (`pip install pyodbc`) |
| LLM réel | `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY=...` (modèle `LLM_MODEL`, défaut `claude-sonnet-5-5`) |
| Telegram | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` |
| Simulateur autonome | `python simulator/sim.py --server http://localhost:8000 --scenario normal_night --speed 5` |
| Edge Raspberry Pi | `python edge/main.py --fake --server http://localhost:8000` (PC) ; voir `MORNING_REPORT.md` pour le vrai Pi |
| Webcam PC → 3D | `python dashboard/camera_loop.py --source 0` (poids YOLO requis) |

## V2 (branche `feat/v2`)
Dossier médical (15 ans d'historique fictif), fièvre vraie ≠ hausse thermique, SpO2, diagnostics live, ordonnance de traitement et plan
d'administration, psychologie (rôle `psychiatre`, questionnaire sur tablette), prédiction des crises, ambulances en temps réel (GPS, chambre
réservée), un workflow n8n par agent. Démo : **Lancer la démo → `full_demo_v2`** ; script minuté et version jury de 3 minutes dans
[`docs/demo_v2.md`](docs/demo_v2.md) ; bilan dans `MORNING_REPORT.md` (section V2) ; avancement dans `PROGRESS_V2.md`.

## n8n (orchestration réelle)
`npx n8n`, puis `.\n8n\import.ps1` (ou `./n8n/import.sh`) : crée les credentials et active les 15 workflows (un par agent ; V1 : `risk-triage`, `risk-verify`,
`shift-report`, `pharmacy-alerts`). La plateforme leur délègue la réponse aux risques et reprend la main seule si n8n est arrêté.
Voir `n8n/README.md`.

## Tests
```bash
.venv/Scripts/python -m pytest dashboard/tests computer_vision/tests edge/tests simulator/tests -q
```

## Structure
Voir `PROMPT.md` (spécification complète), `docs/EXISTING.md` (audit de l'existant), `contracts/mqtt-topics.md`
(contrats de messages), `PROGRESS.md`, `DECISIONS.md`, `BLOCKERS.md`.

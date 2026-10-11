# n8n — orchestration des agents

**Principe.** La détection temps réel et la **sévérité** restent dans le backend Python (règles déterministes, NEWS2,
qSOFA, seuils par patient) : latence, sécurité, fonctionnement hors ligne. n8n orchestre **le raisonnement LLM, les
notifications, les escalades, les attentes et les comptes rendus** de chaque agent.
Si n8n est arrêté, la plateforme continue seule (repli local automatique, affiché dans l'interface).

```
plateforme ──POST /webhook/<workflow> + X-Hospital-Secret──▶ n8n ──x-api-key──▶ api.anthropic.com
     ▲                                                       │──────────────▶ Telegram
     └────────── Authorization: Bearer <jeton de service> ───┘  (plan, résultat d'agent, escalade, journal)
```

## 1. Démarrage

```powershell
npx n8n                      # interface sur http://localhost:5678 (ou : docker run -it --rm -p 5678:5678 n8nio/n8n)
```
Créer le compte propriétaire à la première ouverture, puis **Settings → n8n API → Create an API key**.

Variables dans `.env` (jamais commité ; modèle dans `.env.example`) :

| Variable | Rôle |
|---|---|
| `N8N_ENABLED=true` | active l'envoi des événements vers n8n |
| `N8N_BASE_URL=http://localhost:5678` | adresse de n8n |
| `N8N_WEBHOOK_SECRET` | secret partagé : la plateforme l'envoie dans `X-Hospital-Secret`, les webhooks n8n le vérifient |
| `PLATFORM_URL=http://localhost:8000` | adresse de la plateforme vue depuis n8n |
| `PLATFORM_SERVICE_TOKEN` | jeton de service : n8n appelle l'API de la plateforme avec le rôle `owner` |
| `N8N_API_KEY` | clé de l'API publique de n8n, utilisée seulement par le script d'import |
| `ANTHROPIC_API_KEY`, `LLM_MODEL` | clé et modèle utilisés par les nœuds HTTP Anthropic |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | bot et conversation destinataires |

## 2. Import (credentials + 15 workflows + activation)

```powershell
.\n8n\import.ps1                 # Windows   (.\n8n\import.ps1 -Check pour vérifier l'état)
```
```bash
./n8n/import.sh                  # Linux / macOS   (./n8n/import.sh --check)
```
Le script (`n8n/setup_n8n.py`, API publique de n8n) est **rejouable** : il crée ou met à jour les 4 credentials à partir
de `.env`, importe **tous** les fichiers de `n8n/workflows/` (mise à jour si le nom existe déjà) et les **active**. Il ne
touche à aucun autre workflow de l'instance.

| Credential n8n | Type | Contenu |
|---|---|---|
| Hospital Copilot — Anthropic (x-api-key) | Header Auth | `x-api-key: ANTHROPIC_API_KEY` |
| Hospital Copilot — Telegram | Telegram API | `TELEGRAM_BOT_TOKEN` |
| Hospital Copilot — Plateforme (jeton de service) | Header Auth | `Authorization: Bearer PLATFORM_SERVICE_TOKEN` |
| Hospital Copilot — Webhook (X-Hospital-Secret) | Header Auth | `X-Hospital-Secret: N8N_WEBHOOK_SECRET` |

Les fichiers `n8n/workflows/*.json` ne contiennent **aucun secret** : les credentials y sont désignés par leur nom et
par un jeton (`__CRED_ANTHROPIC__`…), remplacé par l'identifiant réel à l'import. Trois valeurs non secrètes sont aussi
posées à l'import (`__PLATFORM_URL__`, `__TELEGRAM_CHAT_ID__`, `__LLM_MODEL__`) ; elles ne servent que lorsque le
déclencheur est un Cron, sinon l'événement de la plateforme les fournit.

Si la plateforme n'écoute pas sur le port de `PLATFORM_URL` : `.\n8n\import.ps1 -PlatformUrl http://localhost:8010`.

**Sans clé d'API** (`.\n8n\import.ps1 -Cli` ou `./n8n/import.sh --cli`) : exécute
`npx n8n import:workflow --separate --input=n8n/workflows`. Il faut alors créer les 4 credentials à la main, les
sélectionner dans les nœuds de chaque workflow, puis activer les workflows.

**Régénérer les fichiers** après une modification de prompt :
```powershell
.venv\Scripts\python n8n\build_agent_workflows.py    # un workflow par agent, depuis dashboard/app/agents/specs.py
.venv\Scripts\python n8n\build_v1_workflows.py       # risk-triage, risk-verify, shift-report, pharmacy-alerts
.\n8n\import.ps1
```

## 3. Carte des agents

Chaque agent Python a son workflow n8n. La même carte est affichée dans la plateforme (bouton **Carte des agents**,
`GET /api/agents/map`) avec le nombre d'appels passés par n8n ou par le repli local.

```mermaid
flowchart LR
  subgraph PY["Backend Python — détection et sévérité déterministes"]
    VIS[VisionAgent] ; VIT[VitalsAgent] ; ENV[EnvironmentAgent] ; RISK[RiskAgent] ; FU[FollowUpAgent] ; REP[ReportAgent]
    FEV[FeverAgent] ; DIAG[DiagnosticsAgent] ; MED[MedicationAgent] ; INT[InterventionAgent] ; PSY[PsychAgent] ; PRED[PredictionAgent] ; AMB[AmbulanceAgent]
  end
  subgraph N8N["n8n — raisonnement LLM, notifications, attentes, escalades, comptes rendus"]
    w1[vision-watch] ; w2[vitals-trend] ; w3[environment-comfort] ; w4[risk-triage] ; w5[risk-verify] ; w6[shift-report] ; w6b[record-summary] ; w6c[pharmacy-alerts]
    w7[fever-pathway] ; w8[diagnostics-live] ; w9[medication-reminders] ; w10[intervention-report] ; w11[psych-monitoring] ; w12[crisis-prediction] ; w13[ambulance-dispatch]
  end
  VIS --> w1 ; VIT --> w2 ; ENV --> w3 ; RISK --> w4 ; FU --> w5 ; REP --> w6 & w6b & w6c
  FEV --> w7 ; DIAG --> w8 ; MED --> w9 ; INT --> w10 ; PSY --> w11 ; PRED --> w12 ; AMB --> w13
  N8N -- Claude --> A[(api.anthropic.com)]
  N8N -- messages --> T[(Telegram)]
  N8N -- "POST /api/agents/result · /api/risks/{id}/plan…" --> PY
```

| Agent | Workflow | Déclencheur | Ce que fait le workflow |
|---|---|---|---|
| VisionAgent | `vision-watch` | événement signalé par la vision (lever nocturne, chute, douleur…), au plus toutes les 5 min par chambre | observation comportementale pour les transmissions, humeur observée |
| VitalsAgent | `vitals-trend` | alerte sur une constante, au plus toutes les 5 min par chambre | lecture de la tendance sur 10 min, points à surveiller |
| EnvironmentAgent | `environment-comfort` | action sur un équipement, au plus toutes les 5 min par chambre | note de confort (ce qui a été fait, pourquoi, quand revérifier) |
| RiskAgent | `risk-triage` | tout nouveau risque (webhook `risk-created`) | explication + plan d'action → Telegram infirmier → attente de « Je prends en charge » → escalade |
| FollowUpAgent | `risk-verify` | sortie du personnel (webhook `staff-left`) | attente → état réel de la chambre → risque résolu ou persistant → Telegram |
| ReportAgent | `shift-report` | Cron 07:45 et 19:45, bouton « Générer » | rapport de garde par chambre → brouillon → Telegram |
| ReportAgent | `record-summary` | bouton « Générer la synthèse » du dossier médical | synthèse du dossier (allergies, maladies chroniques, antécédents, traitements, points d'attention) |
| ReportAgent | `pharmacy-alerts` | Cron quotidien 08:00, bouton de la vue Pharmacie | stock sous le seuil, péremption < 30 j → Telegram pharmacien |
| FeverAgent | `fever-pathway` | fièvre vraie détectée ; résultats du bilan | synthèse, justification de chaque examen proposé, interprétation des résultats → Telegram médecin de garde |
| DiagnosticsAgent | `diagnostics-live` | changement des hypothèses d'un patient (au plus toutes les 2 min) | synthèse des hypothèses et prochaines étapes dans le fil médecin ↔ infirmier |
| MedicationAgent | `medication-reminders` | prise due, relance (> 30 min), médecin prévenu (> 60 min) | point de vigilance ajouté au rappel → Telegram |
| InterventionAgent | `intervention-report` | risque résolu et vérifié | brouillon du compte rendu d'intervention à partir du journal |
| PsychAgent | `psych-monitoring` | score de bien-être sous le seuil | explication des facteurs et conduite à tenir → Telegram |
| PredictionAgent | `crisis-prediction` | prédiction passant à « élevé » ou « critique » | explication du risque et conduite à tenir → Telegram |
| AmbulanceAgent | `ambulance-dispatch` | départ d'une ambulance | briefing d'accueil et préparation (matériel, équipe, examens) → Telegram |

## 4. Forme des workflows

**Workflows d'agents (11, générés depuis `dashboard/app/agents/specs.py`)** — même forme pour tous :

```
Webhook <workflow> (X-Hospital-Secret)
  → Code « Construire le prompt »   consigne de l'agent + contexte envoyé par la plateforme (déjà calculé par des règles)
  → HTTP Anthropic                  credential x-api-key, anthropic-version 2023-06-01, réponse en JSON strict
  → Code « Valider le JSON »        clés obligatoires, troncature détectée ; sinon réponse de secours signalée
  → POST {PLATFORM_URL}/api/agents/result   le gestionnaire Python de l'agent applique le résultat
  → Telegram                        si la plateforme renvoie un message (texte composé par la plateforme)
```
La consigne (prompt) de chaque agent a une seule source, `specs.py` : elle sert au workflow n8n **et** au repli local.

**Workflows V1 (4)** : `risk-triage` et `risk-verify` ont une forme propre (nœud Wait repris par le webhook `risk-ack`,
escalade, vérification après un délai) ; `shift-report` et `pharmacy-alerts` ont un déclencheur Cron en plus du webhook.

Points de conception :
- **Acquittement dans la plateforme** : « Je prends en charge » appelle l'URL de reprise du nœud Wait
  (`…/webhook-waiting/<exécution>/risk-ack`, protégée par `X-Hospital-Secret`). L'entrée du personnel dans la chambre
  lève aussi l'attente.
- **Garde-fous** : la sévérité reste celle de la plateforme ; `risk-verify` ne clôture jamais un risque si le contrôle
  déterministe (`auto_check`) échoue ; une escalade sur un risque déjà pris en charge est ignorée ; un examen suggéré par
  le LLM n'est jamais coché d'office ; le texte d'un rappel de médicament n'est jamais réécrit par le LLM.
- **Réponse de secours** : si l'appel Anthropic échoue, est tronqué ou renvoie un JSON invalide, le workflow continue
  et la plateforme construit la réponse déterministe de l'agent, signalée « réponse de secours (LLM indisponible) ».
- **Tokens** : `max_tokens` à 8000 (12000 pour le rapport de garde) — le modèle consomme des tokens de réflexion.
- **Délais de démo** : n8n reçoit les délais de la plateforme (`ESCALATION_*_S`, `FOLLOWUP_RECHECK_S`). Un nœud Wait se
  déclenche avec une précision de quelques secondes.
- n8n (Node) résout `localhost` en IPv6 : les workflows appellent la plateforme sur `127.0.0.1`.
- Toute exécution apparaît dans le panneau **Agents** de la plateforme (`n8n:<workflow>` : entrée, raisonnement, sortie).

## 5. Repli si n8n est indisponible

La plateforme sonde `GET {N8N_BASE_URL}/healthz` toutes les 20 s et tente chaque webhook 3 fois. En cas d'échec, ou si
`N8N_ENABLED=false` : chaque agent exécute lui-même le même prompt (API Anthropic directe ; réponse simulée si
`LLM_PROVIDER=mock`), le RiskAgent rédige le plan et envoie Telegram, le FollowUpAgent gère l'escalade et la
revérification. L'interface l'affiche : badge « n8n hors ligne · repli local », étiquette « agents locaux » sur le risque,
colonne « en local » de la Carte des agents.

## 6. Vérifier

```powershell
.\n8n\import.ps1 -Check                          # les 15 workflows doivent être ACTIFS
curl http://localhost:8000/health                # "n8n": "online", "llm": "ok"
curl -H "X-N8N-API-KEY: <clé>" "http://localhost:5678/api/v1/executions?limit=10"
```
Dans n8n : onglet **Executions** de chaque workflow (chaque nœud montre ses entrées et sorties, dont la réponse de Claude).

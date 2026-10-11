# Architecture — Hospital Copilot (HackCure)

Document de préparation au jury. Chaque affirmation renvoie à un fichier du dépôt : ouvrez-le si on vous pose une question.
Vocabulaire utilisé partout ci-dessous :

- **réel** : codé, exécuté et vérifié (tests ou passage réel décrit dans `MORNING_REPORT.md`) ;
- **simulé** : le code existe, mais la donnée ou le matériel est remplacé par une simulation ;
- **activable** : fonction de la V3, mise en route par une variable de `.env` — voir `PROGRESS_V3.md` pour ce qui est réellement terminé et testé ;
- **non fait** : absent du dépôt.

Rappel honnête à dire au jury : données patients **fictives** ; la démo tourne avec `LLM_PROVIDER=mock` et n8n désactivé, car le crédit de l'API Anthropic de l'équipe est épuisé (`BLOCKERS.md`, ligne du 11/10 00:35) ; aucun test sur un vrai Raspberry Pi n'est documenté (`MORNING_REPORT.md` §3, « Manque ») ; le Vision Transformer est intégré mais n'a jamais été exécuté ici (`MORNING_REPORT.md` V2.3).

---

## 1. Vue d'ensemble

```mermaid
flowchart LR
  subgraph SRC["Sources de donnees"]
    PI["Edge Raspberry Pi 5 - chambre 101 (edge/main.py)"]
    SIM["Simulateur (simulator/engine.py) - chambres 102 a 104 + appareils"]
    CAM["Webcam PC (dashboard/camera_loop.py)"]
    TAB["Tablette patient / telephone ambulancier"]
  end
  subgraph TR["Transport - contrats JSON (contracts/schemas)"]
    MQTT["MQTT Mosquitto - hackcure/room/N/..."]
    HTTP["Repli HTTP - POST /api/ingest"]
  end
  subgraph SRV["Plateforme FastAPI (dashboard/app)"]
    ING["Ingestion (ingest/handler.py) - validation, room_state"]
    BUS["Bus asyncio interne (bus.py)"]
    AG["13 agents Python (agents/*.py) - regles deterministes"]
    DB[("SQLite ou SQL Server (models.py)")]
    API["API REST + WebSocket /ws (api/*.py, ws.py)"]
  end
  subgraph EXT["Raisonnement et messages"]
    N8N["n8n - 15 workflows (n8n/workflows)"]
    LLM["API Anthropic (Claude) ou mock"]
    TG["Telegram"]
  end
  UI["Interface web - jumeau 3D Three.js + vues (dashboard/static)"]

  PI --> MQTT
  PI --> HTTP
  SIM --> ING
  CAM --> HTTP
  TAB --> API
  MQTT --> ING
  HTTP --> ING
  ING --> BUS
  BUS --> AG
  AG --> DB
  AG --> N8N
  AG --> LLM
  N8N --> LLM
  N8N --> TG
  N8N --> API
  AG --> API
  API --> UI
  UI --> API
  API --> MQTT
```

Lecture du schéma, en une phrase : **les capteurs publient des messages JSON normalisés ; la plateforme les valide, met à jour l'état de la chambre, les agents appliquent des règles Python pour détecter et classer les risques ; le LLM (dans n8n ou en direct) ne fait que rédiger explications et plans ; un humain valide ; l'interface 3D reçoit tout par WebSocket.**

### Les briques et leur fichier

| Brique | Fichier(s) | Ce qu'elle fait |
|---|---|---|
| Edge chambre 101 | `edge/main.py` (classe `Edge`), `edge/vision/*`, `edge/transport/__init__.py`, `edge/safety/local_rules.py` | Caméra → modèle → posture ; capteurs ; règles locales ; publication |
| Module vision | `computer_vision/src/` (`inference.py`, `detection/`, `tracking/`, `temporal/`, `transformer/`, `behavior.py`) | Détection YOLO, suivi, détecteur de chute temporel, analyse comportementale optionnelle |
| Contrats | `contracts/mqtt-topics.md`, `contracts/schemas/*.json`, `dashboard/app/contracts.py` | Un JSON Schema par type de message, `validate(topic, payload)` |
| Ingestion | `dashboard/app/ingest/handler.py` (`handle`), `ingest/mqtt.py`, `api/ingest.py` | Même traitement que le message vienne de MQTT, de HTTP ou du simulateur embarqué |
| Bus interne | `dashboard/app/bus.py` (`EventBus`) | Files asyncio par abonné, motifs `+`, `*`, `#` |
| Agents | `dashboard/app/agents/manager.py` (`AGENT_CLASSES`, 13 classes), `agents/base.py` (`Agent`) | Une tâche asyncio par agent, redémarrée automatiquement sur exception |
| Règles cliniques | `dashboard/app/clinical/` (`news2.py`, `spo2.py`, `fever.py`, `labs.py`, `diagnostics.py`, `psych.py`, `prediction.py`) | Fonctions pures, testables sans serveur |
| Orchestration LLM | `dashboard/app/orchestration.py` (`ask`, `_run_local`, `deliver`), `agents/specs.py` (`SPECS`), `n8n.py`, `agents/llm.py` | n8n si joignable, sinon même prompt en local, sinon réponse de secours |
| Persistance | `dashboard/app/models.py` (37 tables SQLModel), `db.py` | SQLite en mode WAL par défaut, `DATABASE_URL` pour SQL Server |
| Sécurité | `dashboard/app/auth.py` (`PERMISSIONS`, `require`), `audit.py` (`audit`) | JWT en cookie HttpOnly, 7 rôles, journal `AuditLog` |
| Simulateur | `simulator/engine.py` (`SimEngine`, `VirtualRoom`), `simulator/scenarios/*.yaml` (32 fichiers), `dashboard/app/sim/embedded.py` | Chambres virtuelles et appareils ; embarqué dans le serveur ou autonome (`simulator/sim.py`) |
| Interface | `dashboard/static/index.html`, `js/scene.js`, `js/floors.js`, `js/room-live.js`, `js/views/*.js` (18 vues) | Jumeau 3D + vues métier, JavaScript sans framework |

Les 13 agents enregistrés (`agents/manager.py`) : `VisionAgent`, `VitalsAgent`, `EnvironmentAgent`, `RiskAgent`, `FollowUpAgent`, `ReportAgent`, `FeverAgent`, `DiagnosticsAgent`, `MedicationAgent`, `InterventionAgent`, `PsychAgent`, `PredictionAgent`, `AmbulanceAgent`.
Les 15 workflows n8n (`n8n/workflows/`) : `risk-triage`, `risk-verify`, `shift-report`, `pharmacy-alerts`, `vision-watch`, `vitals-trend`, `environment-comfort`, `fever-pathway`, `record-summary`, `diagnostics-live`, `medication-reminders`, `intervention-report`, `psych-monitoring`, `crisis-prediction`, `ambulance-dispatch`.

### Démarrage du serveur (`dashboard/app/main.py`, fonction `lifespan`)

1. `db.init_db()` crée les tables ; `seed.seed_all()` insère les données de démo si `SEED_ON_STARTUP=1`.
2. Sont démarrés dans l'ordre : `ingest/mqtt.py` (`start`), `n8n.py` (`start`), `sim/embedded.py` (`start`), `agents/manager.py` (`start`), `agents/llm.py` (`start_health_check`).
3. Chaque module est importé par `_import_optional` : s'il manque, le serveur démarre quand même.
4. `GET /health` renvoie l'état : `llm`, `mqtt`, `n8n`, `telegram`, nombre de clients WebSocket.

---

## 2. Pipelines, étape par étape

### (a) Vision : de la caméra à la boucle soignant

```mermaid
sequenceDiagram
  participant E as Edge (edge/main.py)
  participant I as Ingestion (handler.py)
  participant V as VisionAgent
  participant R as RiskAgent
  participant N as n8n risk-triage
  participant S as Soignant (interface)
  participant F as FollowUpAgent
  E->>I: vision/state posture on_floor
  I->>V: bus - hackcure/room/101/vision/state
  V->>R: internal/risk_candidate type fall
  R->>S: risque cree + notification (WebSocket)
  R->>N: webhook risk-created (si n8n en ligne)
  N->>S: plan d action + Telegram
  S->>F: Je prends en charge puis entree en chambre
  F->>F: sortie du soignant puis attente
  F->>S: verify_risk - resolu et verifie, ou escalade
```

1. **Image → détection.** `edge/main.py`, `Edge.run` lit la caméra avec OpenCV (1 image sur `process_every`) et appelle `Edge.handle_frame`. Le pipeline est choisi par `edge/vision/pipeline.py`, `build_pipeline` : `CanonicalPipeline` (poids entraînés, via `computer_vision/src`), sinon `TwoClassPipeline`, sinon `PosePipeline` (modèle pose pré-entraîné Ultralytics), sinon `FakePipeline` (`--fake`, aucun matériel).
2. **Qui est le patient ?** `edge/vision/persons.py`, `PersonTracker.patient_track` : la personne dont le point de test est dans le polygone du lit. Les autres personnes sont du personnel : `PersonTracker.update` émet `staff_enter` / `staff_leave`.
3. **Zone.** `edge/vision/zones.py`, `ZoneTracker.update` : point bas-centre de la boîte (ou hanches) dans les polygones `bed`, `bathroom_door`, `exit` de `edge/config/room101.yaml`, avec hystérésis de 2 s.
4. **Classe CV → contrat.** `edge/vision/posture_map.py`, `map_to_contract` : donne `posture`, `activity`, `zone` (table dans `contracts/mqtt-topics.md`). Une chute n'est publiée que si le détecteur temporel la confirme (`fall_confirmed`).
5. **Règles locales, sans réseau.** `Edge.on_transition` appelle `edge/safety/local_rules.py` : `LocalRules.on_fall` (buzzer + veilleuse + message `safety/alarm`), `on_bed_exit` (veilleuse la nuit), `on_env` (clim > 27 °C, chauffage < 19 °C).
6. **Publication.** `Edge._publish` → `edge/transport/__init__.py` : `MqttTransport.publish` (QoS 1 pour les messages critiques) ou `HttpTransport.publish` puis `flush` (lot `POST /api/ingest`). Hors ligne, `HttpTransport.flush` ne garde en file (`OfflineQueue`, fichier jsonl) que `safety/alarm`, `vision/staff` et `call`. **Aucune image n'est envoyée** : seulement du JSON.
7. **Réception.** MQTT : `dashboard/app/ingest/mqtt.py` (`_run`, client aiomqtt avec reconnexion). HTTP : `dashboard/app/api/ingest.py` (`ingest`). Les deux appellent `ingest/handler.py`, `handle(topic, payload)`.
8. **Validation.** `handle` appelle `contracts.validate` (jsonschema) ; un message invalide lève `ContractError` (HTTP 422) et incrémente `stats["rejected"]`.
9. **État de la chambre.** `_on_vision_state` met à jour `room_state(room)` (dictionnaire en mémoire), enregistre un `PatientStateSnapshot` au changement ou toutes les 60 s, puis `_project_legacy` traduit en événement 3D d'origine (`fall`, `pain`, `recover`) via `state.process_event`.
10. **Bus.** `handle` termine par `bus.publish(topic, {...})`.
11. **VisionAgent** (`agents/vision.py`, motif `hackcure/room/+/vision/#`) : `on_state` lisse (hystérésis 1 s, sauf chute acceptée immédiatement), `transition` décide : chute → `candidate(room, "fall")` ; sortie du lit la nuit sans personnel → `unaccompanied_bed_exit` ; toilettes > 15 min (`on_tick`) → `toilet_too_long`. `candidate` publie `internal/risk_candidate`.
12. **RiskAgent** (`agents/risk.py`, `on_candidate`) :
    1. `plans.severity_for` fixe la sévérité par règle (chute = `critical`, toujours) ;
    2. déduplication : un seul risque ouvert par chambre et par type ;
    3. création du `Risk` et diffusion WebSocket **avant** tout appel au LLM ;
    4. `delegate_to_n8n` : si n8n est activé et répond à `/healthz`, envoi du webhook `risk-created` (`n8n.send_event`, 3 tentatives) ;
    5. `notify_for` : notification in-app aux infirmiers (≥ medium) et au médecin de garde (≥ high) ; Telegram seulement si n8n ne s'en charge pas.
13. **Plan d'action.**
    - Avec n8n : le workflow `risk-triage` fait rédiger explication et plan par Claude, les dépose par `POST /api/risks/{id}/plan` (`api/n8n.py`, `set_plan`), envoie Telegram, puis attend l'acquittement (nœud Wait) ; sans acquittement dans le délai, il appelle `POST /api/risks/{id}/escalate`.
    - Sans n8n : `RiskAgent.enrich` appelle `llm.complete_json` avec les prompts `prompts/_system.md` et `prompts/risk_plan.md`. Si la réponse n'a pas 3 à 6 étapes, le plan de secours `plans.FALLBACK_PLANS[type]` est utilisé et étiqueté « réponse de secours (LLM indisponible) ».
14. **Prise en charge.** Bouton « Je prends en charge » → `POST /api/risks/{id}/ack` (`api/n8n.py`, `acknowledge`) : statut `in_progress`, trace `AuditLog`, reprise du nœud Wait de n8n (`n8n.resume`). En simulation, `resolutions.start_for` lance le scénario `*_resolves.yaml` du type de risque (un soignant virtuel entre). Avec un edge réel, rien n'est simulé : c'est la présence détectée qui compte.
15. **Visite.** `FollowUpAgent` (`agents/followup.py`) : `on_staff_enter` crée un `StaffVisit` et passe tous les risques ouverts de la chambre en `in_progress` ; `on_staff_leave` clôt la visite et programme la revérification après `FOLLOWUP_RECHECK_S` (120 s par défaut), ou la délègue au workflow `risk-verify`.
16. **Revérification déterministe.** `FollowUpAgent.recheck` appelle `verify_risk(type, room_state)` : pour une chute, « posture ≠ `on_floor` et activité ≠ `fall` ». Vrai → `resolved` + `verified_at` ; faux → `escalated` + notification au médecin de garde. Dans `risk-verify`, l'avis de Claude ne peut clore que si ce contrôle est aussi satisfait (`DECISIONS.md`, 14:20).
17. **Sans visite.** `FollowUpAgent.check_escalations` : escalade après 2 min (critical), 10 min (high), 30 min (medium) — variables `ESCALATION_*_S`.
18. **Compte rendu.** `internal/risk/resolved` réveille l'`InterventionAgent` (`agents/care.py`, `draft`) : brouillon de compte rendu, à signer par le soignant (`POST /api/interventions/{id}/sign`).

Règle à retenir : un risque **clinique** ne se ferme jamais seul. `RiskAgent.on_clear` ne clôt automatiquement que `AUTO_CLEARABLE = {"thermal_discomfort", "room_overheat"}` ; pour les autres il ajoute la note « signal revenu dans les limites — à confirmer par un soignant ».

État : **réel** pour toute la chaîne serveur (test `dashboard/tests/test_integration_demo.py`). Côté edge : **réel en `--fake` sur PC**, **non testé sur un vrai Pi**. Les poids YOLO ne sont pas dans le dépôt.

### (b) Constantes, NEWS2 et SpO2

1. Chaque appareil publie `hackcure/room/{room}/device/{deviceId}` à 1 Hz (`simulator/engine.py`, `VirtualRoom`) — **simulé** : aucun appareil médical réel n'est branché.
2. `handler._on_device` range la mesure dans `latest_device`, dans l'historique en mémoire (`history`, 900 points ≈ 15 min) et dans le résumé `room_state["vitals"]` ; `_store_vitals_sampled` écrit un `VitalReading` toutes les 10 s seulement.
3. `VitalsAgent.handle` (`agents/vitals.py`) compare aux seuils du patient : `limits_for` part de `DEFAULT_LIMITS` (FC 48–112, PAS 95–180, FR 25) et les adapte aux antécédents (BPCO → SpO2 88 %, FR 28 ; fibrillation → FC 120).
4. Anti-bruit : `raise_candidate` exige `PERSIST = 3` lectures consécutives hors limites avant de publier `internal/risk_candidate`.
5. **SpO2** : `clinical/spo2.py`, `classify`. Standard : < 94 attention, < 90 élevé, < 88 critique. BPCO (cible 88–92 %) : < 88, < 85, < 83. « Chute rapide » = au moins 4 points perdus en 60 s **et** valeur déjà sous la cible → critique. Une aggravation (`rank` plus élevé) est transmise sans attendre.
6. **NEWS2** : `VitalsAgent.on_tick` (toutes les `VITALS_TICK_S` = 20 s) appelle `clinical/news2.py`, `news2(...)` avec l'échelle SpO2 n° 2 pour un patient BPCO. Score ≥ 5 → candidat `news2_high` ; `severity_for` : ≥ 7 critique, ≥ 5 élevé.
7. **Tendance sepsis** : `VitalsAgent.delta` compare la moyenne des 5 premiers et des 5 derniers points sur 10 min ; +0,8 °C et +18 bpm, ou −18 mmHg avec +18 bpm → candidat `sepsis_trend`.
8. Un signal secondaire (tachycardie, hypotension…) pendant un risque critique déjà ouvert est noté, sans créer de doublon (`SECONDARY`). La désaturation, elle, est toujours un risque à part entière.
9. Suite identique au pipeline (a) à partir de l'étape 12. Revérification : `verify_risk` relit la constante (ex. `hypoxemia` → `classify` renvoie `none`).
10. En parallèle, `VitalsAgent.insight` demande une lecture de tendance au workflow `vitals-trend` (au plus une fois par chambre toutes les 5 min) ; le texte est rangé dans `room_state["vitalsNote"]`.

### (c) Fièvre vraie ou simple hausse thermique

```mermaid
flowchart TD
  T["Thermometre : temperature centrale"] --> A{"clinical/fever.assess"}
  A -->|"fever : 3 lectures >= 38,0 ou >= 37,8 deux fois en 1 h"| R["Risque Fievre + parcours"]
  A -->|"thermal_rise : peau ou chambre chaude, centrale normale"| E["EnvironmentAgent seul : confort, pas d alerte"]
  R --> C["1. Bilan clinique : checklist 7 points (medecin de garde)"]
  C --> L["2. Bilan biologique propose par regles, valide par le medecin"]
  L --> F["3. Confort par EnvironmentAgent"]
  F --> X["4. Resultats au dossier, antipyretique prescrit, reverification"]
```

1. `FeverAgent.handle` (`agents/fever.py`) lit chaque message du thermomètre et appelle `clinical/fever.py`, `assess(historique, now, skin_temp, env_temp)`.
2. **Fièvre vraie** : 3 lectures consécutives ≥ 38,0 °C, ou ≥ 37,8 °C à deux reprises séparées d'au moins `FEVER_REPEAT_GAP_S` (10 min) dans l'heure. La température cutanée de la caméra thermique ne suffit **jamais** seule.
3. Fièvre → `qsofa(rr, sbp)` puis `internal/risk_candidate` de type `fever`. Le `RiskAgent` crée le risque ; `internal/risk/created` revient au `FeverAgent`, qui exécute `open_pathway` : création d'un `FeverPathway`, notification « Médecin de garde demandé », et demande de synthèse au workflow `fever-pathway`.
4. **Bilan clinique** : checklist `fever.CHECKLIST` (7 points), cochée par `POST /api/fever/{pid}/checklist` (`set_check`) puis `POST /api/fever/{pid}/exam-done` (`finish_exam`).
5. **Bilan biologique** : `clinical/labs.py`, `propose_fever_workup` propose les examens par règles, chacun avec son motif. Le LLM rédige la justification ; un examen suggéré par le LLM n'est jamais coché d'office. Le médecin valide par `POST /api/fever/{pid}/labs/validate` (`validate_labs`) — impossible avant le bilan clinique.
6. **Confort, ensuite seulement** : tant que le parcours est aux étapes `HOLD_STAGES`, l'`EnvironmentAgent` ne touche pas à la chambre ; après validation, `EnvironmentAgent.comfort_for_fever` agit.
7. **Résultats** : `FeverAgent.deliver_results` (dans `on_tick`, après `FEVER_LAB_DELAY_S`) appelle `labs.simulate` (**résultats simulés**), crée un `MedicalRecordEntry` de type `biologie` et les `LabResult`, puis demande l'interprétation au LLM.
8. **Simple hausse thermique** : `FeverAgent.on_thermal_rise` → `EnvironmentAgent.thermal_rise` : fenêtre si l'air extérieur est plus frais et le patient non fragile, sinon climatisation ; revérification après `THERMAL_RECHECK_S`. Aucun risque, aucun médecin : seulement des lignes dans le journal des agents.
9. Les commandes passent par `commands.py`, `send_command` : MQTT si un edge réel est vivant, sinon simulateur embarqué, sinon long-poll `GET /api/edge/commands`, sinon application virtuelle côté serveur (`source: server-virtual`).

### (d) Prédiction des crises

1. `PredictionAgent.on_tick` (`agents/prediction.py`, toutes les `PREDICTION_TICK_S` = 10 s) appelle `evaluate(room)` pour chaque chambre.
2. `context` rassemble : constantes, NEWS2, qSOFA, antécédents, traitements, derniers résultats biologiques, expression, `kpVariance` / `rhythmicHz` (mouvements rythmiques publiés par la vision), doses d'antiépileptique manquées, et les séries temporelles (`SERIES`).
3. `clinical/prediction.py`, `predict(ctx)` calcule cinq conditions : crise d'épilepsie, sepsis, événement cardiaque, détérioration générale, complication du diabète.
4. **Règles** : chaque condition additionne des facteurs pondérés (ex. ST ≥ 2 mm : 48 points ; glycémie < 0,7 g/L : 62 points). Le total, plafonné à 100, est le **risque** ; `level` : ≥ 80 critique, ≥ 60 élevé, ≥ 30 modéré.
5. **Pente** : `slope_per_min` fait une régression linéaire sur 10 min ; il faut au moins 8 points et 90 s d'observation (`PREDICTION_MIN_SPAN_S`).
6. **Fenêtre de temps** : `window_to(valeur, seuil, pente)` = (seuil − valeur) / pente, avec ± 40 %. Sans pente exploitable : fenêtre forfaitaire documentée (ex. ST ≥ 2 mm → 0–20 min) ou aucune.
7. **Confiance** : `_result` la calcule à partir de la **quantité de données** (« élevée » si assez de séries et une fenêtre calculée, sinon « moyenne » ou « faible »). Ce n'est pas une probabilité (`DECISIONS.md`, 23:05).
8. À partir de « élevé » : notification aux infirmiers, médecin de garde à « critique », candidat `predicted_*` vers le `RiskAgent`, explication par le workflow `crisis-prediction`.
9. Revérification : `verify_risk` relit `PredictionAgent.risk_of` ; résolu si le risque est repassé sous 60/100.
10. Mention affichée : « Estimation de prototype, non validée cliniquement » (`DISCLAIMER`).

### (e) Psychologie

1. `PsychAgent.ensure_questionnaire` (`agents/psych.py`) : dès que le patient admis est au lit, création d'un `PsychQuestionnaire` avec un jeton aléatoire (`secrets.token_urlsafe`) et notification aux infirmiers.
2. Le patient remplit la page tablette `/patient/questionnaire/{token}` (`dashboard/static/questionnaire.html`) : PHQ-9, GAD-7, questionnaire de sommeil rédigé pour le projet (non validé). Page publique, jeton à usage unique, seul le prénom est affiché.
3. `POST /api/psych/questionnaire/{token}` (`api/psych.py`, `questionnaire_submit`) → `clinical/psych.py`, `score_answers`, puis `internal/psych/questionnaire` sur le bus.
4. **Item 9** : `PsychAgent.on_questionnaire` — si l'item 9 du PHQ-9 est positif, notification critique à trois rôles (psychiatre, médecin de garde, infirmiers), candidat `psych_alert` (sévérité `critical` fixée par `severity_for`) et Telegram envoyé directement par la plateforme, **sans attendre ni n8n ni le LLM**.
5. **Score continu** : `PsychAgent.on_tick` → `evaluate` → `clinical/psych.py`, `compute` : pour dépression, anxiété et insomnie, somme de facteurs pondérés (questionnaire, expressions du visage, levers et toilettes la nuit, sommeil, constantes, antécédents, analyse comportementale).
6. **Bien-être** = 100 − (0,65 × score du trouble le plus marqué + 0,35 × moyenne des trois).
7. Sous `PSYCH_THRESHOLD` (50) : notification à `ALERT_ROLES`, candidat `psych_low_wellbeing`, explication par `psych-monitoring`.
8. Droits : les infirmiers voient le niveau et les consignes, pas les réponses (`view_psych_answers` réservé aux médecins et au psychiatre, `auth.py`).

Limite à dire : les compteurs d'observations sont en mémoire (`RoomSignals`) et repartent de zéro au redémarrage. Ce n'est jamais un diagnostic.

### (f) Ambulance

1. Fiche d'intervention dans la vue Ambulances (`js/views/ambulances.js`) → `POST /api/ambulances/missions` (`api/ambulances.py`, `create_mission`).
2. **Réservation** : `ambulance.py`, `choose_room(type d'urgence, chambres libres)`. Aucune chambre libre → refus 409.
3. `agents/ambulance.py`, `dispatch` : notifications à l'équipe, `set_reservation` (étiquette « Réservée — arrivée dans X min » dans `room_state`), briefing par le workflow `ambulance-dispatch`.
4. **GPS simulé** : `AmbulanceAgent.on_tick` (chaque seconde) avance sur une polyligne embarquée (`position_at`, `speed_kmh`), calcule l'ETA (`eta_seconds`), diffuse `ambulance/position`.
5. **GPS réel** : page `/ambulance/track/{jeton}` (`dashboard/static/ambulance-track.html`) ; le téléphone envoie sa position toutes les 2 s à `POST /api/ambulances/track/{jeton}` (`track_position`). La première position reçue fait passer la mission en mode GPS. HTTPS obligatoire sur le téléphone : tunnel Cloudflare ou certificat auto-signé (`docs/ambulance.md`).
6. **Arrivée** : à moins de `AMBULANCE_ARRIVAL_M` (60 m) ou par le bouton « Arrivé » → message `arrived` ; `js/ambulance-3d.js` joue l'entrée de l'ambulance et le brancard.
7. **Admission** : après `AMBULANCE_INSTALL_S`, `AmbulanceAgent.install` crée l'admission (`api/patients.py`, `_admit`), enregistre le patient dans l'état 3D et réactive la chambre dans le simulateur. Le questionnaire d'admission (pipeline e) suit.

Simulé : trajets, coordonnées de la clinique (fictives, à Tunis), temps accéléré en démo. Réel : la page GPS du téléphone.

### (g) Ordonnance de traitement et rappels de prise

1. Le médecin rédige l'ordonnance (`js/views/care.js`) → `POST /api/treatment-orders` (`api/care.py`, `create_order`). Chaque ligne est contrôlée par `_check` : allergie du patient et interactions simples (`clinical/diagnostics.py`, `interactions`).
2. Signature : `POST /api/treatment-orders/{id}/sign` (`sign_order`). Une ligne avec alerte d'allergie **bloque** la signature, sauf confirmation explicite du médecin, tracée (`audit(..., "sign", "treatment_order", ..., {"forced": ...})`).
3. `care.py`, `build_plan` génère les `MedicationDose` pour 72 h (`HORIZON_H`).
4. `MedicationAgent.on_tick` (`agents/care.py`, toutes les 3 s) : à l'heure → `reminder` ; retard > `MED_RELAUNCH_S` (30 min) → `relaunch` + candidat `medication_late` ; retard > `MED_ESCALATE_S` (60 min) → `escalation` au médecin de garde.
5. Prises conditionnelles (« si température > 38,5 °C ») : `MedicationAgent._conditional` crée la prise quand la condition est remplie et l'intervalle minimal respecté.
6. Le texte du rappel est composé par la plateforme ; le workflow `medication-reminders` n'ajoute qu'un point de vigilance. Le LLM ne peut réécrire ni dose ni horaire (`DECISIONS.md`, 21:58).
7. Administration : `POST /api/care-plan/doses/{id}/give` → `care.give` : prise enregistrée, stock de la pharmacie décrémenté, `AuditLog`.
8. Revérification du risque `medication_late` : `verify_risk` → `care.overdue_in_room` doit être vide.

L'ordonnance de sortie (V1) est distincte : `api/prescriptions.py`, `sign_prescription` — refus 409 en cas d'alerte allergie sauf `force=true`.

### (h) Panne d'équipement

1. Deux sources : le champ `fault{code,label}` d'un message `device` (contrat `device.json`), ou l'événement `machine_error` du pipeline d'Amal (`POST /api/yolo/event`, `POST /api/demo/trigger` → `state.process_event` → `internal/machine_error`).
2. `VitalsAgent.handle` : `equipment.is_fault` écarte l'occlusion et la poche vide d'une pompe (déjà couvertes par `iv_occlusion` / `iv_empty`) ; `equipment.register` range la panne dans `room_state["deviceFaults"]`.
3. `VitalsAgent.on_machine_event` rapproche le libellé d'Amal (« IV Pump ») de nos types par `equipment.device_type`.
4. `VitalsAgent.equipment_changed` publie **un seul** candidat `equipment_fault` par chambre. Sévérité : `high` si l'appareil est vital (`equipment.VITAL` : oxygène, ECG, oxymètre, transfusion, pompe à perfusion), `medium` sinon.
5. 3D : `js/equipment-faults.js` (bandeau « PANNE » en chambre, tableau dans la salle Équipements de l'étage 1) et indicateurs d'Amal (`avatars.js`, `scene.js`).
6. La panne ne se clôt pas seule : scénario `equipment_resolves.yaml`, puis `verify_risk` (« plus aucune panne dans `deviceFaults` »).

Simulé : toutes les pannes (action `device_fault` du simulateur).

### (i) Dossier médical

1. `medical_history.py`, `ensure_history` génère une fois, à l'initialisation, 9 à 15 ans d'historique **fictif** par patient ; `generate` est déterministe (graine = CRC32 du code patient).
2. API `dashboard/app/api/dossier.py` : `entries` (frise paginée, filtres, recherche `LIKE`), `entry`, `lab_series`, `profile`, `get_summary` / `regenerate_summary`.
3. **Accès par rôle** : `scope_of(user)` — médecins et psychiatre en écriture, infirmiers en lecture, réceptionniste identité et admissions seulement, pharmacien allergies et traitements. Filtrage côté serveur ; hors périmètre → 403.
4. **Traçabilité** : chaque lecture passe par `audit_read`, écrite dans une transaction courte séparée (`DECISIONS.md`, 21:10) ; l'impression est tracée aussi (`api/print.py`).
5. **Synthèse IA** : `summary_context` extrait un résumé déterministe (profil, valeurs anormales récentes, 14 documents récents) ; `orchestration.ask("record-summary", ...)` ; résultat stocké comme document `synthese` unique par patient.
6. Interface : `js/views/dossier.js` (frise, filtres, courbes Chart.js), bandeau `js/clinical-profile.js`.

---

## 3. Comment le LLM est appelé (commun à tous les agents)

```mermaid
flowchart TD
  A["Agent : orchestration.ask(workflow, ref, context)"] --> B{"n8n active et /healthz ok ?"}
  B -->|"oui"| C["POST /webhook/workflow + X-Hospital-Secret"]
  C --> D["n8n : prompt, Claude, validation JSON"]
  D --> E["POST /api/agents/result (jeton de service)"]
  B -->|"non"| F["_run_local : meme prompt (agents/specs.py)"]
  F --> G{"LLM_PROVIDER"}
  G -->|"anthropic"| H["API Anthropic directe"]
  G -->|"mock"| I["reponse deterministe spec.mock"]
  H -->|"erreur, delai, JSON invalide"| I
  E --> J["orchestration.deliver : gestionnaire de l agent + AgentLog"]
  H --> J
  I --> J
```

- Une seule source pour les prompts : `agents/specs.py` (`SPECS`, `build_prompt`, `validate`), utilisée par n8n (`n8n/build_agent_workflows.py`) et par le repli local.
- Trois niveaux de repli, tous visibles dans l'interface : n8n → plateforme → « réponse de secours (LLM indisponible) » (`agents/llm.py`, `FALLBACK_LABEL`). Les compteurs sont dans `orchestration.stats` et affichés par la Carte des agents (`GET /api/agents/map`).
- Délai maximal `LLM_TIMEOUT_S` (45 s) ; le client Anthropic est construit dans un thread et préchauffé (`manager.start`) pour ne pas bloquer la boucle asyncio.
- Sécurité des échanges avec n8n : la plateforme envoie `X-Hospital-Secret` ; n8n revient avec `Authorization: Bearer PLATFORM_SERVICE_TOKEN` (`auth.py`, `service_user_from_token`).

---

## 4. Ce que la V3 ajoute

> **État réel à la fin de la nuit (11/10)** — les mécanismes V3 décrits ci-dessous sont tous dans le dépôt et couverts par des tests
> automatiques. Ce qui a été lancé en conditions réelles et ce qui ne l'a pas été est dans `MORNING_REPORT.md`, section V3
> (tableau « Vérifié / non vérifié »). En résumé : HTTPS TLS 1.3, chiffrement AES-256-GCM, HMAC des trames, FHIR, pseudonymisation et
> SADM ont tourné ensemble sur un serveur de test ; **Docker n'a pas pu être exécuté**, MQTT sur TLS et un vrai Raspberry Pi **n'ont pas été testés**.


Les points d'accroche existent déjà : `main.py` charge, s'ils sont présents, les routeurs `api/fhir`, `api/integrity`, `api/sadm` ; `index.html` charge `js/v3/sadm.js`, `js/v3/fhir-export.js`, `js/v3/frame-integrity.js` ; `auth.py` contient la permission `view_identity`. Au moment de la rédaction, ces fichiers JavaScript sont des coquilles vides et les trois routeurs ne sont pas dans cet arbre de travail.

| Fonction | Où elle s'insère dans l'architecture | Interrupteur |
|---|---|---|
| Pseudonymisation | À la sortie : prompts LLM, webhooks n8n, Telegram, journaux → `PAT-0001`, chambre, âge, sexe, données cliniques | `PSEUDONYMIZE_OUTBOUND` (activé par défaut) |
| TLS | Devant l'API : uvicorn en HTTPS, TLS 1.3 minimum, certificat auto-signé (`scripts/make-cert.ps1` / `.sh`) | `HTTPS=true` |
| Chiffrement au repos | Entre les modèles et la base : AES-256-GCM (bibliothèque `cryptography`) sur l'identité, le contenu des documents du dossier, les réponses aux questionnaires | `DATA_ENCRYPTION_KEY` (absente : démarrage en clair avec avertissement) |
| Intégrité des trames | Dans l'ingestion, avant `contracts.validate` : `seq`, `ts`, `sig` = HMAC-SHA256 sur `topic + "\n" + JSON canonique` ; rejet des trames invalides, rejouées ou de plus de 30 s | `EDGE_HMAC_KEY` (absente : acceptées avec avertissement) |
| FHIR R4 | Nouvelle API de lecture `/fhir/...` au-dessus des modèles existants | `FHIR_ENABLED` |
| SADM | Sur chaque recommandation : indice de confiance, paramètres déclencheurs, boutons Valider / Rejeter tracés dans `AuditLog` | — |
| Docker | Autour de tout : `Dockerfile`, `docker-compose.yml` (services `platform`, `mosquitto`, profils `n8n` et `mssql`) | — |

Détail dans `docs/CONFORMITE.md`.

---

## 5. Bibliothèques réellement utilisées

Sources : `requirements.txt`, `edge/requirements.txt`, `computer_vision/requirements.txt`, les balises `<script>` de `dashboard/static/index.html` et les imports du code.

| Bibliothèque | Rôle | Où |
|---|---|---|
| FastAPI | API REST, WebSocket `/ws`, dépendances de permission | `dashboard/app/main.py`, `dashboard/app/api/*.py` |
| uvicorn | Serveur ASGI | `dashboard/serve.py` (écoute IPv4 et IPv6) |
| websockets | Support WebSocket d'uvicorn | dépendance de `uvicorn[standard]` |
| SQLModel / SQLAlchemy | Modèles et sessions ; `PRAGMA journal_mode=WAL` pour SQLite | `dashboard/app/models.py`, `db.py` |
| Pydantic | Validation des corps de requête, `CurrentUser` | `dashboard/app/api/*.py`, `auth.py` |
| PyJWT | Jetons de session (HS256) | `dashboard/app/auth.py` |
| bcrypt | Hachage des mots de passe (`rounds=10`) | `dashboard/app/auth.py` |
| passlib | **Installé mais inutilisé** (incompatibilité avec bcrypt ≥ 4.1) | `requirements.txt` ; `DECISIONS.md` 06:20 |
| httpx | Appels sortants asynchrones : n8n, Telegram, relais du flux caméra | `dashboard/app/n8n.py`, `notify/telegram.py`, `api/camera.py` |
| aiomqtt | Client MQTT asynchrone du serveur | `dashboard/app/ingest/mqtt.py` |
| paho-mqtt | Client MQTT de l'edge | `edge/transport/__init__.py` (`MqttTransport`) |
| requests | Repli HTTP de l'edge et du simulateur autonome | `edge/transport/__init__.py` (`HttpTransport`), `simulator/sim.py` |
| jsonschema | Validation des messages contre `contracts/schemas` | `dashboard/app/contracts.py` |
| PyYAML | Scénarios du simulateur, configuration de l'edge | `simulator/engine.py`, `edge/main.py` |
| Jinja2 | Pages d'impression A4 | `dashboard/app/api/print.py`, `dashboard/templates/print/` |
| python-multipart | Formulaires FastAPI | `requirements.txt` |
| python-dotenv | Lecture de `.env` | `dashboard/app/config.py` |
| anthropic (SDK) | Appel de Claude quand `LLM_PROVIDER=anthropic` | `dashboard/app/agents/llm.py` (`AnthropicLlm`) |
| numpy | Calculs sur les images et les séries | `edge/`, `computer_vision/src/` |
| Ultralytics YOLO | Détection du patient et de sa posture | `computer_vision/src/detection/patient_detector.py`, `edge/vision/pipeline.py` |
| PyTorch / torchvision | Moteur de YOLO ; Vision Transformer optionnel (DINOv2) | `computer_vision/src/transformer/`, `behavior.py` — non installé dans le `.venv` du serveur |
| OpenCV | Lecture caméra, flou de l'aperçu, dessin | `edge/main.py`, `dashboard/camera_loop.py` |
| onnxruntime | Expression du visage (FER+), optionnel | `edge/vision/expression.py` |
| gpiozero, adafruit-mlx90640, adafruit-dht, blinka | Pilotes GPIO, caméra thermique, DHT22 — import paresseux, simulation si absents | `edge/actuators/`, `edge/thermal/mlx90640.py`, `edge/sensors/` |
| vitaldb | Rejeu optionnel de constantes réelles anonymes ; sinon synthétique | `simulator/vitaldb_replay.py` |
| pytest, pytest-asyncio | Tests | `dashboard/tests`, `edge/tests`, `simulator/tests`, `computer_vision/tests` |
| Three.js r128 + OrbitControls | Jumeau numérique 3D | `dashboard/static/js/scene.js`, `floors.js` (chargés depuis un CDN) |
| Chart.js 4.4.1 | Courbes des constantes et de la biologie | `js/views/devices.js`, `js/views/dossier.js` |
| Leaflet 1.9.4 + tuiles OpenStreetMap | Carte des ambulances | `js/views/ambulances.js` |
| n8n | Orchestration du raisonnement, attentes, escalades, Telegram | `n8n/workflows/*.json`, `n8n/setup_n8n.py` |
| Mosquitto 2 | Broker MQTT | `docker-compose.yml`, `docker/mosquitto.conf` |
| cryptography | AES-256-GCM, certificat TLS (V3, **activable**) | `dashboard/app/crypto.py`, `scripts/make_cert.py` (dans `requirements.txt` ; import paresseux : la plateforme démarre sans) |
| Docker / Compose | Conteneurisation (V3) | `Dockerfile`, `docker-compose.yml` |

---

## 6. Choix techniques et alternatives

Chaque raison vient de `DECISIONS.md` ou de `PROMPT.md` (section « Replis décidés d'avance »). L'inconvénient est celui qu'il faut reconnaître devant le jury.

**SQLite plutôt que SQL Server ou PostgreSQL.** Raison : un seul fichier, zéro installation, la démo démarre avec une commande ; SQL Server reste possible par `DATABASE_URL` (`db.py`). Inconvénient : un seul écrivain à la fois — nous avons eu un verrou (transaction ouverte pendant un `await`, corrigé, `PROGRESS_V2.md` étape 1) ; SQL Server n'a **jamais été testé** (`MORNING_REPORT.md` §3) ; PostgreSQL n'est pas prévu.

**MQTT avec repli HTTP.** Raison : MQTT est le standard IoT (léger, publication/abonnement, QoS) ; mais la démo doit marcher sans broker (`DECISIONS.md` 05:42), d'où `POST /api/ingest` avec un traitement strictement identique. Inconvénient : deux chemins à maintenir ; la nuit du développement, Docker était arrêté, donc **tout a tourné en repli HTTP** ; le broker de `docker/mosquitto.conf` accepte les connexions anonymes sur 1883.

**Règles Python déterministes plutôt qu'un LLM pour détecter.** Raison : latence, fonctionnement hors ligne, reproductibilité, et surtout sécurité — « un LLM ne doit jamais clôturer seul une chute » (`DECISIONS.md` 14:20). Le LLM explique, synthétise, propose. Inconvénient : les règles sont rigides, chaque nouveau cas clinique doit être codé, et leurs seuils n'ont pas été validés cliniquement.

**n8n plutôt qu'une orchestration tout en code.** Raison : attentes longues, escalades, envoi Telegram et appels LLM visibles et modifiables sans redéployer ; chaque exécution est consultable. Inconvénient : un service de plus ; précision de quelques secondes sur le nœud Wait ; n8n résout `localhost` en IPv6 (corrigé par `127.0.0.1`). C'est pourquoi tout a un repli local (`orchestration._run_local`).

**Traitement vidéo en bordure (edge) plutôt que dans le cloud.** Raison : vie privée — aucune image ne quitte la chambre, seulement des états JSON ; et les règles locales marchent sans réseau. Inconvénient : puissance limitée du Pi, un boîtier à installer et maintenir par chambre ; performance sur Pi **non mesurée** (les seuls chiffres du dépôt viennent d'un GPU de PC portable, `computer_vision/reports/benchmark_results.json`).

**JavaScript sans framework.** Raison : le jumeau 3D d'origine (Three.js r128 en global) devait être étendu sans être réécrit (`PROMPT.md`, règle de non-régression 3D) ; les ajouts sont additifs (`room-live.js` enveloppe `AvatarManager.update`, `DECISIONS.md` 08:00). Inconvénient : beaucoup de fichiers, état global, pas de composants ni de typage ; les bibliothèques viennent d'un CDN, donc le navigateur a besoin d'Internet.

**Simulateur.** Raison : pas d'appareils médicaux ni de patients réels ; il fallait une démo sans Pi, sans broker, sans clé LLM (`DECISIONS.md` 05:45). Il produit les mêmes messages de contrat que le vrai matériel, donc le reste du système ne voit pas la différence. Inconvénient : des données synthétiques ne prouvent rien cliniquement ; nous avons dû réduire le bruit simulé pour éviter de fausses alertes (`DECISIONS.md` 00:55).

**Bus asyncio interne plutôt que Kafka ou RabbitMQ.** Raison : un seul processus, aucune dépendance ; une file bornée par abonné qui jette le plus ancien message plutôt que de bloquer une source (`bus.py`, `publish`). Inconvénient : rien n'est persistant ni distribué — un redémarrage perd les messages en transit et l'état en mémoire (`room_state`, compteurs des agents) ; passer à plusieurs serveurs demanderait un vrai broker.

**Claude comme LLM.** Raison : sorties JSON structurées validées, bon français ; fournisseur isolé derrière `BaseLlm` (`agents/llm.py`), interchangeable avec `MockLlm`. Inconvénient : service payant hébergé à l'étranger — c'est précisément ce qui nous a bloqués (crédit épuisé) ; d'où le mode `mock` et la pseudonymisation des données sortantes.

**Persistance sous-échantillonnée.** Raison : plusieurs dizaines d'appareils à 1 Hz rempliraient la base ; on garde 1 valeur toutes les 10 s en base et 15 min à 1 Hz en mémoire (`DECISIONS.md` 07:10). Inconvénient : pas d'archive à la seconde.

---

## 7. Qui répond à quoi

Les noms ne sont pas inventés : seul le rôle d'Amal est documenté dans le dépôt (`AMAL_SYNC.md` : jumeau 3D et vision). Répartissez les autres rôles entre vous.

| Sujet de la question | Rôle | Fichiers à connaître | Doc à relire |
|---|---|---|---|
| Jumeau 3D, étages, visite à pied | Amal (3D) | `js/scene.js`, `js/floors.js`, `js/avatars.js` | `AMAL_SYNC.md`, `docs/EXISTING.md` |
| Vision : YOLO, suivi, chute, transformer | Amal (vision) | `computer_vision/src/`, `computer_vision/reports/*.md` | `computer_vision/README.md` |
| Edge Raspberry Pi, capteurs, règles locales | Vision / edge | `edge/main.py`, `edge/safety/local_rules.py`, `edge/transport/__init__.py` | `MORNING_REPORT.md` §4 |
| Ingestion, bus, agents, base | Backend / agents | `ingest/handler.py`, `bus.py`, `agents/*.py`, `models.py` | ce document, §2 |
| Extensions temps réel de la 3D et vues métier | Front | `js/room-live.js`, `js/views/*.js`, `js/equipment-faults.js` | `docs/demo_v2.md` |
| n8n, prompts, LLM, replis | n8n / IA | `orchestration.py`, `agents/specs.py`, `n8n.py`, `n8n/workflows/` | `n8n/README.md` |
| Auth, rôles, audit, TLS, AES, HMAC, pseudonymisation, RGPD / INPDP | Sécurité / conformité | `auth.py`, `audit.py`, fichiers V3 | `docs/CONFORMITE.md` |
| NEWS2, SpO2, fièvre, prédictions, psychologie, ordonnances | Clinique | `clinical/*.py`, `agents/fever.py`, `agents/psych.py` | ce document, §2 b à g |
| Coûts, déploiement, feuille de route | Porteur du projet | — | `docs/DEPLOIEMENT.md` |
| Questions pièges | Tous | — | `docs/QA_JURY.md` |

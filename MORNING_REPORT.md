# Rapport du matin — Hospital Copilot (HackCure)

Branche : `feat/platform` (dépôt `Firas-Bennani/Hospital_copilot`). `master` = code d'origine d'Amal intact.
Tout a été fait en autonomie dans la nuit du 10/10/2026 ; décisions dans `DECISIONS.md`, blocages dans `BLOCKERS.md`, avancement dans `PROGRESS.md`.

## 1. Lancer la plateforme (une seule commande)

```powershell
# Windows
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\run-demo.ps1 -Reset          # crée .venv si besoin, copie .env.example → .env, démarre http://localhost:8000
# option : .\scripts\run-demo.ps1 -Edge   → lance aussi un faux Raspberry Pi (edge --fake) pour la chambre 101
```
```bash
# Linux / macOS
./scripts/run-demo.sh --reset           # ./scripts/run-demo.sh 8000 --edge pour le faux Pi
```
À la main : `cd dashboard && ..\.venv\Scripts\uvicorn server:app --host 0.0.0.0 --port 8000` (le point d'entrée `server:app` est conservé).

Tests : `.venv\Scripts\python -m pytest dashboard/tests computer_vision/tests edge/tests simulator/tests -q`
(140 tests : 92 dashboard dont le test d'intégration `fall_demo → nurse_resolves` et 8 tests n8n, 13 vision, 24 edge, 11 simulateur ; les tests n'appellent ni n8n ni l'API Anthropic).

## 2. Identifiants (mot de passe commun `hackcure2026`, variable `DEMO_PASSWORD`)

| Identifiant | Rôle | Ce qu'il voit / fait |
|---|---|---|
| `owner` | Propriétaire | Tout + gestion des utilisateurs |
| `medecin` | Médecin généraliste | Tout : rapports, ordonnances (signer, imprimer), commandes |
| `medecin_garde` | Médecin de garde | Idem médecin ; destinataire des escalades |
| `infirmier` | Infirmier | 3D + commandes d'équipements, centre de commande (plans, « Marquer résolu »), rapport de garde, patients (modifier), documents en lecture |
| `receptionniste` | Réceptionniste | Patients (CRUD, admission/sortie), vues en lecture |
| `pharmacien` | Pharmacien | Pharmacie (CRUD médicaments, traitements) + jumeau 3D seulement |

## 3. Ce qui marche / est simulé / manque

**Fonctionne (vérifié par tests + captures Playwright dans `docs/screenshots/`)**
- Jumeau 3D d'origine intact (boutons de démo, Demo/Real, CCTV, zoom) + extensions additives : poses `sitting_up / sitting_edge / standing / walking / sitting_chair / absent (badge WC / Hors chambre)`, icône d'expression, halo thermique, avatar infirmier, fenêtre / radiateur / clim / veilleuse animés, étiquettes potence + moniteur avec **vraies constantes**, liseré de risque vert/orange/rouge/violet, bandeau KPI.
- Ingestion MQTT (aiomqtt, auto-reconnexion) **et** repli HTTP `POST /api/ingest`, validation JSON Schema (`contracts/`), `room_state` temps réel.
- Simulateur : chambres 102–104 + appareils des 4 chambres, 8 scénarios YAML, VitalDB (si réseau + paquet) sinon synthétique ; **embarqué** dans le serveur (zéro processus en plus) et autonome (`simulator/sim.py`).
- 6 agents (Vision, Vitals + NEWS2, Environment, Risk + plan LLM/mock, FollowUp, Report) : journal temps réel (📥 → 🧠 → ✅), dédup, escalades, résolution **vérifiée**, levée automatique des signaux transitoires.
- Notifications in-app (cloche + toasts) ; **Telegram** actif avec le `.env` déposé par l'équipe (vérifié : messages reçus `200 OK` pendant la démo `full_demo`).
- Auth JWT cookie, 6 rôles, permissions côté serveur + UI filtrée, audit de toute modification.
- Dossier patient, historique, pharmacie (stock/péremption/allergènes), ordonnance avec **alerte allergie**, rapport médecin (brouillon IA), rapport de garde IA (avec **humeur**), pages d'impression A4 (`/print/prescription/{id}`, `/print/report/{id}`, `/print/shift/{id}`).
- Edge Raspberry Pi complet avec simulation automatique de tout le matériel absent ; `--fake` testé de bout en bout sur PC (règles locales, alarme, commandes aller-retour via MQTT ou long-poll HTTP).

**Simulé / dégradé (par choix, voir DECISIONS.md)**
- LLM : réel par défaut (`LLM_PROVIDER=anthropic`, `claude-sonnet-5-5`) — avec n8n en ligne, plans, vérifications et rapports de garde sont rédigés par Claude **dans n8n** ; n8n arrêté, la plateforme appelle l'API elle-même. `/health` affiche `llm: ok|error`. En cas d'échec, « réponse de secours (LLM indisponible) » est affiché ; `LLM_PROVIDER=mock` reste pour les tests. Le SDK est chargé hors boucle et préchauffé (un blocage de ~55 s au premier risque a été corrigé dans la nuit).
- Pas de broker cette nuit (Docker Desktop arrêté) : tout a tourné en repli HTTP. `docker compose up -d` active Mosquitto sans autre changement.
- Poids YOLO absents du dépôt : l'edge bascule sur le modèle pose pré-entraîné (téléchargement Ultralytics) puis `--fake`. Le chemin « poids entraînés » (`CanonicalPipeline` → `computer_vision/src`) est codé mais n'a pas pu être exécuté sans les `.pt`.
- Caméra thermique, DHT22, GPIO : pilotes écrits, simulés ici (pas de Pi).
- Aperçu caméra 101 : proxy MJPEG flouté si `EDGE_CAMERA_URL` ; sinon vue schématique.

**Attention — `.env`** : le fichier `.env` présent à la racine (non commité) contient la clé Anthropic, le jeton Telegram et les variables `N8N_*` de ce projet (secret des webhooks, jeton de service, clé d'API n8n). Ne pas le pousser sur GitHub.

**Manque / à faire si temps**
- Tests réels sur le Pi (voir §4), calibration du lit, FER+ (`python edge/download_ferplus.py`).
- SQL Server : supporté par `DATABASE_URL=mssql+pyodbc://…` mais non testé (pas de serveur dispo).
- Les chaînes internes de `dashboard-ui.js` (journal legacy) restent en anglais (fichier existant non réécrit).

## 4. Brancher le vrai Raspberry Pi 5 (chambre 101)

```bash
sudo apt install -y python3-venv libatlas-base-dev libcamera-apps i2c-tools   # + raspi-config : I2C on, caméra on
git clone https://github.com/Firas-Bennani/Hospital_copilot.git && cd Hospital_copilot && git checkout feat/platform
python3 -m venv .venv && .venv/bin/pip install -r edge/requirements.txt
python edge/download_ferplus.py                     # optionnel (expression)
nano edge/config/room101.yaml                       # server.url = http://<PC>:8000 ; mqtt.host = <PC> ou "" (HTTP seul)
.venv/bin/python edge/main.py --show                 # test avec fenêtre ; Ctrl+C
sudo cp edge/systemd/hackcure-edge.service /etc/systemd/system/ && sudo systemctl enable --now hackcure-edge
```
- **Calibration du lit / zones** : `python edge/calibrate_zones.py --source 0` → clic pour dessiner `bed`, `n` pour passer à `bathroom_door` puis `exit`, `s` pour sauver dans `room101.yaml`. Le point testé est le bas-centre de la boîte (ou les hanches avec un modèle pose), hystérésis 2 s.
- **Thermique** : MLX90640 sur I²C (SDA GPIO2, SCL GPIO3, 3,3 V). Calibration : `calibration_offset_c` dans le yaml ou `ThermalCamera.calibrate(ref)` ; `calibrated=false` tant que rien n'est réglé.
- **Câblage GPIO (BCM)** : DHT22 → GPIO4 ; bouton d'appel → GPIO22 (vers GND, pull-up interne) ; contact de porte → GPIO5 ; buzzer → GPIO17 ; veilleuse (LED/relais) → GPIO27 ; LED chauffage → GPIO23 ; LED clim → GPIO24 ; servo fenêtre → GPIO18 (PWM, alim 5 V séparée, masse commune).
- Côté serveur : rien à changer. Dès que l'edge parle (`source: edge-*`), la chambre 101 passe en vision réelle et le simulateur embarqué ne garde que les appareils. `EDGE_CAMERA_URL=http://<pi>:8080/stream` pour l'aperçu flouté.
- Sans broker : l'edge interroge `GET /api/edge/commands` ; avec Mosquitto : abonnement `hackcure/room/101/cmd/+`.

## 5. Script de démo de 3 minutes
Voir `docs/demo.md` (minuté). Résumé : zoom 101 → **Lancer la démo → full_demo** → lever (risque « lever non accompagné », veilleuse) → chute (chambre violette, VisionAgent → RiskAgent critical + plan, notifications) → centre de commande (plan coché) → infirmier entre (avatar, in_progress, StaffVisit) → sort → FollowUpAgent vérifie → résolu → fièvre (halo, VitalsAgent) → rapport de garde + impression → ordonnance avec alerte allergie.

## 6. n8n — orchestration réelle (démarrage, import, démo)

La plateforme détecte ; **n8n orchestre la réponse** avec de vrais appels à l'API Anthropic et à Telegram. Détails : `n8n/README.md`.

**Démarrage**
```powershell
npx n8n                                   # http://localhost:5678 (déjà lancé sur cette machine)
.\n8n\import.ps1                          # crée/met à jour les 4 credentials, importe et ACTIVE les 4 workflows (rejouable)
.\n8n\import.ps1 -Check                   # doit afficher 4 × ACTIF
.\scripts\run-demo.ps1 -Reset             # plateforme ; /health doit afficher "n8n": "online" et "llm": "ok"
```
Déjà fait cette fois-ci : les credentials « Hospital Copilot — … » et les workflows `risk-triage`, `risk-verify`, `shift-report`, `pharmacy-alerts` existent et sont actifs dans n8n. Les workflows de l'autre projet présents dans la même instance n'ont pas été touchés.

**Port 8000 occupé** : un autre projet (`Industrial_Copilot`) écoute sur le port 8000 de cette machine. Soit l'arrêter avant la démo, soit lancer `.\scripts\run-demo.ps1 -Port 8010` (le script transmet l'URL à n8n) et, pour les déclencheurs Cron, `.\n8n\import.ps1 -PlatformUrl http://localhost:8010`.

**Ce que fait chaque workflow**
- `risk-triage` (webhook `risk-created`) : Claude rédige l'explication et le plan → plan déposé sur la plateforme → Telegram infirmier → attente de « Je prends en charge » (2 / 10 / 30 min) → sinon escalade + Telegram médecin de garde.
- `risk-verify` (webhook `staff-left`) : attente 2 min → état réel de la chambre → Claude dit si le risque est résolu (avec le contrôle déterministe comme garde-fou) → `resolved` ou risque persistant → Telegram.
- `shift-report` (Cron 07:45 / 19:45 + bouton « Générer ») : rapport de garde par chambre rédigé par Claude → brouillon sur la plateforme → Telegram avec le lien d'impression.
- `pharmacy-alerts` (Cron 08:00 + bouton de la vue Pharmacie) : stock sous le seuil, péremption < 30 j → Telegram pharmacien.

**Dans l'interface** : badge « n8n · orchestration » et bouton **Ouvrir n8n** (médecins, owner) dans la barre du haut ; cartes `n8n:<workflow>` et fil des étapes dans le panneau Agents ; étiquette « orchestré par n8n » et bouton **🙋 Je prends en charge** dans le Centre de commande. n8n arrêté ⇒ badge « n8n hors ligne · repli local » et les agents Python reprennent la main (plan, Telegram, escalade, re-vérification). Captures : `docs/screenshots/10-n8n-agents.png`, `11-n8n-commande.png`.

**Test réel joué le 10/10/2026** (n8n 2.40.7, `claude-sonnet-5-5`, vrai bot Telegram, plateforme sur le port 8010, délais raccourcis : `ESCALATION_CRITICAL_S=8`, `FOLLOWUP_RECHECK_S=20`) :

| Vérification | Résultat | Preuve (API n8n `/api/v1/executions`) |
|---|---|---|
| Plan d'action rédigé par l'API Anthropic via n8n, pas par le secours | ✅ 6 étapes, fournisseur affiché « anthropic claude-sonnet-5-5 (n8n) » | `full_demo` : exéc. 124 (réponse `msg_011CftcHwp8…`) ; `fall_demo` : exéc. 141 (`msg_011CftdjwX6…`) |
| Telegram envoyé | ✅ `ok: true` sur les nœuds Telegram (infirmier, médecin de garde, confirmation) | exéc. 124, 126, 141, 142 |
| Escalade sans acquittement | ✅ risque `escalated`, Telegram médecin de garde | exéc. 124 (`full_demo`), 141 (`fall_demo`) |
| `resolved` par `risk-verify` après la sortie de l'infirmier | ✅ « n8n:risk-verify (vérifié) — plus au sol : posture lying_bed… » | exéc. 126 (`full_demo`), 142 (`nurse_resolves`) |
| « Je prends en charge » lève l'attente | ✅ `n8n_resumed: true`, exécution terminée sur « acquitté » | exéc. 127 |
| Rapport de garde et alertes pharmacie | ✅ rapport rédigé par Claude, page d'impression 200 ; Telegram pharmacien | exéc. 143, 144 |

À savoir :
- `full_demo` a été joué 4 fois. L'escalade n'a eu lieu que dans un passage (exéc. 124) : l'infirmier entre 30 s après la chute, ce qui vaut prise en charge, et le nœud Wait de n8n n'est pas précis à la seconde (avec un délai de 8 s, l'escalade est arrivée 12 à 20 s après le plan). Le dernier passage, avec le code final, a été fait sur `fall_demo` puis `nurse_resolves` (exéc. 141 et 142).
- Avec les délais normaux (2 min), `full_demo` ne montre donc **pas** l'escalade. Pour la montrer au jury : `fall_demo` sans rien toucher pendant 2 min (ou `ESCALATION_CRITICAL_S=20` avant de lancer la plateforme).
- Le premier passage a échoué : n8n ne joignait pas la plateforme (`localhost` résolu en IPv6). Corrigé dans les workflows (`127.0.0.1`).
- Dans un passage, une coupure réseau de quelques secondes a fait échouer l'appel Anthropic depuis n8n (`socket hang up`) : le workflow a continué avec le plan de secours, affiché « secours (LLM indisponible) via n8n ». Dans un autre, une réponse de vérification tronquée a déclenché le même repli ; la limite de tokens a été relevée depuis et le passage suivant (exéc. 142) a été rédigé par Claude.
- Rejouer le test : lancer la plateforme, **Lancer la démo → fall_demo**, attendre l'escalade, puis **nurse_resolves** ; suivre dans n8n → Executions, ou `curl -H "X-N8N-API-KEY: …" "http://localhost:5678/api/v1/executions?limit=10"`.

## 7. Résumé de BLOCKERS.md
| Blocage | Repli |
|---|---|
| Docker Desktop arrêté → pas de Mosquitto | Repli HTTP + simulateur embarqué ; MQTT optionnel (`docker compose up -d`) |
| Poids YOLO absents du dépôt | Repli pose pré-entraîné puis `--fake` ; pipeline canonique codé mais non exécuté |
| Pas de Pi / capteurs / Telegram / clé Anthropic | Simulation automatique ; Telegram et Anthropic activés par variables d'environnement |
| Port 8000 occupé par un autre projet sur cette machine | Test réel sur le port 8010 ; `run-demo.ps1 -Port 8010` + `import.ps1 -PlatformUrl …` (voir §6) |
| `computer_vision/src/datasets/` absent du dépôt source (ignoré par `.gitignore`) | Module `harmonize.py` reconstruit (tests CV verts) ; données `computer_vision/data/**` intactes |

---

# V2 — rapport (branche `feat/v2`)

`feat/platform` reste la version de démo sûre (V1, non modifiée). La V2 est sur **`feat/v2`** ; avancement dans `PROGRESS_V2.md`,
décisions dans `DECISIONS.md`, synchronisation des travaux d'Amal dans `AMAL_SYNC.md`, script de démo dans **`docs/demo_v2.md`**.

## V2.1 Commandes

```powershell
git checkout feat/v2
.\scripts\run-demo.ps1 -Reset             # http://localhost:8000 — -Reset obligatoire la première fois (nouvelles tables et données)
.\scripts\run-demo.ps1 -Port 8010 -Reset  # si le port 8000 est pris par un autre projet
npx n8n                                     # puis, dans un autre terminal :
.\n8n\import.ps1                           # importe et active les 15 workflows (-Check pour vérifier, -PlatformUrl http://127.0.0.1:8010 si besoin)
.venv\Scripts\python -m pytest dashboard/tests computer_vision/tests edge/tests simulator/tests -q   # 215 tests
```
Linux / macOS : `./scripts/run-demo.sh --reset`, `./n8n/import.sh`.
Démo : bouton **Lancer la démo → `full_demo_v2`** (8 min, tout est joué automatiquement) ; version jury de 3 minutes dans `docs/demo_v2.md`.

## V2.2 Comptes de démonstration (mot de passe `hackcure2026`)

| Identifiant | Rôle | Nouveautés V2 |
|---|---|---|
| `owner` | Propriétaire | Tout, dont la Carte des agents et le lancement des démos |
| `medecin` | Médecin généraliste | Dossier médical (écriture), diagnostics live, ordonnance de traitement, prédictions, psychologie en lecture complète |
| `medecin_garde` | Médecin de garde | Idem + destinataire des fièvres vraies, des prédictions critiques, des prises en retard > 60 min |
| `infirmier` | Infirmier | Plan de soins (administrer), fil médecin ↔ infirmier, dossier en lecture, psychologie : état et consignes seulement |
| `psychiatre` | **Psychiatre (nouveau)** | Voit toute la plateforme ; écrit la psychologie (prescriptions psychothérapeutiques) et le dossier ; reçoit l'alerte « item 9 » |
| `receptionniste` | Réceptionniste | Ambulances (fiche d'intervention, départ), admissions ; dossier : identité et admissions |
| `pharmacien` | Pharmacien | Pharmacie ; dossier : allergies et traitements |

## V2.3 Ce qui marche (vérifié par tests et captures `docs/screenshots/v2/`)

- **Travaux d'Amal intégrés** (étage 1, modes RDC / Étage 1 / Tout / Éclaté, visite à pied, risque comportemental) ; synchronisation re-jouable.
- **Environnement** : fenêtre, radiateur, clim et veilleuse réellement animés dans les 4 chambres, par un humain, un agent ou n8n.
- **Boucle soignant pour tous les scénarios** : un risque clinique ne se lève jamais seul ; « Je prends en charge » → le bon soignant entre (infirmier, médecin de garde, psychiatre) → il sort → revérification déterministe → « résolu et vérifié ». 15 scénarios de résolution.
- **SpO2** de premier plan (seuils standard et BPCO, NEWS2 échelle 2, KPI, oxymètre dans chaque chambre).
- **Fièvre vraie ≠ hausse thermique** : température centrale confirmée → médecin de garde → bilan clinique → bilan biologique validé → confort ensuite → résultats au dossier. Chambre chaude : confort seul, sans alerte.
- **Dossier médical** : 9 à 15 ans d'historique fictif par patient, frise, filtres, recherche, courbes biologiques, synthèse IA, impression, accès par rôle et audit.
- **Diagnostics live**, fil médecin ↔ infirmier, **ordonnance de traitement** (allergies bloquantes, interactions), **plan d'administration**, rappels / relances / escalade, stock décrémenté, **comptes rendus d'intervention** à signer.
- **Psychologie** : questionnaire d'admission sur tablette (PHQ-9, GAD-7, sommeil), alerte immédiate item 9, score de bien-être, prescriptions.
- **Prédictions** : 5 conditions, risque 0–100, fenêtre de temps estimée, confiance, facteurs ; glucomètre et segment ST simulés.
- **Ambulances** : carte Leaflet, ETA en continu, chambre réservée dès le départ, GPS simulé **et** GPS réel par téléphone, arrivée en 3D, admission.
- **n8n** : un workflow par agent — 13 agents, **15 workflows actifs**, chacun avec une exécution réelle vérifiée ; repli local automatique ; vue **Carte des agents**.
- **`full_demo_v2`** : scénario de 8 min avec pilote automatique (`dashboard/app/demo_v2.py`) ; test d'intégration `dashboard/tests/test_v2_full_demo.py`. **Passages réels** sur le port 8010 (n8n, Telegram) : trois passages complets de `full_demo_v2` ; au dernier (exécutions n8n 361–412) les 11 gestes du pilote sont joués, la mission est admise, le questionnaire rempli, le parcours fièvre mené au bout, la prise administrée, et 16 des 17 risques ouverts pendant la démo (fièvre, prédictions, NEWS2, chute, bien-être…) finissent « résolus et vérifiés », sans réouverture ; le dernier est un « sortie du lit » de fond en 101 (patient au fauteuil), hors scénario. Les deux premiers passages ont obtenu des réponses de Claude validées (14 exécutions : `risk-triage`, `fever-pathway`, `diagnostics-live`, `ambulance-dispatch`, `psych-monitoring`, `vision-watch`) ; **au dernier, l'API Anthropic a répondu « credit balance is too low » : tous les textes d'IA sont des réponses de secours** (voir `BLOCKERS.md`). La détection, la sévérité et la vérification, déterministes, n'en dépendent pas.

**Synchronisation Amal du 11/10 (`384ae87`, `12e1eb2`)**
- **Panne de machine** (`machine_error`) : reliée à nos appareils. L'événement d'Amal (bouton « Panne machine », `/api/yolo/event`) **et** le flux d'un appareil (champ `fault` du contrat `device`) donnent le même risque **« Panne d'équipement »** (un par chambre, élevé si l'appareil est vital), affiché sur l'appareil dans la chambre et dans la **salle Équipements de l'étage 1**, notifié à l'infirmier, avec son scénario de résolution `equipment_resolves`. Pas de doublon avec `iv_empty` / `iv_occlusion`. Scénario `machine_error_103` ; une panne est aussi jouée dans `full_demo_v2`.
- **Analyse comportementale optionnelle** : `risk_analyzer` et `agent_adapter` d'Amal, assemblés par `computer_vision/src/behavior.py`, alimentent `behavioral_risk` depuis l'edge et `camera_loop.py` (nouveau message `vision/behavior`) → VisionAgent → risque, et un facteur du PsychAgent (agitation, immobilité prolongée). `camera_loop.py` est la fusion de sa réécriture et de notre publication aux contrats.
- **Vision Transformer (DINOv2)** : code intégré, **non exécuté ici** — les poids entraînés ne sont pas dans le dépôt et PyTorch n'est pas installé dans `.venv`. Le repli est automatique et testé : l'analyse tourne sur le détecteur seul, sans erreur, sans téléchargement. Pour l'activer : installer PyTorch, déposer `computer_vision/runs/patient_transformer/best_transformer.pt` et avoir le backbone dans le cache torch hub.
- Vérifié avec `LLM_PROVIDER=mock` et `N8N_ENABLED=false` (pas de crédit d'API) : 215 tests verts, captures `84` (non-régression RDC / étage 1 / éclaté) et `85…88` (panne de machine).

## V2.4 Ce qui est simulé

- **Toutes les données patients sont fictives** (identités, historique de 15 ans, biologie, imagerie) et générées de façon déterministe.
- **Appareils** : oxymètre, glucomètre, ECG / ST, perfusion, température centrale, ambiance — tous simulés (seule la chambre 101 peut recevoir un vrai Raspberry Pi).
- **Pannes d'appareil** : simulées (action `device_fault` du simulateur) ; aucun appareil réel n'est branché.
- **Résultats de laboratoire** : simulés (délai `FEVER_LAB_DELAY_S`, 30 s en démo), cohérents avec le tableau clinique.
- **Soignants** : en simulation, « Je prends en charge » fait entrer un soignant virtuel ; dès qu'un edge réel parle pour la chambre, rien n'est simulé.
- **Dans `full_demo_v2`**, les gestes humains (sortie, départ de l'ambulance, questionnaire, bilan clinique, validation, ordonnance, administration, prise en charge) sont joués par le pilote **à travers l'API**, et tracés « Démo V2 — geste simulé ».
- **Ambulance** : trajets embarqués (polylignes), temps accéléré × 6 en démo ; le GPS réel demande HTTPS sur le téléphone (voir `docs/ambulance.md`).
- **Prédictions** : règles pondérées et extrapolation linéaire — « Estimation de prototype, non validée cliniquement ». Le niveau de confiance mesure la quantité de données, pas une probabilité.
- **Questionnaire de sommeil** : rédigé pour le projet (non validé). PHQ-9 et GAD-7 sont les échelles standard.
- Détection et sévérité restent **déterministes en Python** ; le LLM explique, synthétise, propose. Chaque résultat d'IA porte « Aide à la décision — validation médicale requise ».

## V2.5 Points d'attention

- Une base créée avant la V2 doit être recréée (`-Reset`) : nouvelles tables, patients, médicaments et historique.
- Sur cette machine le port 8000 est occupé par un autre projet : les tests réels de la V2 ont été faits sur le port 8010.
- Navigateur sans carte graphique : la 3D est lente (le serveur n'est pas en cause).
- `.env` (clé Anthropic, Telegram, `N8N_*`) n'est jamais commité ; les JSON de `n8n/workflows/` ne contiennent aucun secret.

---

# V3 — conformité au cahier des charges (nuit du 10 au 11/10, branche `feat/v2`)

Points de retour : tags `v2-stable` et `v2-pre-conformite`. Avancement : `PROGRESS_V3.md` (8 étapes cochées). Décisions : `DECISIONS.md`.
Tout a été développé et testé **sans crédit d'API** : `LLM_PROVIDER=mock`, `N8N_ENABLED=false`.

## V3.1 Ce qui est actif par défaut, et ce qu'il faut activer

| Mécanisme | Par défaut | Pour l'activer | Si la clé ou le certificat manque |
|---|---|---|---|
| Pseudonymisation de ce qui sort (LLM, n8n, Telegram, journaux) | **actif** | `PSEUDONYMIZE_OUTBOUND=1` | — |
| Identité complète réservée aux rôles `view_identity` | **actif** | — | — |
| Journal d'audit avec adresse IP | **actif** | — | — |
| SADM (indice de confiance, déclencheurs, Valider / Rejeter, bandeau) | **actif** | `SADM_ENABLED=1` | — |
| API FHIR R4 en lecture + bouton « Exporter en FHIR » | **actif** | `FHIR_ENABLED=1` | — |
| HTTPS, TLS 1.3 minimum | inactif | `HTTPS=true` (+ `scripts/make-cert`, sinon créé au démarrage) | démarrage en HTTP + avertissement |
| Chiffrement au repos AES-256-GCM | inactif | `scripts/make-key --write` (écrit `DATA_ENCRYPTION_KEY`) | données en clair + avertissement |
| Intégrité des trames HMAC-SHA256 | inactif (mode démo) | `scripts/make-key --write` (écrit `EDGE_HMAC_KEY`), même clé sur le Pi | trames acceptées + avertissement sur la page Machines |
| MQTT sur TLS | inactif | `MQTT_TLS=1`, port 8883, `docker/mosquitto-tls.conf` | MQTT en clair ou repli HTTP |
| Docker | — | `scripts/run-docker.ps1` | — |

L'état courant est visible dans `GET /health` (champ `security`, avec la liste des avertissements) et au démarrage du serveur (« SÉCURITÉ — … »).

**Pour la démo de 8h, le plus sûr est de ne rien activer de plus** : tout ce qui est « actif par défaut » se montre sans configuration, et
l'écran reste en `http://localhost:8000` sans avertissement de certificat. Pour montrer le chiffrement et le HMAC au jury :

```powershell
.\scripts\make-key.ps1 --write      # DATA_ENCRYPTION_KEY + EDGE_HMAC_KEY dans .env (ne remplace jamais une clé existante)
.\scripts\run-demo.ps1 -Reset       # base neuve chiffrée ; page Machines : « Vérification HMAC-SHA256 active »
# HTTPS en plus : ajouter HTTPS=true dans .env → https://localhost:8000 (accepter l'avertissement du navigateur)
```
**Attention** : une fois la base chiffrée, garder la même `DATA_ENCRYPTION_KEY` (sinon les noms et les documents s'affichent « 🔒 chiffré » ;
remettre la clé ou relancer avec `-Reset`). Ne pas activer la clé HMAC si un simulateur autonome ou `camera_loop.py` tourne sans cette clé :
leurs trames seraient refusées.

## V3.2 Vérifié / non vérifié

| Étape | Tests automatiques | Lancé en conditions réelles | Non vérifié |
|---|---|---|---|
| 1 Docker | structure du `Dockerfile` et du compose, sonde de santé | `docker compose config` valide | **Image jamais construite ni lancée** : le démon Docker de la machine ne répondait pas (voir `BLOCKERS.md`). À tester : `scripts/run-docker.ps1`, attendre « healthy ». |
| 2 Pseudonymisation | aucun nom de patient dans les prompts, les webhooks, Telegram, les journaux ; pharmacien sans identité | serveur de test : explications d'IA en « PAT-0002 » | avec le vrai LLM et n8n (pas de crédit) |
| 3 TLS / AES / audit | AES-GCM, donnée altérée, sans clé, migration, recherche, poignée de main TLS 1.3 acceptée et 1.2 refusée, audit avec IP | serveur HTTPS sur le port 8010 : TLS 1.2 refusé, base chiffrée sur disque, `/health` sans avertissement | MQTT sur TLS contre un broker ; n8n face à un serveur HTTPS auto-signé ; navigateur réel en HTTPS |
| 4 FHIR | structure de chaque ressource, codes LOINC, pseudonymes, rôles, audit | `/fhir/Patient` et 154 observations lus sur le serveur de test ; bouton présent dans le dossier | validateur officiel HL7 non utilisé ; table LOINC de biologie écrite de mémoire ; téléchargement du fichier non essayé |
| 5 Intégrité des trames | trame valide, signature fausse, rejeu, trop ancienne, non signée, mode démo | simulateur embarqué : 3 860 trames signées vérifiées, 0 rejet ; trame non signée refusée (401) ; carte « HMAC-SHA256 active » | chemin MQTT, vrai Raspberry Pi |
| 6 SADM | formules de l'indice, explication de chaque type de recommandation, décisions tracées, garde-fous de rôle | captures `docs/screenshots/v3/` : bandeau, bande sur risque / diagnostics / prédictions / psychologie, boutons dans la cloche | clic réel sur Valider / Signer dans un navigateur (testés par l'API seulement) ; bloc « À signer » non capturé (aucune ordonnance en brouillon au moment de la capture) ; aucun test avec des soignants |
| 7 Documents | — | relus, état réel ajouté en tête | chiffres de coût = estimations ; points juridiques INPDP / RGPD à confirmer avec un juriste ; sections 4-5-6 reconstruites (texte officiel du cahier des charges absent du dépôt) |
| 8 Final | **263 tests verts** (dont `full_demo_v2` en mock) | captures de non-régression 3D (`01`, `02`) | `full_demo_v2` n'a pas été rejoué à la main dans un navigateur cette nuit |

Les étapes 4, 5 et 7 ont été réalisées par des sous-agents en parallèle, dans des arbres de travail séparés, puis intégrées une par une.
Les suites complètes intermédiaires lancées en parallèle des captures ont été faussées par la saturation de la machine (un test de délai
d'escalade a échoué une fois sous charge, puis passé) : le résultat qui fait foi est la suite complète finale, lancée seule.

## V3.3 Ce que montre l'interface

- **Bandeau permanent** en bas : « Recommandation consultative — la décision et la signature restent celles du médecin ».
- **Centre de commande, Diagnostics live, Prédictions, Psychologie, parcours fièvre** : sous chaque recommandation, l'indice de confiance
  (formule en infobulle), les paramètres déclencheurs, Valider / Rejeter.
- **Cloche** : Valider / Rejeter directement sur une alerte ; bloc « À signer » pour les médecins.
- **Paramètres des machines** : carte « Intégrité des trames ».
- **Dossier médical** : bouton « Exporter en FHIR ».
- Les textes rédigés par l'IA désignent le patient par son pseudonyme (« PAT-0002 ») : c'est voulu (rien de nominatif ne part vers le LLM).
  Le nom reste affiché à côté pour les soignants.

## V3.4 Documents

`docs/ARCHITECTURE.md`, `docs/CONFORMITE.md`, `docs/DEPLOIEMENT.md`, `docs/QA_JURY.md` (jury) ; `docs/securite.md`, `docs/interoperabilite.md`,
`docs/integrite-trames.md`, `docs/ergonomie.md`, `docs/biais.md` (par mécanisme) ; `docs/demo_v2.md` (déroulé de la démonstration, inchangé).

## V3.5 Points d'attention pour 8h

- **Crédit Anthropic toujours épuisé** : garder `LLM_PROVIDER=mock` et `N8N_ENABLED=false` dans `.env`, ou recharger le crédit.
- Un serveur de la plateforme tourne déjà sur le port 8000 depuis 01h06 (lancé hors de cette session) : il n'a pas les changements V3 ;
  le relancer (`.\scripts\run-demo.ps1 -Reset`) pour les avoir.
- La machine était saturée cette nuit (CPU à 100 %, 1 Go de mémoire libre, Docker Desktop en erreur) : fermer ce qui n'est pas utile avant la démo.

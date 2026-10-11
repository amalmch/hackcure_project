# AMAL_SYNC — suivi de l'intégration du dépôt d'Amal

Dépôt source : `https://github.com/amalmch/hackcure_project` (branche `master`, remote git `amal`).
Notre dépôt a été créé à partir de son commit `7c4322d` (historiques sans lien commun).

| Date | Base | Dernier commit intégré | Commits repris |
|---|---|---|---|
| 2026-10-10 18:45 | `7c4322d` | `a4fa849` | `a4fa849` « Update 3D hospital dashboard and multi-floor navigation » |
| 2026-10-11 02:00 | `a4fa849` | **`12e1eb2`** | `384ae87` « feat: add 3D dashboard support for machine errors », `12e1eb2` « feat: update YOLO and transformer models and inference scripts » |

**Dernier commit d'Amal intégré : `12e1eb2`** — c'est la base de la prochaine synchronisation.

## Procédure (re-jouable)

```bash
git remote add amal https://github.com/amalmch/hackcure_project.git   # si absent
git fetch amal master
BASE=12e1eb2                                   # dernier commit intégré (ligne ci-dessus)
git log --oneline $BASE..amal/master           # ce qu'il y a de nouveau ; rien ⇒ terminé
# 1) fichiers JS : application à trois voies, conflits résolus à la main en gardant les deux apports
git diff $BASE amal/master -- dashboard/static/js > /tmp/amal.patch && git apply -3 /tmp/amal.patch
# 2) fichiers que nous avons restructurés : lire le diff et le porter à la main
git diff $BASE amal/master -- dashboard/server.py dashboard/static/index.html dashboard/static/css
# 3) le reste (hors données) : git diff $BASE amal/master --stat -- . ':(exclude)computer_vision/data'
# 4) vision : fichiers que nous n'avons pas modifiés → repris tels quels
git checkout amal/master -- computer_vision/src/transformer computer_vision/reports   # puis relire inference.py, agent_adapter.py (écarts ci-dessous)
```
Puis : `node --check` sur chaque JS, `pytest`, captures `scripts/shots_v2.py` (RDC, Étage 1, éclaté, salle isolée, visite à pied), mise à jour du tableau ci-dessus.

## Où vont ses changements chez nous

| Fichier d'Amal | Chez nous |
|---|---|
| `dashboard/static/js/floors.js` | repris **tel quel** ; chargé après `app.js` ; initialisé par `scene.js` (`HospitalFloors.init`) |
| `scene.js`, `avatars.js`, `patient-state.js` | fusion à trois voies avec nos ajouts (liseré de risque, poses, moniteurs) |
| `dashboard/server.py` | porté dans `dashboard/app/state.py` (`process_event`) et `dashboard/app/api/demo.py` (`DemoEvent`, `/api/demo/trigger`, `/api/yolo/event`) |
| `index.html` (panneau capteurs) | `#sensor-panel` + `static/js/sensor-panel.js`, alimenté par `room_state.env` |

| `server.py` : `machine_error`, `machine_type` (384ae87) | `app/state.py` (`process_event`, `machine_fault`), `app/api/demo.py` (`DemoEvent.machine_type`), puis **`app/equipment.py` + VitalsAgent** : la panne est rattachée à notre appareil (`MedicalDevice`), devient le risque `equipment_fault`, avec son scénario `equipment_resolves` |
| `avatars.js` (engrenage au-dessus de la potence), `scene.js` (bandeau du moniteur), `patient-state.js`, `dashboard-ui.js`, `demo-controller.js`, `dashboard.css` (384ae87) | fusion à trois voies (2 conflits, les deux apports gardés) ; complété par `static/js/equipment-faults.js` (étiquette en chambre + tableau de la salle Équipements) |
| `index.html` : bouton « Machine Error » + liste des machines | porté dans notre `index.html` (« Panne machine », libellés français, mêmes valeurs) |
| `computer_vision/src/transformer/`, `temporal/risk_analyzer.py`, `temporal/transformer_analysis.py`, `scripts/train_patient_transformer.py`, `reports/` (12e1eb2) | repris **tels quels** |
| `computer_vision/src/inference.py`, `temporal/agent_adapter.py` (12e1eb2) | repris avec deux écarts (ci-dessous) ; assemblés par `computer_vision/src/behavior.py` (`BehaviorAnalyzer`, `load_transformer`) |
| `dashboard/camera_loop.py` (réécriture, 12e1eb2) | fusionné avec notre version : sa boucle et son affichage, notre publication aux contrats (`/api/ingest`) + le nouveau message `vision/behavior` |

## Écarts volontaires
- `/api/yolo/event` garde `source="yolo"` (Amal : `ai_pipeline`) : notre ingestion et nos tests distinguent `yolo` / `simulation`.
- Le message WebSocket `behavior` n'est émis que pour `behavioral_risk` ; les autres événements gardent exactement les messages d'origine (non-régression).
- Le panneau « Étages & salles » de `floors.js` est remonté au-dessus du bandeau KPI et masqué quand une vue HTML est ouverte (règles dans `platform.css`, `floors.js` non modifié).
- **Transformer optionnel** (12e1eb2) : chez Amal, `inference.py` et `camera_loop.py` importent PyTorch et chargent DINOv2 par `torch.hub.load` (téléchargement) à chaque démarrage. Chez nous `load_transformer()` ne charge le modèle que si PyTorch, le backbone (cache torch hub) **et** les poids entraînés `computer_vision/runs/patient_transformer/best_transformer.pt` sont déjà sur le disque ; sinon il renvoie `None` et l'analyse continue sur le détecteur seul. Les poids ne sont pas dans le dépôt : aucun téléchargement, aucun entraînement.
- `InterventionAgentAdapter` : plus d'appel HTTP par défaut vers `localhost:8001` (1 s d'attente par image) ; le service d'intervention est la plateforme elle-même. Un service externe reste possible par `INTERVENTION_AGENT_URL`.
- « Immobilité prolongée » : l'analyseur d'Amal la classe en risque modéré ; pour un patient au repos dans son lit nous la ramenons à « faible » (`behavioral_level`), sinon chaque patient endormi ouvrirait un risque.
- `camera_loop.py` n'envoie « recover » qu'au retour à la normale (chez Amal : toutes les 2 s) : sur la plateforme, « recover » efface aussi les alertes en cours du patient.
- `machine_error` : une panne n'est jamais confondue avec l'occlusion ou la poche vide de la pompe (`iv_occlusion`, `iv_empty`), qui gardent leurs risques et leur scénario `iv_resolves`. « Recovery » remet l'appareil en service mais le risque attend la confirmation d'un soignant (règle V2 : pas de clôture automatique).

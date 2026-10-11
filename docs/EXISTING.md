# Audit de l'existant (phase A)

Inventaire de ce qui était livré dans le dépôt d'Amal (`hackcure_project`) et qui est **réutilisé tel quel**.
Rien de ce qui est listé ici ne doit être réécrit ; on étend par de nouveaux fichiers.

## 1. Backend d'origine — `dashboard/server.py` (→ refactoré en `dashboard/app/`)

Le comportement est conservé à l'identique ; `server.py` ne fait plus qu'importer `app.main:app`.

| Élément | Où (après refactor) | Comportement |
|---|---|---|
| `patients` (dict) | `app/state.py` | 4 patients `patient_01..04`, chambres `101..104`, noms `Patient A..D`, âges 72/68/81/75, champs `state`, `fall_detected`, `pain_detected`, `confidence`, `last_event_time`, `alert_priority`, `source`, `room_position` |
| `process_event(patient_id, event_type, source, confidence)` | `app/state.py` | `fall` → `fall_detected`/critical ; `pain` → `pain_detected`/high ; `fall_and_pain` → critical ; `recover` → normal/none ; type inconnu ignoré ; insère dans `event_history` (max 100) ; diffuse `patient_event` |
| `ConnectionManager` | `app/ws.py` | `connect`, `disconnect`, `broadcast(dict)` |
| `GET /api/patients` | `app/api/demo.py` | dict complet des patients |
| `GET /api/events` | idem | 50 derniers événements |
| `POST /api/demo/trigger` `{patient_id, event_type, confidence}` | idem | 400 si mode ≠ `demo` ; `source="simulation"` |
| `POST /api/demo/reset` | idem | `recover` sur tous + vide l'historique + message `reset` |
| `POST /api/mode` `{mode}` | idem | `demo` ou `real` (400 sinon) ; message `mode_change` |
| `POST /api/yolo/event` | idem | comme trigger mais `source="yolo"`, accepté dans tous les modes |
| `GET /` | `app/main.py` | `static/index.html` |
| `/static` | idem | fichiers statiques |
| `WS /ws` | idem | envoie `init` ; répond `pong` à `ping` |

### Messages WebSocket d'origine
```json
{"type":"init","patients":{...},"mode":"demo","event_history":[...20 max]}
{"type":"patient_event","patient_id":"patient_02","event_type":"fall","source":"simulation",
 "fall_detected":true,"pain_detected":false,"state":"fall_detected","confidence":0.93,
 "alert_priority":"critical","timestamp":"..."}
{"type":"reset","patients":{...}}
{"type":"mode_change","mode":"real"}
{"type":"pong"}
```
Ajouts additifs (phase A) : `init.room_states`, `patient_event.room`, endpoint `GET /health`, `GET /login`.

## 2. Frontend d'origine — `dashboard/static/`

Scripts **globaux** (pas de modules), ordre de chargement : `patient-state.js`, `scene.js`, `avatars.js`, `dashboard-ui.js`, `demo-controller.js`, `app.js`. Three.js **r128** + `OrbitControls` (CDN).

### `PatientStateManager` (`patient-state.js`)
`STATES {NORMAL, FALL, PAIN, FALL_PAIN}`, `PRIORITIES {none,low,high,critical}`, `init(patients)`, `getPatient(id)`, `getAllPatients()`, `getPatientList()`, `updatePatient(event)`, `resetAll(patients?)`, `hasActiveAlerts()`, `getCriticalPatients()`, `subscribe(cb(type, data))` — types `init`, `update {patient, event}`, `reset`.

### `HospitalScene` (`scene.js`, ~1500 lignes, GELÉ visuellement)
Export : `init`, `getScene`, `getCamera`, `getBedParts(roomId)` → `{backrest, blanket, ...}`, `getBedWorldPosition(roomId)` → `{x, z, rotY}`, `focusOnPatient(patientId)`, `zoomToRoom(roomId)`, `zoomToReception()`, `resetCamera()`, `topDownView()`, `dispose()`, `BED` = `{x:-1.2, z:-1.85, deckY:0.8, hingeZ:-0.25, backAngle:π/6}`.
- Internes utiles : `ROOMS = {101:{x:-4,z:-5,rotY:0}, 102:{x:4,z:-5,rotY:0}, 103:{x:-4,z:5,rotY:π}, 104:{x:4,z:5,rotY:π}}`, repère local chambre x −4..4 / z −3..3, `DOOR {x:2.6,w:1.3,h:2.1}` sur le mur z=+3 (couloir), `WINDOW {x0:1.6,x1:3.2,sill:0.95,top:2.35}` sur le mur z=−3 (rangée nord seulement), `roomGroups[id]` (THREE.Group par chambre), `monitors[]` (`{canvas, ctx, tex, room, hr, targetHr, spo2, bp, alarm}`), `makeMonitor/drawMonitor` (écran animé ECG/pleth/resp), `syncVitals()` (table fixe par état patient, toutes les 500 ms), potence `buildIVPole` à `(BED.x+0.85, BED.z-0.85)`, chariot moniteur `(1.7, -2.5)`, fauteuil `(2.9, -0.6)`, `window._hackcureCamera` pour le picking, boutons de zoom par chambre ajoutés dans `#camera-controls`, double-clic = zoom, overlay CCTV masqué au zoom.
- Boucle `animate()` : tween caméra, `syncVitals` (500 ms), redraw moniteurs (66 ms), `animateExterior`, `AvatarManager.update(dt)`.

### `AvatarManager` (`avatars.js`)
Export : `init`, `update(delta)`, `getAvatarAtPosition(raycaster)`. Avatar articulé (`body`, `pelvis`, `torso`, `neck`, `arms.{R,L}.{shoulder,elbow}`, `legs.{R,L}.{hip,knee}`), poses `normal` / `pain` / `fall` (table `poses(BED)`), anneau de statut, étiquette sprite, indicateur douleur, dossier de lit et couverture synchronisés. Pose choisie par `poseKey(p)` : `fall_detected` → `fall`, `pain_detected` → `pain`, sinon `normal`. Transitions lissées (`k = 1 − e^(−6·dt)`). Les meshes portent `userData.patientId`.

### `DashboardUI` (`dashboard-ui.js`)
Export : `init`, `selectPatient(id)` (zoom CCTV + détail), `addEventToLog(event)`, `getSelectedPatientId()`. Cartes patients (`#patient-cards-container`), bannière d'alerte, journal (`#event-list`, 50 max), horloge, boutons vue d'ensemble / dessus.

### `DemoController` (`demo-controller.js`)
Export : `init(mode)`, `triggerDemoEvent(pid, type, conf)`, `resetAll()`, `updateVisibility(mode)`. Boutons `.demo-btn[data-event]`, `#btn-auto-demo` (séquence auto), `#btn-reset-all`, select `#demo-target-patient`. Masqué en mode `real` (`.demo-hidden`).

### `app.js`
WebSocket + reconnexion (3 s) + ping (30 s). Sur `init` (première fois) : `PatientStateManager.init` → `HospitalScene.init` → `AvatarManager.init` → `DashboardUI.init` → `DemoController.init` → boutons de mode → clic 3D (sélection d'avatar). Sur reconnexion : resynchronisation sans réinitialiser la scène.

### Mise en page (`index.html` / `dashboard.css`)
`#top-bar` (logo, `#mode-selector`, `#connection-status`, `#clock`) · `#app-container` = `#sidebar` (280 px : cartes + `#demo-controls`) + `#viewport-container` (`#alert-banner`, `#mode-indicator`, `#three-container`, `#cctv-overlay`, `#camera-controls`) + `#event-panel` (300 px : `#event-list`, `#patient-detail`). Variables CSS : `--bg-*`, `--text-*`, `--accent-*`, `--status-*`, `--radius-*`.

## 3. Vision par ordinateur — `computer_vision/`

- `src/inference.py` — `PatientMonitor(model_path, confidence, iou_threshold, device, imgsz, temporal_config)` : `process_frame(frame, ts)` → liste de dicts `{patient_id(track), state(classe CV), confidence, bbox, position, movement, fall_event{detected,...}, possible_discomfort, trajectory}` ; `process_video`, `process_image`, `reset`, `from_config`.
- `src/tracking/patient_tracker.py` — `PatientTracker` (YOLO + ByteTrack, importe `ultralytics` au chargement), `TrackState`.
- `src/temporal/movement_analyzer.py` — `MovementAnalyzer.update(track_id, center, image_width, image_height, frame_idx, center_history)` → `{state: stationary|slow|walking|rapid_motion, velocity, ...}`.
- `src/temporal/fall_detector.py` — `FallDetector.update(track_id, class_name, confidence, movement_state, velocity, frame_idx, timestamp)` → `FallEvent{detected, confidence, ...}` ; `from_config(temporal.yaml)`.
- `src/face/discomfort.py` — `DiscomfortAssociator.associate(detections, patient_tracks, w, h)`.
- `src/spatial/position.py` — `compute_position(bbox, w, h)` → `PatientPosition{x_center, y_center, bottom_x, bottom_y, area_norm, ...}` (le point bas-centre sert au test du polygone du lit).
- `src/datasets/harmonize.py` — **reconstruit** (voir DECISIONS.md) : `polygon_to_bbox`, `harmonize_label_line`, `build_remap`.
- `configs/datasets.yaml` (classes canoniques 0..6 : `patient_fallen`, `patient_lying`, `patient_moving_out`, `patient_near_fall`, `patient_out`, `patient_sitting`, `possible_discomfort`), `configs/temporal.yaml` (seuils), `configs/training.yaml`.
- `tests/test_core.py` — 13 tests (harmonisation, position, mouvement, chute, inconfort). Ne dépendent pas d'`ultralytics`.
- `data/processed/patient_detection/` + `data/manifests/` — **jamais modifiés**.
- Racine : `train_yolo.py` / `test_yolo.py` (modèle 2 classes `falling` / `no_falling`), `dashboard/camera_loop.py` (webcam → YOLO 2 classes + DeepFace → `POST /api/yolo/event`).
- Poids `*.pt` et `runs/` **absents du dépôt** : tout le code doit fonctionner sans eux (repli section 6.4 du PROMPT).

## 4. Points d'extension retenus
- `scene.js` : ajout **additif** d'une fonction exportée `setMonitorVitals(room, {hr, spo2, bp, alarm})` (valeurs réelles prioritaires sur la table fixe de `syncVitals`) et de `getRoomGroup(roomId)` / `setRoomRiskColor(roomId, level)` pour les nouveaux scripts.
- `avatars.js` : nouvelles poses `sitting_edge`, `standing`, `walking`, `absent` + `setPosture(patientId, posture)`; le mapping legacy `poseKey` reste prioritaire pour `fall`/`pain`.
- Nouveaux scripts : `room-live.js`, `staff-avatars.js`, `equipment.js`, `kpi-bar.js`, `nav.js`, `api.js`, `auth.js`, `agents-panel.js`, `views/*.js` chargés **après** les existants.

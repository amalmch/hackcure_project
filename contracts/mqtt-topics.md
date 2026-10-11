# Contrats de messages — SOURCE DE VÉRITÉ

Préfixe : `hackcure/room/{roomCode}/…` (`roomCode` = `101`..`104`). JSON UTF-8.
Chaque message porte `ts` (ISO 8601 UTC) et `source` (`edge-yolo`, `edge-pose`, `edge-fake`, `sim`, `server`, `camera_loop`).
Un JSON Schema par message dans `schemas/` ; la correspondance topic → schéma est dans `dashboard/app/contracts.py`
(`schema_for_topic`, `validate`) et testée par `dashboard/tests/test_contracts.py`.

**Repli HTTP** (pas de broker) : `POST /api/ingest` avec `{ "topic": "hackcure/room/101/vision/state", "payload": { ... } }`
→ traitement strictement identique à la réception MQTT. Réponse `202 {"status":"accepted"}` ou `422` si le schéma échoue.
Un lot est accepté sous la forme `{ "messages": [ {topic, payload}, ... ] }`.

| Topic | Émetteur | Schéma | Contenu |
|---|---|---|---|
| `…/vision/state` (2 Hz) | edge / sim | `vision_state.json` | `persons`, `patientTrackId`, `posture`, `activity`, `zone`, `confidence`, `cvClass`, `floorPos{x,y}?` |
| `…/vision/staff` | edge / sim | `vision_staff.json` | `event: staff_enter / staff_leave`, `persons`, `durationSec?` |
| `…/vision/expression` | edge / sim | `vision_expression.json` | `expression`, `confidence` |
| `…/vision/behavior` | edge / camera_loop | `vision_behavior.json` | `riskLevel` (`none`…`critical`), `riskScore`, `indicators[]`, `recommendations[]?`, `transformer?`, `fallProbability?` — analyse comportementale optionnelle |
| `…/thermal` (1 Hz) | edge / sim | `thermal.json` | `skinTempC`, `maxTempC`, `calibrated` |
| `…/env` | edge / sim | `env.json` | `tempC`, `humidity`, `motion`, `doorOpen` |
| `…/call` | edge / sim | `call.json` | `pressed: true` |
| `…/device/{deviceId}` (1 Hz) | sim | `device.json` | `type`, `status?`, `metrics` (par type, voir ci-dessous), `fault{code,label?}?` (panne de l'appareil) |
| `…/safety/alarm` | edge | `safety_alarm.json` | `reason: fall / call / critical / bed_exit_night`, `localActionTaken[]`, `offline?` |
| `…/cmd/{equipment}` | serveur → edge | `cmd.json` | `action: open / close / on / off / set`, `value?`, `requestedBy`, `reason`, `commandId?` |
| `…/cmd/ack` | edge → serveur | `cmd_ack.json` | `equipment`, `action`, `ok`, `state`, `commandId?` |
| `hackcure/sim/scenario` | serveur → sim | `sim_scenario.json` | `name`, `room?`, `speed?` |

## Métriques par type d'appareil (`device.json`)
| `type` | `metrics` |
|---|---|
| `iv_pump` | `rateMlH`, `volumeLeftMl`, `occlusion` |
| `nutrition_pump` | `rateMlH`, `volumeLeftMl` |
| `transfusion` | `rateMlH`, `volumeLeftMl`, `reaction` |
| `bp` | `sys`, `dia`, `map` |
| `ecg` | `hr`, `rhythm` (`sinus`, `tachy`, `brady`, `afib`, `artifact`) |
| `oxygen` | `flowLMin` |
| `spo2` | `spo2` |
| `thermometer` | `tempC` |

`deviceId` recommandé : `{room}-{type}` (ex. `101-iv_pump`).

## Valeurs énumérées
- `posture` : `lying_bed | sitting_bed | sitting_chair | standing | walking | on_floor | absent`
- `activity` : `sleeping | awake_bed | out_of_bed | toilet | out_of_room | fall`
- `zone` : `bed | floor | bathroom_door | exit | none`
- `expression` : `neutral | happy | sad | pain | fear | anger | surprise`
- `equipment` (cmd) : `window | heater | ac | light | buzzer`

## Correspondance classes CV → contrat (`edge/vision/posture_map.py`)
| Classe CV | posture | activity | zone |
|---|---|---|---|
| `patient_lying` (dans le polygone du lit) | `lying_bed` | `awake_bed`, ou `sleeping` si immobile > 5 min | `bed` |
| `patient_sitting` | `sitting_bed` si dans le lit, sinon `sitting_chair` | `awake_bed` / `out_of_bed` | `bed` / `floor` |
| `patient_moving_out`, `patient_near_fall` | `standing` | `out_of_bed` | `floor` |
| `patient_out` / aucune détection | `absent` | `out_of_room` (ou `toilet` si dernière zone = `bathroom_door`) | `exit` / `none` |
| `patient_fallen` confirmé par `FallDetector` | `on_floor` | `fall` | `floor` |
| `falling` (modèle 2 classes) | `on_floor` | `fall` | `floor` |

## Correspondance contrat → 3D existante (serveur, `dashboard/app/ingest/handler.py`)
- `on_floor` / `fall` → `patient_event` `fall` (ou `fall_and_pain` si expression `pain`)
- expression `pain` hors chute → `patient_event` `pain`
- sinon → `recover` si un état d'alerte était actif.
- En plus, le serveur diffuse sur `/ws` : `room_state = { type:"room_state", room, posture, activity, persons, expression, skinTempC, env, equipment, vitals, riskLevel, ts }`.

## Messages WebSocket `/ws` (serveur → navigateur)
Existants : `init` (patients, mode, event_history, room_states) · `patient_event` · `reset` · `mode_change` · `pong`.
Nouveaux : `room_state` · `agent_log` · `agent_status` · `risk` · `notification` · `staff_visit` · `kpi` · `device_reading` · `cmd_ack` · `scenario`.

## Intégrité des trames (V3) — `seq`, `ts`, `sig`
Champs ajoutés DANS le payload par les émetteurs (edge, simulateur, `camera_loop`) quand la clé partagée `EDGE_HMAC_KEY` est définie ; tous les schémas les acceptent (`additionalProperties: true`).
- `seq` : entier strictement croissant par émetteur (émetteur = `source` + chambre).
- `ts` : l'horodatage déjà présent (ISO 8601 UTC) ; c'est lui qui est signé.
- `sig` : HMAC-SHA256 en hexadécimal minuscule de `topic + "\n" + canonical_json(payload sans "sig")`, avec `canonical_json(obj) = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` (octets UTF-8).
- `measuredAt` (optionnel) : heure de mesure d'origine d'un message renvoyé depuis la file hors ligne de l'edge (son `ts` est alors l'heure d'envoi).

Primitives : `contracts/integrity.py` (bibliothèque standard uniquement). Côté serveur (`dashboard/app/ingest/integrity.py`), avec une clé : trame non signée, signature invalide, `ts` de plus de 30 s (`FRAME_MAX_AGE_S`) ou séquence déjà vue → rejet (`401` sur `POST /api/ingest` si rien n'est accepté dans le lot ; ignorée en MQTT), compté dans `GET /api/integrity`. Sans clé : mode démo, tout est accepté avec un avertissement. Non concernés : `…/cmd/{equipment}` (serveur → edge) et `hackcure/sim/scenario`. Détails : `docs/integrite-trames.md`.

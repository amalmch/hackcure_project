"""
Ingestion commune MQTT / HTTP (repli) / simulateur embarqué.

`handle(topic, payload, via)` :
1. valide le message contre son JSON Schema (`app.contracts`) ;
2. met à jour le cache `state.room_states` (contrat `room_state`, section 6.2) ;
3. persiste (sous-échantillonné) : VitalReading, EnvironmentReading, PatientStateSnapshot, MedicalDevice.last_seen, RoomEquipment ;
4. projette sur l'état 3D existant (`patient_event` fall / pain / fall_and_pain / recover) ;
5. publie sur le bus interne (`hackcure/room/{room}/…`) pour les agents ;
6. diffuse `room_state` / `device_batch` / `cmd_ack` sur le WebSocket (coalescés à 2 Hz).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import select

from .. import contracts, state
from ..bus import bus
from ..db import session_scope
from ..models import EnvironmentReading, MedicalDevice, PatientStateSnapshot, RoomEquipment, VitalReading
from ..ws import manager
from . import integrity  # V3 : intégrité des trames IoT

logger = logging.getLogger("hackcure.ingest")

ROOMS = ("101", "102", "103", "104")
HISTORY_LEN = 900  # ~15 min à 1 Hz

# ── mémoire vive ──────────────────────────────────────────────────────────────
latest_device: dict[str, dict[str, Any]] = {}  # device_id -> {room, type, status, metrics, ts}
history: dict[str, dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=HISTORY_LEN)))  # device_id -> metric -> (ts, value)
edge_seen: dict[str, float] = {}  # room -> dernier message d'un edge réel (time.time())
last_expression: dict[str, tuple[str, float, float]] = {}  # room -> (expression, confidence, time)
_derived_legacy: dict[str, str] = {}  # room -> dernier état 3D dérivé de la vision
_last_db_write: dict[str, float] = {}
_last_snapshot: dict[str, tuple[str, str, float]] = {}
_dirty_rooms: set[str] = set()
_pending_device_msgs: list[dict[str, Any]] = []
_flusher: Optional[asyncio.Task] = None
stats = {"accepted": 0, "rejected": 0, "by_via": defaultdict(int)}

DEVICE_UNITS = {"hr": "bpm", "spo2": "%", "sys": "mmHg", "dia": "mmHg", "map": "mmHg", "tempC": "°C", "rateMlH": "ml/h", "volumeLeftMl": "ml", "flowLMin": "l/min", "rr": "/min"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_room_state(room: str) -> dict[str, Any]:
    return {
        "type": "room_state",
        "room": room,
        "patient_id": state.patient_for_room(room),
        "posture": "lying_bed",
        "activity": "awake_bed",
        "zone": "bed",
        "persons": 1,
        "confidence": 0.0,
        "expression": "neutral",
        "skinTempC": None,
        "thermalCalibrated": False,
        "env": {"tempC": None, "humidity": None, "motion": False, "doorOpen": False},
        "equipment": {"window": "closed", "heater": "off", "ac": "off", "light": "off"},
        "vitals": {},
        "devices": {},
        "deviceFaults": {},  # pannes d'équipement par type d'appareil (app/equipment.py)
        "riskLevel": "none",
        "behavior": {"risk_level": "none", "risk_score": 0.0, "indicators": [], "recommendations": []},
        "openRisks": 0,
        "staffPresent": False,
        "staffRole": None,
        "source": "none",
        "visionSource": "none",
        "lastVisionTs": None,
        "ts": _now_iso(),
    }


def room_state(room: str) -> dict[str, Any]:
    rs = state.room_states.get(room)
    if rs is None:
        rs = default_room_state(room)
        state.room_states[room] = rs
    return rs


def init_room_states() -> None:
    for r in ROOMS:
        room_state(r)
    try:
        with session_scope() as s:
            for eq in s.exec(select(RoomEquipment)).all():
                room_state(eq.room_code)["equipment"][eq.type] = eq.state
    except Exception:  # base absente en phase A / tests sans DB
        logger.debug("init_room_states: équipements non chargés")


def is_real_edge(source: str) -> bool:
    return str(source).startswith("edge") or source in ("camera_loop", "pi")


def edge_alive(room: str, within_s: float = 15.0) -> bool:
    t = edge_seen.get(room)
    return t is not None and (time.time() - t) < within_s


# ── point d'entrée ────────────────────────────────────────────────────────────
async def handle(topic: str, payload: dict[str, Any], via: str = "http") -> dict[str, Any]:
    """Traite un message. Lève `contracts.ContractError` si invalide, `integrity.FrameRejected` si la trame échoue au contrôle d'intégrité."""
    try:
        kind, groups = contracts.validate(topic, payload)
    except contracts.ContractError:
        stats["rejected"] += 1
        raise
    # ── V3, étape 5 : intégrité des trames (séquence, horodatage, HMAC-SHA256) — voir ingest/integrity.py ──
    verdict = integrity.check(topic, payload, via)
    if not verdict.ok:
        stats["rejected"] += 1
        raise integrity.FrameRejected(verdict, topic)
    # ── fin V3, étape 5 ──
    stats["accepted"] += 1
    stats["by_via"][via] += 1
    room = groups.get("room", "")
    source = str(payload.get("source", via))

    if room and is_real_edge(source):
        edge_seen[room] = time.time()
        try:  # couper la vision virtuelle de la 101 dès qu'un edge réel parle
            from ..sim import embedded

            embedded.notify_real_edge(room)
        except Exception:
            pass

    if kind == "vision_state":
        await _on_vision_state(room, payload, source)
    elif kind == "vision_staff":
        await _on_vision_staff(room, payload)
    elif kind == "vision_expression":
        await _on_expression(room, payload, source)
    elif kind == "vision_behavior":
        await _on_vision_behavior(room, payload, source)
    elif kind == "thermal":
        _on_thermal(room, payload, source)
    elif kind == "env":
        _on_env(room, payload)
    elif kind == "call":
        rs = room_state(room)
        rs["callPressed"] = bool(payload.get("pressed"))
        rs["ts"] = payload["ts"]
        _dirty_rooms.add(room)
    elif kind == "device":
        _on_device(room, groups["device"], payload)
    elif kind == "safety_alarm":
        rs = room_state(room)
        rs["localAlarm"] = {"reason": payload["reason"], "actions": payload.get("localActionTaken", []), "ts": payload["ts"]}
        _dirty_rooms.add(room)
    elif kind == "cmd_ack":
        await _on_cmd_ack(room, payload)
    elif kind == "cmd":
        pass  # commandes : émises par le serveur, relayées telles quelles sur le bus
    elif kind == "sim_scenario":
        pass

    await bus.publish(topic, {"room": room, "kind": kind, "data": payload, "groups": groups, "via": via})
    _ensure_flusher()
    return {"kind": kind, "room": room}


def handle_nowait(topic: str, payload: dict[str, Any], via: str = "embedded") -> None:
    """Variante planifiée (callback synchrone du simulateur embarqué)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _run():
        try:
            await handle(topic, payload, via)
        except contracts.ContractError as exc:
            logger.warning("Message simulateur invalide %s: %s", topic, exc)
        except integrity.FrameRejected:
            pass  # déjà compté et journalisé par ingest/integrity.py
        except Exception:
            logger.exception("Ingestion %s", topic)

    loop.create_task(_run())


# ── traitements par type ──────────────────────────────────────────────────────
_behavior_calm: dict[str, bool] = {}


async def _on_vision_behavior(room: str, p: dict[str, Any], source: str) -> None:
    """Analyse comportementale de l'edge / camera_loop (optionnelle) → même chemin que `behavioral_risk` :
    état legacy, `room_state.behavior`, VisionAgent → RiskAgent, PsychAgent. Un niveau calme répété ne produit rien."""
    level = p["riskLevel"]
    calm = level in ("none", "low")
    if calm and _behavior_calm.get(room, True):
        return
    _behavior_calm[room] = calm
    pid = state.patient_for_room(room)
    if pid:
        await state.process_event(pid, "behavioral_risk", source=source, confidence=float(p.get("confidence", 0.9)), risk_level="none" if calm else level,
                                  risk_score=float(p["riskScore"]), behavior_indicators=[] if calm else list(p["indicators"]), recommendations=[] if calm else list(p.get("recommendations") or []))


async def _on_vision_state(room: str, p: dict[str, Any], source: str) -> None:
    rs = room_state(room)
    changed = (rs["posture"], rs["activity"]) != (p["posture"], p["activity"])
    rs.update(
        posture=p["posture"], activity=p["activity"], zone=p["zone"], persons=int(p["persons"]), confidence=float(p["confidence"]),
        cvClass=p.get("cvClass"), floorPos=p.get("floorPos"), source=source, visionSource=source, lastVisionTs=p["ts"], ts=p["ts"],
    )
    rs["staffPresent"] = int(p["persons"]) > 1
    rs["kpVariance"], rs["rhythmicHz"] = p.get("kpVariance"), p.get("rhythmicHz")  # mouvements rythmiques (PredictionAgent)
    rs["patient_id"] = state.patient_for_room(room)
    _dirty_rooms.add(room)

    now = time.time()
    last = _last_snapshot.get(room)
    if changed or last is None or now - last[2] > 60:
        _last_snapshot[room] = (p["posture"], p["activity"], now)
        _store_snapshot(room, rs, source)

    await _project_legacy(room, rs, source, immediate=changed)
    if changed:
        await _broadcast_room(room)


async def _on_vision_staff(room: str, p: dict[str, Any]) -> None:
    rs = room_state(room)
    rs["staffPresent"] = p["event"] == "staff_enter"
    rs["staffRole"] = (p.get("role") or "nurse") if rs["staffPresent"] else None
    rs["persons"] = int(p["persons"])
    rs["lastStaffEvent"] = {"event": p["event"], "durationSec": p.get("durationSec"), "ts": p["ts"]}
    rs["ts"] = p["ts"]
    await manager.broadcast({"type": "staff_visit", "room": room, "event": p["event"], "persons": p["persons"], "durationSec": p.get("durationSec"), "ts": p["ts"]})
    await _broadcast_room(room)


async def _on_expression(room: str, p: dict[str, Any], source: str) -> None:
    rs = room_state(room)
    prev = rs.get("expression")
    rs["expression"] = p["expression"]
    rs["expressionConfidence"] = float(p["confidence"])
    rs["ts"] = p["ts"]
    last_expression[room] = (p["expression"], float(p["confidence"]), time.time())
    _dirty_rooms.add(room)
    if prev != p["expression"]:
        await _project_legacy(room, rs, source, immediate=True)
        await _broadcast_room(room)


def _on_thermal(room: str, p: dict[str, Any], source: str) -> None:
    rs = room_state(room)
    rs["skinTempC"] = float(p["skinTempC"])
    rs["thermalCalibrated"] = bool(p["calibrated"])
    rs["thermalSource"] = source
    rs["ts"] = p["ts"]
    _dirty_rooms.add(room)
    _store_env_sampled(room, "skinTempC", float(p["skinTempC"]), period=15.0)


def _on_env(room: str, p: dict[str, Any]) -> None:
    rs = room_state(room)
    rs["env"] = {"tempC": float(p["tempC"]), "humidity": float(p["humidity"]), "motion": bool(p.get("motion", False)), "doorOpen": bool(p.get("doorOpen", False))}
    if p.get("outdoorC") is not None:  # température extérieure (simulateur ou station) : sert au choix fenêtre / climatisation
        rs["env"]["outdoorC"] = float(p["outdoorC"])
    rs["ts"] = p["ts"]
    _dirty_rooms.add(room)
    _store_env_sampled(room, "tempC", float(p["tempC"]), period=15.0)
    _store_env_sampled(room, "humidity", float(p["humidity"]), period=60.0)


def _on_device(room: str, device_id: str, p: dict[str, Any]) -> None:
    rs = room_state(room)
    metrics = dict(p["metrics"])
    entry = {"room": room, "device_id": device_id, "type": p["type"], "status": p.get("status", "running"), "metrics": metrics, "ts": p["ts"], "source": p.get("source", "sim"), "fault": p.get("fault")}
    latest_device[device_id] = entry
    rs["devices"][device_id] = {"type": p["type"], "status": entry["status"], "metrics": metrics, "ts": p["ts"], "fault": p.get("fault")}
    now = time.time()
    for m, v in metrics.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            history[device_id][m].append((now, float(v)))
    # résumé des constantes pour le moniteur 3D et les agents
    v = rs["vitals"]
    t = p["type"]
    if t == "ecg":
        v["hr"] = metrics.get("hr")
        v["rhythm"] = metrics.get("rhythm")
        if "rr" in metrics:
            v["rr"] = metrics["rr"]
        if "stMm" in metrics:
            v["st"] = metrics["stMm"]  # sus-décalage du segment ST (mm)
    elif t == "spo2":
        v["spo2"] = metrics.get("spo2")
    elif t == "bp":
        v["sys"], v["dia"], v["map"] = metrics.get("sys"), metrics.get("dia"), metrics.get("map")
    elif t == "thermometer":
        v["tempC"] = metrics.get("tempC")
    elif t == "glucometer":
        v["glucose"] = metrics.get("glucose")  # glycémie capillaire (g/L)
    elif t == "oxygen":
        v["o2FlowLMin"] = metrics.get("flowLMin")
    elif t == "iv_pump":
        v["ivVolumeLeftMl"] = metrics.get("volumeLeftMl")
        v["ivOcclusion"] = metrics.get("occlusion")
    rs["ts"] = p["ts"]
    _dirty_rooms.add(room)
    _pending_device_msgs.append({"room": room, "device_id": device_id, "type": p["type"], "status": entry["status"], "metrics": metrics, "ts": p["ts"]})
    _store_vitals_sampled(room, device_id, metrics, period=10.0, status=entry["status"])


async def _on_cmd_ack(room: str, p: dict[str, Any]) -> None:
    rs = room_state(room)
    if p.get("ok") and p["equipment"] in rs["equipment"]:
        rs["equipment"][p["equipment"]] = p["state"]
        try:
            with session_scope() as s:
                eq = s.exec(select(RoomEquipment).where(RoomEquipment.room_code == room, RoomEquipment.type == p["equipment"])).first()
                if eq:
                    eq.state = p["state"]
                    eq.updated_at = datetime.now(timezone.utc)
        except Exception:
            logger.debug("cmd_ack: équipement non persisté")
    rs["ts"] = p["ts"]
    await manager.broadcast({"type": "cmd_ack", "room": room, **{k: p.get(k) for k in ("equipment", "action", "ok", "state", "commandId", "error")}})
    await _broadcast_room(room)


# ── projection sur l'état 3D existant ─────────────────────────────────────────
def derive_legacy_state(rs: dict[str, Any]) -> str:
    fall = rs.get("activity") == "fall" or rs.get("posture") == "on_floor"
    pain = rs.get("expression") == "pain" and float(rs.get("expressionConfidence", 1.0) or 0) >= 0.4
    return state.state_from_flags(fall, pain)


async def _project_legacy(room: str, rs: dict[str, Any], source: str, immediate: bool) -> None:
    pid = state.patient_for_room(room)
    if not pid:
        return
    derived = derive_legacy_state(rs)
    prev = _derived_legacy.get(room)
    if derived == prev:
        return
    _derived_legacy[room] = derived
    event_type = {"fall_detected": "fall", "pain_detected": "pain", "fall_and_pain": "fall_and_pain", "normal": "recover"}[derived]
    if event_type == "recover" and prev is None:
        return  # premier message « normal » : rien à récupérer
    legacy_source = "yolo" if is_real_edge(source) else "simulation"
    await state.process_event(pid, event_type, source=legacy_source, confidence=float(rs.get("confidence") or 0.9))


# ── persistance sous-échantillonnée ──────────────────────────────────────────
def _store_vitals_sampled(room: str, device_id: str, metrics: dict[str, Any], period: float, status: str) -> None:
    now = time.time()
    key = f"dev:{device_id}"
    if now - _last_db_write.get(key, 0) < period:
        return
    _last_db_write[key] = now
    try:
        with session_scope() as s:
            adm_id = _active_admission_id(s, room)
            for m, v in metrics.items():
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    continue
                s.add(VitalReading(device_id=device_id, admission_id=adm_id, room_code=room, metric=m, value=float(v), unit=DEVICE_UNITS.get(m, "")))
            dev = s.exec(select(MedicalDevice).where(MedicalDevice.device_id == device_id)).first()
            if dev:
                dev.last_seen = datetime.now(timezone.utc)
                dev.status = status
    except Exception:
        logger.debug("VitalReading non persisté", exc_info=True)


def _store_env_sampled(room: str, metric: str, value: float, period: float) -> None:
    now = time.time()
    key = f"env:{room}:{metric}"
    if now - _last_db_write.get(key, 0) < period:
        return
    _last_db_write[key] = now
    try:
        with session_scope() as s:
            s.add(EnvironmentReading(room_code=room, metric=metric, value=value))
    except Exception:
        logger.debug("EnvironmentReading non persisté", exc_info=True)


def _store_snapshot(room: str, rs: dict[str, Any], source: str) -> None:
    try:
        with session_scope() as s:
            s.add(PatientStateSnapshot(
                admission_id=_active_admission_id(s, room), room_code=room, posture=rs["posture"], activity=rs["activity"], zone=rs["zone"],
                expression=rs.get("expression", "neutral"), skin_temp_c=rs.get("skinTempC"), persons=int(rs.get("persons", 1)), source=source,
            ))
    except Exception:
        logger.debug("Snapshot non persisté", exc_info=True)


def _active_admission_id(session, room: str) -> Optional[int]:
    try:
        from ..models import Admission

        adm = session.exec(select(Admission).where(Admission.room_code == room, Admission.discharged_at.is_(None))).first()
        return adm.id if adm else None
    except Exception:
        return None


# ── diffusion WebSocket coalescée ────────────────────────────────────────────
async def _broadcast_room(room: str) -> None:
    _dirty_rooms.discard(room)
    rs = room_state(room)
    rs["patient_id"] = state.patient_for_room(room)
    await manager.broadcast(rs)


def _ensure_flusher() -> None:
    global _flusher
    if _flusher is None or _flusher.done():
        try:
            _flusher = asyncio.get_running_loop().create_task(_flush_loop())
        except RuntimeError:
            pass


async def _flush_loop() -> None:
    while True:
        try:
            await asyncio.sleep(0.5)
            for room in list(_dirty_rooms):
                await _broadcast_room(room)
            if _pending_device_msgs:
                batch = _pending_device_msgs[:]
                _pending_device_msgs.clear()
                await manager.broadcast({"type": "device_batch", "readings": batch, "ts": _now_iso()})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("flush_loop")


def set_risk_level(room: str, level: str, open_count: int) -> None:
    rs = room_state(room)
    if rs.get("riskLevel") != level or rs.get("openRisks") != open_count:
        rs["riskLevel"] = level
        rs["openRisks"] = open_count
        _dirty_rooms.add(room)
        _ensure_flusher()


def device_history(device_id: str, metric: str, seconds: int = 600) -> list[tuple[float, float]]:
    cutoff = time.time() - seconds
    return [(t, v) for t, v in history.get(device_id, {}).get(metric, []) if t >= cutoff]


init_room_states()

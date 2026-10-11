"""
État patient « legacy » (comportement de l'ancien server.py, conservé à l'identique)
+ cache `room_state` par chambre pour les nouveaux scripts 3D.

Le message WebSocket `patient_event` et la structure `patients` ne changent pas :
le frontend existant (patient-state.js, avatars.js, dashboard-ui.js) en dépend.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .bus import bus
from .ws import manager

logger = logging.getLogger("hackcure.state")

MAX_HISTORY = 100

# Même contenu que l'ancien server.py (ids, noms, âges, chambres, positions)
PATIENT_DEFAULTS: list[dict[str, Any]] = [
    {"patient_id": "patient_01", "name": "Patient A", "age": 72, "room": "101", "room_position": {"x": -4.0, "z": -4.0}},
    {"patient_id": "patient_02", "name": "Patient B", "age": 68, "room": "102", "room_position": {"x": 4.0, "z": -4.0}},
    {"patient_id": "patient_03", "name": "Patient C", "age": 81, "room": "103", "room_position": {"x": -4.0, "z": 4.0}},
    {"patient_id": "patient_04", "name": "Patient D", "age": 75, "room": "104", "room_position": {"x": 4.0, "z": 4.0}},
]


def _fresh_patient(base: dict[str, Any]) -> dict[str, Any]:
    return {
        **base,
        "state": "normal",
        "fall_detected": False,
        "pain_detected": False,
        "confidence": 0.0,
        "last_event_time": None,
        "alert_priority": "none",
        "source": "system",
        # champs IA du pipeline comportemental (Amal a4fa849)
        "risk_level": "none",
        "risk_score": 0.0,
        "behavior_indicators": [],
        "recommendations": [],
        # panne d'équipement (Amal 384ae87)
        "machine_error": False,
        "machine_type": "",
    }


patients: dict[str, dict[str, Any]] = {p["patient_id"]: _fresh_patient(p) for p in PATIENT_DEFAULTS}
event_history: list[dict[str, Any]] = []
current_mode: dict[str, str] = {"mode": "demo"}

# room code -> patient_id (mis à jour par le seed / les admissions)
room_to_patient: dict[str, str] = {p["room"]: p["patient_id"] for p in PATIENT_DEFAULTS}

# Cache des états de chambre (contrat room_state, section 6.2)
room_states: dict[str, dict[str, Any]] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def patient_for_room(room: str) -> str | None:
    return room_to_patient.get(str(room))


def room_for_patient(patient_id: str) -> str | None:
    p = patients.get(patient_id)
    return p["room"] if p else None


def register_patient(patient_id: str, name: str, age: int | None, room: str | None) -> None:
    """Ajoute/actualise un patient legacy (appelé par le seed et le CRUD patients)."""
    base = patients.get(patient_id) or _fresh_patient({"patient_id": patient_id, "name": name, "age": age, "room": room, "room_position": {"x": 0, "z": 0}})
    base["name"] = name
    base["age"] = age
    if room:
        # une chambre n'héberge qu'un patient actif
        for r, pid in list(room_to_patient.items()):
            if pid == patient_id and r != room:
                del room_to_patient[r]
        room_to_patient[str(room)] = patient_id
        base["room"] = str(room)
    patients[patient_id] = base


def unregister_patient(patient_id: str) -> None:
    patients.pop(patient_id, None)
    for r, pid in list(room_to_patient.items()):
        if pid == patient_id:
            del room_to_patient[r]


def state_from_flags(fall: bool, pain: bool) -> str:
    if fall and pain:
        return "fall_and_pain"
    if fall:
        return "fall_detected"
    if pain:
        return "pain_detected"
    return "normal"


async def process_event(
    patient_id: str,
    event_type: str,
    source: str = "demo",
    confidence: float = 0.90,
    risk_level: str = "none",
    risk_score: float = 0.0,
    behavior_indicators: list | None = None,
    recommendations: list | None = None,
    machine_type: str = "",
) -> dict[str, Any] | None:
    """Met à jour l'état d'un patient et diffuse `patient_event` (comportement d'origine + champs de risque comportemental)."""
    if patient_id not in patients:
        logger.warning("Unknown patient: %s", patient_id)
        return None

    patient = patients[patient_id]
    now = now_iso()
    behavior_indicators = list(behavior_indicators or [])
    recommendations = list(recommendations or [])

    if event_type == "fall":
        patient["fall_detected"], patient["pain_detected"] = True, False
        patient["state"], patient["alert_priority"] = "fall_detected", "critical"
        risk_level, risk_score = "critical", max(risk_score, 0.95)
    elif event_type == "pain":
        patient["fall_detected"], patient["pain_detected"] = False, True
        patient["state"], patient["alert_priority"] = "pain_detected", "high"
        risk_level = "high" if risk_level == "none" else risk_level
    elif event_type == "fall_and_pain":
        patient["fall_detected"], patient["pain_detected"] = True, True
        patient["state"], patient["alert_priority"] = "fall_and_pain", "critical"
        risk_level, risk_score = "critical", max(risk_score, 0.95)
    elif event_type == "behavioral_risk":
        pass  # met à jour le risque sans forcer chute ni douleur
    elif event_type == "recover":
        patient["fall_detected"], patient["pain_detected"] = False, False
        patient["machine_error"], patient["machine_type"] = False, ""
        patient["state"], patient["alert_priority"] = "normal", "none"
        risk_level, risk_score, behavior_indicators, recommendations = "none", 0.0, [], []
    elif event_type == "machine_error":
        patient["machine_error"], patient["machine_type"] = True, machine_type
        patient["state"], patient["alert_priority"] = "machine_error", "high"
        risk_level = "high" if risk_level == "none" else risk_level
    else:
        logger.warning("Unknown event type: %s", event_type)
        return None

    patient["confidence"] = confidence
    patient["last_event_time"] = now
    patient["source"] = source
    patient["risk_level"] = risk_level
    patient["risk_score"] = risk_score
    patient["behavior_indicators"] = behavior_indicators
    patient["recommendations"] = recommendations

    event = {
        "type": "patient_event",
        "patient_id": patient_id,
        "event_type": event_type,
        "source": source,
        "fall_detected": patient["fall_detected"],
        "pain_detected": patient["pain_detected"],
        "state": patient["state"],
        "confidence": confidence,
        "alert_priority": patient["alert_priority"],
        "risk_level": risk_level,
        "risk_score": risk_score,
        "behavior_indicators": behavior_indicators,
        "recommendations": recommendations,
        "machine_error": patient.get("machine_error", False),
        "machine_type": patient.get("machine_type", ""),
        "timestamp": now,
        "room": patient.get("room"),
    }

    event_history.insert(0, event)
    if len(event_history) > MAX_HISTORY:
        event_history.pop()

    await manager.broadcast(event)
    await bus.publish(f"internal/patient_event/{patient_id}", event)
    # propagation vers room_state (3D, n8n) et vers le VisionAgent → RiskAgent
    room = patient.get("room")
    if room:
        behavior = {"risk_level": risk_level, "risk_score": risk_score, "indicators": behavior_indicators, "recommendations": recommendations, "source": source, "ts": now}
        rs = room_states.get(str(room))
        if rs is not None:
            rs["behavior"] = behavior
        if event_type == "behavioral_risk":  # les autres événements gardent exactement les messages d'origine
            await manager.broadcast({"type": "behavior", "room": str(room), "patient_id": patient_id, **behavior})
        if event_type in ("behavioral_risk", "recover"):
            await bus.publish("internal/behavior", {"room": str(room), "patient_id": patient_id, "event_type": event_type, **behavior})
        if event_type in ("machine_error", "recover"):  # → VitalsAgent : risque « panne d'équipement » rattaché à l'appareil
            await bus.publish("internal/machine_error", {"room": str(room), "patient_id": patient_id, "active": event_type == "machine_error", "machine_type": machine_type, "source": source})
    logger.info("[%s] %s: %s (conf=%.2f, risk=%s)", source.upper(), patient_id, event_type, confidence, risk_level)
    return event


async def machine_fault(room: str, label: str | None) -> None:
    """Reflète dans l'état legacy (cartes, 3D d'Amal) une panne détectée par le flux d'un appareil, ou sa levée."""
    pid = patient_for_room(room)
    patient = patients.get(pid) if pid else None
    if not patient or (bool(label) == bool(patient.get("machine_error")) and (label or "") == patient.get("machine_type", "")):
        return
    if label and patient.get("machine_error"):  # déjà signalée (événement machine_error) : on garde le libellé d'origine
        return
    patient["machine_error"], patient["machine_type"] = bool(label), label or ""
    if not (patient["fall_detected"] or patient["pain_detected"]):  # une chute ou une douleur garde la priorité d'affichage
        patient["state"], patient["alert_priority"] = ("machine_error", "high") if label else ("normal", "none")
    now = now_iso()
    patient["last_event_time"] = now
    event = {
        "type": "patient_event", "patient_id": pid, "event_type": "machine_error" if label else "machine_repaired", "source": "device",
        "fall_detected": patient["fall_detected"], "pain_detected": patient["pain_detected"], "state": patient["state"], "confidence": 1.0,
        "alert_priority": patient["alert_priority"], "risk_level": patient["risk_level"], "risk_score": patient["risk_score"],
        "behavior_indicators": patient["behavior_indicators"], "recommendations": patient["recommendations"],
        "machine_error": patient["machine_error"], "machine_type": patient["machine_type"], "timestamp": now, "room": str(room),
    }
    event_history.insert(0, event)
    if len(event_history) > MAX_HISTORY:
        event_history.pop()
    await manager.broadcast(event)


async def reset_all(source: str = "system") -> None:
    for pid in list(patients):
        await process_event(pid, "recover", source=source, confidence=1.0)
    event_history.clear()
    await manager.broadcast({"type": "reset", "patients": patients})
    await bus.publish("internal/reset", {})


async def set_mode(mode: str) -> None:
    current_mode["mode"] = mode
    await manager.broadcast({"type": "mode_change", "mode": mode})
    await bus.publish("internal/mode", {"mode": mode})
    logger.info("Mode switched to: %s", mode)


def init_message() -> dict[str, Any]:
    """Message `init` envoyé à chaque nouveau client WebSocket (champs d'origine + extensions)."""
    return {
        "type": "init",
        "patients": patients,
        "mode": current_mode["mode"],
        "event_history": event_history[:20],
        "room_states": room_states,
    }

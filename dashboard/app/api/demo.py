"""
Endpoints d'origine (démo, mode, YOLO) — comportement inchangé.
Restent accessibles sans authentification en mode démo (règle du prompt).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import state

router = APIRouter(tags=["legacy"])


class DemoEvent(BaseModel):
    patient_id: str
    event_type: str  # "fall", "pain", "fall_and_pain", "recover", "behavioral_risk", "machine_error"
    confidence: float = 0.90
    risk_level: str = "none"  # none, low, moderate, high, critical
    risk_score: float = 0.0
    behavior_indicators: list[str] = []
    recommendations: list[str] = []
    machine_type: str = ""  # ex. "IV Pump", "ECG Monitor" (machine_error)


class ModeSwitch(BaseModel):
    mode: str  # "demo" or "real"


@router.get("/api/patients")
async def get_patients():
    """État courant de tous les patients (structure legacy)."""
    return JSONResponse(content=state.patients)


@router.get("/api/events")
async def get_events(request: Request, since: str | None = None, hours: int | None = None):
    """Sans paramètre : historique legacy (50 derniers `patient_event`).
    Avec `since` (ISO) ou `hours` : événements structurés (risques, postures, humeurs, visites) pour n8n `shift-report`."""
    if since is None and hours is None:
        return JSONResponse(content=state.event_history[:50])
    from .. import auth as authlib

    authlib.get_current_user(request)  # données cliniques : session ou jeton de service
    from datetime import datetime, timedelta, timezone

    from sqlmodel import select

    from ..db import session_scope
    from ..models import MoodObservation, PatientStateSnapshot, Risk, StaffVisit
    from ..risks import risk_dict

    try:
        start = datetime.fromisoformat(since) if since else datetime.now(timezone.utc) - timedelta(hours=hours or 12)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    except ValueError:
        return JSONResponse(content={"error": "since invalide (ISO 8601)"}, status_code=400)
    with session_scope() as s:
        risks = [risk_dict(s, r, with_plan=True) for r in s.exec(select(Risk).where(Risk.detected_at >= start).order_by(Risk.detected_at)).all()]
        snaps = s.exec(select(PatientStateSnapshot).where(PatientStateSnapshot.ts >= start).order_by(PatientStateSnapshot.ts)).all()
        events, last = [], {}
        for sn in snaps:
            key = (sn.posture, sn.activity)
            if last.get(sn.room_code) != key:
                events.append({"ts": sn.ts.isoformat(), "room": sn.room_code, "posture": sn.posture, "activity": sn.activity, "persons": sn.persons})
                last[sn.room_code] = key
        moods = [{"ts": m.ts.isoformat(), "room": m.room_code, "mood": m.mood, "note": m.note} for m in s.exec(select(MoodObservation).where(MoodObservation.ts >= start).order_by(MoodObservation.ts)).all()]
        visits = [{"room": v.room_code, "started_at": v.started_at.isoformat(), "ended_at": v.ended_at.isoformat() if v.ended_at else None, "persons": v.persons, "risk_id": v.risk_id} for v in s.exec(select(StaffVisit).where(StaffVisit.started_at >= start)).all()]
    from ..ingest import handler

    rooms = {r: {k: handler.room_state(r).get(k) for k in ("posture", "activity", "expression", "vitals", "env", "riskLevel", "patient_id", "skinTempC")} for r in handler.ROOMS}
    return JSONResponse(content={"since": start.isoformat(), "risks": risks, "state_events": events, "moods": moods, "visits": visits, "rooms": rooms, "legacy_events": state.event_history[:50]}, headers={"Cache-Control": "no-store"})


@router.post("/api/demo/trigger")
async def trigger_demo_event(event: DemoEvent):
    if state.current_mode["mode"] != "demo":
        return JSONResponse(content={"error": "Demo events only allowed in demo mode"}, status_code=400)
    await state.process_event(
        patient_id=event.patient_id,
        event_type=event.event_type,
        source="simulation",
        confidence=event.confidence,
        risk_level=event.risk_level,
        risk_score=event.risk_score,
        behavior_indicators=event.behavior_indicators,
        recommendations=event.recommendations,
        machine_type=event.machine_type,
    )
    return JSONResponse(content={"status": "ok", "event": event.event_type})


@router.post("/api/demo/reset")
async def reset_demo():
    await state.reset_all()
    return JSONResponse(content={"status": "reset"})


@router.post("/api/mode")
async def switch_mode(mode: ModeSwitch):
    if mode.mode not in ("demo", "real"):
        return JSONResponse(content={"error": "Mode must be 'demo' or 'real'"}, status_code=400)
    await state.set_mode(mode.mode)
    return JSONResponse(content={"status": "ok", "mode": mode.mode})


@router.post("/api/yolo/event")
async def receive_yolo_event(event: DemoEvent):
    """Événements YOLO réels envoyés par camera_loop.py (scénario A)."""
    await state.process_event(
        patient_id=event.patient_id,
        event_type=event.event_type,
        source="yolo",
        confidence=event.confidence,
        risk_level=event.risk_level,
        risk_score=event.risk_score,
        behavior_indicators=event.behavior_indicators,
        recommendations=event.recommendations,
        machine_type=event.machine_type,
    )
    return JSONResponse(content={"status": "ok"})

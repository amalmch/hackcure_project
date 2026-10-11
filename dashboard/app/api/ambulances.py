"""
Ambulances (V2, étape 5) : fiche d'intervention, position et ETA en temps réel, réservation de chambre,
suivi GPS réel par un téléphone (`/ambulance/track/{jeton}`).
"""

from __future__ import annotations

import json
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlmodel import Session, func, select

from .. import ambulance as geo
from .. import auth as authlib
from ..agents import ambulance as agent
from ..audit import audit
from ..config import STATIC_DIR, settings
from ..db import get_session
from ..ingest import handler
from ..models import Admission, AmbulanceMission, Patient, Room
from ..ws import manager

router = APIRouter(tags=["ambulances"])


def free_rooms(session: Session) -> list[str]:
    occupied = set(session.exec(select(Admission.room_code).where(Admission.discharged_at.is_(None))).all())
    reserved = set(session.exec(select(AmbulanceMission.reserved_room).where(AmbulanceMission.status.in_(agent.ACTIVE))).all())
    return [r.code for r in session.exec(select(Room).order_by(Room.code)).all() if r.code not in occupied and r.code not in reserved]


class NewPatient(BaseModel):
    first_name: str
    last_name: str
    age: int = 60
    sex: str = "M"
    allergies: str = ""
    history: str = ""


class MissionIn(BaseModel):
    patient_id: Optional[str] = None  # patient existant…
    new_patient: Optional[NewPatient] = None  # …ou nouveau
    reason: str
    emergency_type: str = "other"
    severity: int = 2
    vitals: dict[str, Any] = {}
    mode: str = "sim"  # sim | gps
    route: str = "marsa"
    ambulance: str = "AMB-01"
    time_scale: Optional[float] = None  # démo : accélère ce trajet simulé


class TrackIn(BaseModel):
    lat: float
    lon: float
    speed_kmh: Optional[float] = None
    accuracy_m: Optional[float] = None
    arrived: bool = False


@router.get("/api/ambulances")
def ambulances(session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_ambulances"))):
    since = datetime.now(timezone.utc) - timedelta(hours=12)
    rows = session.exec(select(AmbulanceMission).where(AmbulanceMission.departed_at >= since).order_by(AmbulanceMission.id.desc()).limit(30)).all()
    return {"clinic": geo.CLINIC, "types": geo.EMERGENCY_TYPES, "severities": geo.SEVERITY, "routes": {k: {"label": v["label"], "km": round(geo.route_length_m(v["points"]) / 1000, 1)} for k, v in geo.ROUTES.items()},
            "free_rooms": free_rooms(session), "time_scale": settings.ambulance_time_scale, "missions": [agent.mission_out(m) for m in rows]}


@router.post("/api/ambulances/missions", status_code=201)
async def create_mission(body: MissionIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("manage_ambulances"))):
    """Départ d'une ambulance pour un patient : la chambre adaptée est réservée immédiatement."""
    if body.emergency_type not in geo.EMERGENCY_TYPES or body.severity not in geo.SEVERITY or body.mode not in ("sim", "gps"):
        raise HTTPException(400, "Type d'urgence, gravité ou mode invalide")
    if body.patient_id:
        p = session.exec(select(Patient).where(Patient.patient_id == body.patient_id)).first()
        if not p:
            raise HTTPException(404, "Patient introuvable")
        if session.exec(select(Admission).where(Admission.patient_id == p.id, Admission.discharged_at.is_(None))).first():
            raise HTTPException(409, "Ce patient est déjà hospitalisé")
    elif body.new_patient:
        n = session.exec(select(func.count(Patient.id))).one()
        while session.exec(select(Patient).where(Patient.patient_id == f"patient_{n + 1:02d}")).first() or session.exec(select(Patient).where(Patient.code == f"PAT-{n + 1:04d}")).first():
            n += 1
        np = body.new_patient
        p = Patient(patient_id=f"patient_{n + 1:02d}", code=f"PAT-{n + 1:04d}", display_name=f"{np.first_name} {np.last_name}", first_name=np.first_name, last_name=np.last_name,
                    birth_date=date(date.today().year - max(0, np.age), 6, 15), sex=np.sex, allergies=np.allergies, history=np.history)
        session.add(p)
        session.flush()
    else:
        raise HTTPException(400, "Patient existant (patient_id) ou nouveau patient requis")
    room = geo.choose_room(body.emergency_type, free_rooms(session))
    if not room:
        raise HTTPException(409, "Aucune chambre libre : faire la sortie d'un patient avant le départ de l'ambulance")
    route = geo.ROUTES.get(body.route) or geo.ROUTES["marsa"]
    pts = route["points"]
    now = datetime.now(timezone.utc)
    total = geo.route_length_m(pts)
    scale = max(0.1, min(60.0, body.time_scale)) if body.time_scale else settings.ambulance_time_scale
    m = AmbulanceMission(ambulance_code=body.ambulance, patient_pk=p.id, patient_id=p.patient_id, patient_name=p.full_name, age=p.age, sex=p.sex, reason=body.reason.strip()[:300], emergency_type=body.emergency_type,
                         severity=body.severity, vitals_json=json.dumps(body.vitals, ensure_ascii=False), mode=body.mode, status="en_route", departed_at=now, reserved_room=room, lat=pts[0][0], lon=pts[0][1],
                         remaining_m=total, route_json=json.dumps(pts if body.mode == "sim" else []), route_label=route["label"] if body.mode == "sim" else "GPS réel (téléphone)", track_token=secrets.token_urlsafe(10),
                         eta_at=now + timedelta(seconds=geo.eta_seconds(total, 40.0) / (scale if body.mode == "sim" else 1.0)), time_scale=scale if body.time_scale else 0.0,
                         preparation_json=json.dumps(geo.PREPARATION.get(body.emergency_type, geo.PREPARATION["other"]), ensure_ascii=False))
    session.add(m)
    audit(session, user, "dispatch", "ambulance_mission", p.patient_id, {"room": room, "type": body.emergency_type, "mode": body.mode})
    session.commit()
    session.refresh(m)
    agent.set_reservation(room, m)
    out = agent.mission_out(m)
    await agent.dispatch(m.id)
    return out


@router.post("/api/ambulances/missions/{mission_id}/cancel")
async def cancel_mission(mission_id: int, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("manage_ambulances"))):
    m = session.get(AmbulanceMission, mission_id)
    if not m:
        raise HTTPException(404, "Mission introuvable")
    if m.status in agent.ACTIVE:
        m.status = "cancelled"
        audit(session, user, "cancel", "ambulance_mission", mission_id)
        session.commit()
        session.refresh(m)
        agent.set_reservation(m.reserved_room, None)
    out = agent.mission_out(m, False)
    await manager.broadcast({"type": "ambulance", "event": "cancelled", "mission": out})
    return out


# ─── suivi GPS réel : page ouverte sur le téléphone de l'équipe ──────────────
def _by_token(session: Session, token: str) -> AmbulanceMission:
    m = session.exec(select(AmbulanceMission).where(AmbulanceMission.track_token == token)).first()
    if not m:
        raise HTTPException(404, "Mission introuvable")
    return m


@router.get("/api/ambulances/track/{token}")
def track_info(token: str, session: Session = Depends(get_session)):
    m = _by_token(session, token)
    return {"ambulance": m.ambulance_code, "status": m.status, "patient": m.patient_name, "room": m.reserved_room, "clinic": geo.CLINIC, "eta_minutes": agent.mission_out(m, False)["eta_minutes"]}


@router.post("/api/ambulances/track/{token}")
async def track_position(token: str, body: TrackIn, session: Session = Depends(get_session)):
    """Position GPS envoyée toutes les 2 s par le téléphone (API Geolocation du navigateur)."""
    m = _by_token(session, token)
    if m.status != "en_route":
        return {"status": m.status}
    if not (-90 <= body.lat <= 90 and -180 <= body.lon <= 180):
        raise HTTPException(400, "Coordonnées invalides")
    if m.mode != "gps":  # le téléphone prend la main sur le trajet simulé
        m.mode, m.route_json, m.route_label = "gps", "[]", "GPS réel (téléphone)"
    prev = (m.lat, m.lon)
    m.lat, m.lon = body.lat, body.lon
    if body.speed_kmh is not None and body.speed_kmh >= 0:
        m.speed_kmh = min(130.0, body.speed_kmh)
    m.remaining_m = 0.0 if body.arrived else geo.haversine_m((m.lat, m.lon), (geo.CLINIC["lat"], geo.CLINIC["lon"]))
    if geo.haversine_m(prev, (m.lat, m.lon)) > 3:
        import math

        m.heading = (math.degrees(math.atan2(m.lon - prev[1], m.lat - prev[0])) + 360) % 360
    trail = json.loads(m.route_json or "[]")
    trail.append([round(m.lat, 6), round(m.lon, 6)])
    m.route_json = json.dumps(trail[-600:])
    m.eta_at = datetime.now(timezone.utc) + timedelta(seconds=geo.eta_seconds(m.remaining_m, m.speed_kmh))
    session.commit()
    session.refresh(m)
    return {"status": m.status, "remaining_m": round(m.remaining_m), "eta_minutes": agent.mission_out(m, False)["eta_minutes"]}


@router.get("/ambulance/track/{token}", response_class=HTMLResponse)
def track_page(token: str, session: Session = Depends(get_session)):
    _by_token(session, token)
    return HTMLResponse((STATIC_DIR / "ambulance-track.html").read_text(encoding="utf-8"))

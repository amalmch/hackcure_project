"""Personnel présent : liste, service, présence par chambre, visites."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import auth as authlib
from ..audit import audit
from ..db import get_session
from ..ingest import handler
from ..models import Staff, StaffVisit

router = APIRouter(prefix="/api/staff", tags=["staff"])

ROLE_FR = {"nurse": "Infirmier(ère)", "duty_doctor": "Médecin de garde", "general_doctor": "Médecin", "pharmacist": "Pharmacien(ne)", "receptionist": "Réceptionniste", "aide": "Aide-soignant(e)"}


class StaffPatch(BaseModel):
    on_duty: Optional[bool] = None
    current_room: Optional[str] = None
    phone: Optional[str] = None


class StaffIn(BaseModel):
    name: str
    role: str
    on_duty: bool = True
    phone: str = ""


def _out(s: Staff) -> dict:
    return {"id": s.id, "name": s.name, "role": s.role, "role_label": ROLE_FR.get(s.role, s.role), "on_duty": s.on_duty, "phone": s.phone, "current_room": s.current_room}


@router.get("")
def list_staff(session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.can_view_clinical)):
    rows = session.exec(select(Staff).order_by(Staff.on_duty.desc(), Staff.role, Staff.name)).all()
    presence = {r: {"staffPresent": bool(handler.room_state(r).get("staffPresent")), "persons": handler.room_state(r).get("persons")} for r in handler.ROOMS}
    return {"staff": [_out(s) for s in rows], "presence": presence, "on_duty": sum(1 for s in rows if s.on_duty)}


@router.post("", status_code=201)
def create_staff(body: StaffIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_manage_risks)):
    s = Staff(name=body.name.strip(), role=body.role, on_duty=body.on_duty, phone=body.phone)
    session.add(s)
    session.flush()
    audit(session, user, "create", "staff", s.id, {"name": s.name, "role": s.role})
    session.commit()
    session.refresh(s)
    return _out(s)


@router.patch("/{staff_id}")
def patch_staff(staff_id: int, body: StaffPatch, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_manage_risks)):
    s = session.get(Staff, staff_id)
    if not s:
        raise HTTPException(404, "Membre du personnel introuvable")
    if body.on_duty is not None:
        s.on_duty = body.on_duty
        if not body.on_duty:
            s.current_room = None
    if body.current_room is not None:
        s.current_room = body.current_room or None
    if body.phone is not None:
        s.phone = body.phone
    audit(session, user, "update", "staff", staff_id, body.model_dump(exclude_none=True))
    session.commit()
    session.refresh(s)
    return _out(s)


@router.get("/visits")
def visits(room: Optional[str] = None, limit: int = Query(30, le=300), session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.can_view_clinical)):
    q = select(StaffVisit)
    if room:
        q = q.where(StaffVisit.room_code == room)
    rows = session.exec(q.order_by(StaffVisit.started_at.desc()).limit(limit)).all()
    return [{"id": v.id, "room": v.room_code, "started_at": v.started_at, "ended_at": v.ended_at, "persons": v.persons, "risk_id": v.risk_id, "staff_name": v.staff_name,
             "duration_s": (round((v.ended_at - v.started_at).total_seconds()) if v.ended_at else None)} for v in rows]

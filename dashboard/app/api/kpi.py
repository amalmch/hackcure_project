"""Indicateurs du bandeau KPI."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from .. import auth as authlib
from ..db import get_session
from ..ingest import handler
from ..models import Admission, Medication, Risk, Room, Staff

router = APIRouter(prefix="/api/kpi", tags=["kpi"])


def compute_kpi(session: Session) -> dict:
    patients = session.exec(select(func.count(Admission.id)).where(Admission.discharged_at.is_(None))).one()
    rooms = session.exec(select(func.count(Room.id))).one()
    risks = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    open_rows = session.exec(select(Risk.severity, func.count(Risk.id)).where(Risk.status.in_(["open", "in_progress", "escalated"])).group_by(Risk.severity)).all()
    for sev, n in open_rows:
        risks[sev] = n
    staff_on_duty = session.exec(select(func.count(Staff.id)).where(Staff.on_duty.is_(True))).one()
    staff_in_rooms = sum(1 for r in handler.ROOMS if handler.room_state(r).get("staffPresent"))
    temps = [handler.room_state(r)["env"].get("tempC") for r in handler.ROOMS]
    temps = [t for t in temps if t is not None]
    hums = [handler.room_state(r)["env"].get("humidity") for r in handler.ROOMS]
    hums = [h for h in hums if h is not None]
    spo2 = [(handler.room_state(r).get("vitals", {}).get("spo2"), r) for r in handler.ROOMS]
    spo2 = [x for x in spo2 if x[0] is not None]
    spo2_min = min(spo2) if spo2 else None
    meds = session.exec(select(Medication)).all()
    low = sum(1 for m in meds if m.low_stock)
    expiring = sum(1 for m in meds if m.expiring_within(60))
    return {
        "patients": patients,
        "rooms": rooms,
        "open_risks": sum(risks.values()),
        "risks": risks,
        "staff_on_duty": staff_on_duty,
        "staff_in_rooms": staff_in_rooms,
        "avg_temp": round(sum(temps) / len(temps), 2) if temps else None,
        "avg_humidity": round(sum(hums) / len(hums), 1) if hums else None,
        "spo2_min": spo2_min[0] if spo2_min else None,
        "spo2_min_room": spo2_min[1] if spo2_min else None,
        "pharmacy_alerts": low + expiring,
        "low_stock": low,
        "expiring": expiring,
        "date": date.today().isoformat(),
    }


@router.get("")
def kpi(session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.get_current_user)):
    return compute_kpi(session)

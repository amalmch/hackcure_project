"""Patients : CRUD, fiche, admission / sortie, historique."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, func, select

from .. import auth as authlib, state
from ..audit import audit
from ..db import get_session
from ..ingest import handler
from ..models import Admission, Medication, MedicalReport, MoodObservation, Patient, PatientStateSnapshot, Prescription, PrescriptionLine, Risk, Room, Treatment
from ..risks import risk_dict

router = APIRouter(prefix="/api/records", tags=["patients"])


class PatientIn(BaseModel):
    first_name: str
    last_name: str
    birth_date: date
    sex: str = "M"
    allergies: str = ""
    blood_group: str = "O+"
    fall_risk: str = "medium"
    history: str = ""
    display_name: Optional[str] = None
    room: Optional[str] = None
    reason: str = ""
    referring_doctor: str = ""


class PatientPatch(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    birth_date: Optional[date] = None
    sex: Optional[str] = None
    allergies: Optional[str] = None
    blood_group: Optional[str] = None
    fall_risk: Optional[str] = None
    history: Optional[str] = None
    display_name: Optional[str] = None


class AdmitIn(BaseModel):
    room: str
    reason: str = ""
    referring_doctor: str = ""


def _active(session: Session, p: Patient) -> Optional[Admission]:
    return session.exec(select(Admission).where(Admission.patient_id == p.id, Admission.discharged_at.is_(None))).first()


def _out(session: Session, p: Patient) -> dict:
    adm = _active(session, p)
    return {
        "id": p.id, "patient_id": p.patient_id, "code": p.code, "display_name": p.display_name, "first_name": p.first_name, "last_name": p.last_name, "full_name": p.full_name,
        "birth_date": p.birth_date, "age": p.age, "sex": p.sex, "allergies": p.allergies, "allergy_list": p.allergy_list, "blood_group": p.blood_group, "fall_risk": p.fall_risk, "history": p.history,
        "room": adm.room_code if adm else None, "admission": None if not adm else {"id": adm.id, "admitted_at": adm.admitted_at, "reason": adm.reason, "referring_doctor": adm.referring_doctor},
        "legacy_state": state.patients.get(p.patient_id, {}).get("state"),
    }


@router.get("")
def list_patients(q: Optional[str] = None, active_only: bool = False, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_patients"))):
    rows = session.exec(select(Patient).order_by(Patient.code)).all()
    out = [_out(session, p) for p in rows]
    if q:
        ql = q.lower()
        out = [o for o in out if ql in f"{o['full_name']} {o['code']} {o['patient_id']} {o['room']}".lower()]
    if active_only:
        out = [o for o in out if o["room"]]
    return out


@router.get("/{patient_id}")
def get_patient(patient_id: str, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_patients"))):
    p = _find(session, patient_id)
    d = _out(session, p)
    adm = _active(session, p)
    if adm:
        d["treatments"] = [{"id": t.id, "medication_id": m.id, "dci": m.dci, "brand": m.brand, "dosage": m.dosage, "posology": t.posology, "route": t.route, "start": t.start, "prescriber": t.prescriber}
                           for t, m in session.exec(select(Treatment, Medication).join(Medication, Medication.id == Treatment.medication_id).where(Treatment.admission_id == adm.id, Treatment.end.is_(None))).all()]
        d["open_risks"] = [risk_dict(session, r, with_plan=False) for r in session.exec(select(Risk).where(Risk.admission_id == adm.id, Risk.status.in_(("open", "in_progress", "escalated")))).all()]
        d["room_state"] = handler.room_state(adm.room_code)
    return d


@router.get("/{patient_id}/history")
def history(patient_id: str, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_history"))):
    p = _find(session, patient_id)
    out = {"patient": _out(session, p), "admissions": []}
    for adm in session.exec(select(Admission).where(Admission.patient_id == p.id).order_by(Admission.admitted_at.desc())).all():
        reports = session.exec(select(MedicalReport).where(MedicalReport.admission_id == adm.id).order_by(MedicalReport.created_at)).all()
        prescriptions = session.exec(select(Prescription).where(Prescription.admission_id == adm.id).order_by(Prescription.created_at)).all()
        risks = session.exec(select(Risk).where(Risk.admission_id == adm.id).order_by(Risk.detected_at)).all()
        treatments = session.exec(select(Treatment, Medication).join(Medication, Medication.id == Treatment.medication_id).where(Treatment.admission_id == adm.id)).all()
        moods = session.exec(select(MoodObservation.mood, func.count(MoodObservation.id)).where(MoodObservation.admission_id == adm.id).group_by(MoodObservation.mood)).all()
        n_snap = session.exec(select(func.count(PatientStateSnapshot.id)).where(PatientStateSnapshot.admission_id == adm.id)).one()
        out["admissions"].append({
            "id": adm.id, "room": adm.room_code, "admitted_at": adm.admitted_at, "discharged_at": adm.discharged_at, "reason": adm.reason, "referring_doctor": adm.referring_doctor, "active": adm.active,
            "reports": [{"id": r.id, "title": r.title, "author": r.author, "status": r.status, "ai_draft": r.ai_draft, "created_at": r.created_at, "signed_at": r.signed_at} for r in reports],
            "prescriptions": [{"id": pr.id, "prescriber": pr.prescriber, "status": pr.status, "created_at": pr.created_at, "lines": session.exec(select(func.count(PrescriptionLine.id)).where(PrescriptionLine.prescription_id == pr.id)).one()} for pr in prescriptions],
            "risks": [{"id": r.id, "type": r.type, "title": r.title, "severity": r.severity, "status": r.status, "detected_at": r.detected_at, "resolved_by": r.resolved_by} for r in risks],
            "treatments": [{"dci": m.dci, "brand": m.brand, "posology": t.posology, "route": t.route, "start": t.start, "end": t.end} for t, m in treatments],
            "moods": {m: n for m, n in moods}, "snapshots": n_snap,
        })
    return out


@router.post("", status_code=201)
def create_patient(body: PatientIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("create_patients"))):
    n = session.exec(select(func.count(Patient.id))).one()
    code = f"PAT-{n + 1:04d}"
    while session.exec(select(Patient).where(Patient.code == code)).first():
        n += 1
        code = f"PAT-{n + 1:04d}"
    pid = f"patient_{n + 1:02d}"
    while session.exec(select(Patient).where(Patient.patient_id == pid)).first():
        n += 1
        pid = f"patient_{n + 1:02d}"
    p = Patient(patient_id=pid, code=code, display_name=body.display_name or f"{body.first_name} {body.last_name}", first_name=body.first_name, last_name=body.last_name, birth_date=body.birth_date,
                sex=body.sex, allergies=body.allergies, blood_group=body.blood_group, fall_risk=body.fall_risk, history=body.history)
    session.add(p)
    session.flush()
    if body.room:
        _admit(session, p, body.room, body.reason, body.referring_doctor)
    audit(session, user, "create", "patient", p.id, {"code": code})
    session.commit()
    session.refresh(p)
    return _out(session, p)


@router.patch("/{patient_id}")
def patch_patient(patient_id: str, body: PatientPatch, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_edit_patients)):
    p = _find(session, patient_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    audit(session, user, "update", "patient", p.id, body.model_dump(exclude_none=True))
    session.commit()
    session.refresh(p)
    adm = _active(session, p)
    state.register_patient(p.patient_id, p.display_name, p.age, adm.room_code if adm else None)
    return _out(session, p)


@router.delete("/{patient_id}", status_code=204)
def delete_patient(patient_id: str, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("create_patients"))):
    p = _find(session, patient_id)
    if _active(session, p):
        raise HTTPException(400, "Patient hospitalisé : faire la sortie avant suppression")
    if session.exec(select(Admission).where(Admission.patient_id == p.id)).first():
        raise HTTPException(400, "Patient avec historique : suppression refusée (archivage seulement)")
    session.delete(p)
    audit(session, user, "delete", "patient", p.id)
    session.commit()
    state.unregister_patient(p.patient_id)
    return None


@router.post("/{patient_id}/admit")
def admit(patient_id: str, body: AdmitIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_edit_patients)):
    p = _find(session, patient_id)
    if _active(session, p):
        raise HTTPException(400, "Patient déjà hospitalisé")
    _admit(session, p, body.room, body.reason, body.referring_doctor)
    audit(session, user, "admit", "patient", p.id, {"room": body.room})
    session.commit()
    return _out(session, p)


@router.post("/{patient_id}/discharge")
def discharge(patient_id: str, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_edit_patients)):
    p = _find(session, patient_id)
    adm = _active(session, p)
    if not adm:
        raise HTTPException(400, "Patient non hospitalisé")
    adm.discharged_at = datetime.now(timezone.utc)
    for t in session.exec(select(Treatment).where(Treatment.admission_id == adm.id, Treatment.end.is_(None))).all():
        t.end = adm.discharged_at
    audit(session, user, "discharge", "patient", p.id, {"room": adm.room_code})
    session.commit()
    state.unregister_patient(p.patient_id)
    vacate_room(adm.room_code)
    return _out(session, p)


def vacate_room(room: str) -> None:
    """Chambre libre : plus de patient, plus de constantes ; le simulateur embarqué cesse de publier pour elle."""
    rs = handler.room_state(room)
    rs.update(patient_id=None, posture="absent", activity="out_of_room", zone="none", persons=0, expression="neutral", skinTempC=None, vitals={}, devices={}, staffPresent=False, staffRole=None, vacant=True)
    try:
        from ..sim import embedded

        if embedded.engine is not None:
            embedded.engine.set_occupied(room, False)
    except Exception:
        pass
    handler._dirty_rooms.add(room)


def _admit(session: Session, p: Patient, room: str, reason: str, doctor: str) -> Admission:
    if not session.exec(select(Room).where(Room.code == room)).first():
        raise HTTPException(404, "Chambre inconnue")
    if session.exec(select(Admission).where(Admission.room_code == room, Admission.discharged_at.is_(None))).first():
        raise HTTPException(409, f"Chambre {room} occupée")
    adm = Admission(patient_id=p.id, room_code=room, reason=reason, referring_doctor=doctor)
    session.add(adm)
    session.flush()
    state.register_patient(p.patient_id, p.display_name, p.age, room)
    handler.room_state(room)["patient_id"] = p.patient_id
    return adm


def _find(session: Session, patient_id: str) -> Patient:
    p = session.exec(select(Patient).where(Patient.patient_id == patient_id)).first()
    if not p and patient_id.isdigit():
        p = session.get(Patient, int(patient_id))
    if not p:
        p = session.exec(select(Patient).where(Patient.code == patient_id)).first()
    if not p:
        raise HTTPException(404, "Patient introuvable")
    return p

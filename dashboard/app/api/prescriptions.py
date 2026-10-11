"""Ordonnances : lignes depuis l'inventaire, alerte allergie, signature, impression."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import auth as authlib
from ..audit import audit
from ..db import get_session
from ..models import Admission, Medication, Patient, Prescription, PrescriptionLine
from .pharmacy import allergy_conflicts, med_out

router = APIRouter(prefix="/api/prescriptions", tags=["prescriptions"])


class LineIn(BaseModel):
    medication_id: int
    dosage: str = ""
    frequency: str = ""
    duration_days: int = 5
    route: str = "PO"


class PrescriptionIn(BaseModel):
    admission_id: int
    notes: str = ""
    lines: list[LineIn] = []


class PrescriptionPatch(BaseModel):
    notes: Optional[str] = None
    lines: Optional[list[LineIn]] = None


class CheckIn(BaseModel):
    admission_id: int
    medication_id: int


def _out(session: Session, pr: Prescription) -> dict:
    adm = session.get(Admission, pr.admission_id)
    p = session.get(Patient, adm.patient_id) if adm else None
    lines = []
    for ln in session.exec(select(PrescriptionLine).where(PrescriptionLine.prescription_id == pr.id).order_by(PrescriptionLine.id)).all():
        m = session.get(Medication, ln.medication_id)
        lines.append({"id": ln.id, "medication_id": ln.medication_id, "medication": med_out(m) if m else None, "dosage": ln.dosage, "frequency": ln.frequency, "duration_days": ln.duration_days, "route": ln.route,
                      "allergy_warning": ln.allergy_warning, "conflicts": allergy_conflicts(m, p.allergy_list) if (m and p) else []})
    return {"id": pr.id, "admission_id": pr.admission_id, "room": adm.room_code if adm else None, "patient": p.full_name if p else None, "patient_id": p.patient_id if p else None, "patient_code": p.code if p else None,
            "patient_allergies": p.allergies if p else "", "patient_age": p.age if p else None, "prescriber": pr.prescriber, "status": pr.status, "notes": pr.notes, "created_at": pr.created_at, "signed_at": pr.signed_at,
            "lines": lines, "has_allergy_warning": any(l["allergy_warning"] for l in lines)}


def _apply_lines(session: Session, pr: Prescription, patient: Optional[Patient], lines: list[LineIn]) -> list[dict]:
    for old in session.exec(select(PrescriptionLine).where(PrescriptionLine.prescription_id == pr.id)).all():
        session.delete(old)
    warnings = []
    for ln in lines:
        m = session.get(Medication, ln.medication_id)
        if not m:
            raise HTTPException(404, f"Médicament {ln.medication_id} introuvable")
        conflicts = allergy_conflicts(m, patient.allergy_list) if patient else []
        if conflicts:
            warnings.append({"medication": f"{m.dci} ({m.brand})", "allergies": conflicts})
        session.add(PrescriptionLine(prescription_id=pr.id, medication_id=m.id, dosage=ln.dosage, frequency=ln.frequency, duration_days=ln.duration_days, route=ln.route, allergy_warning=bool(conflicts)))
    return warnings


@router.get("")
def list_prescriptions(admission_id: Optional[int] = None, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_medical_docs"))):
    q = select(Prescription)
    if admission_id:
        q = q.where(Prescription.admission_id == admission_id)
    return [_out(session, pr) for pr in session.exec(q.order_by(Prescription.created_at.desc()).limit(100)).all()]


@router.post("/check")
def check_allergy(body: CheckIn, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_medical_docs"))):
    adm = session.get(Admission, body.admission_id)
    m = session.get(Medication, body.medication_id)
    if not adm or not m:
        raise HTTPException(404, "Admission ou médicament introuvable")
    p = session.get(Patient, adm.patient_id)
    conflicts = allergy_conflicts(m, p.allergy_list) if p else []
    return {"conflicts": conflicts, "warning": (f"ALLERGIE : {p.full_name} est allergique à {', '.join(conflicts)} — {m.dci} ({m.brand}) contre-indiqué" if conflicts else None)}


@router.get("/{prescription_id}")
def get_prescription(prescription_id: int, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_medical_docs"))):
    pr = session.get(Prescription, prescription_id)
    if not pr:
        raise HTTPException(404, "Ordonnance introuvable")
    return _out(session, pr)


@router.post("", status_code=201)
def create_prescription(body: PrescriptionIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_write_medical_docs)):
    adm = session.get(Admission, body.admission_id)
    if not adm:
        raise HTTPException(404, "Admission introuvable")
    p = session.get(Patient, adm.patient_id)
    pr = Prescription(admission_id=adm.id, prescriber=user.name or user.username, notes=body.notes, status="draft")
    session.add(pr)
    session.flush()
    warnings = _apply_lines(session, pr, p, body.lines)
    audit(session, user, "create", "prescription", pr.id, {"lines": len(body.lines), "allergy_warnings": warnings})
    session.commit()
    d = _out(session, pr)
    d["warnings"] = warnings
    return d


@router.patch("/{prescription_id}")
def patch_prescription(prescription_id: int, body: PrescriptionPatch, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_write_medical_docs)):
    pr = session.get(Prescription, prescription_id)
    if not pr:
        raise HTTPException(404, "Ordonnance introuvable")
    if pr.status == "signed":
        raise HTTPException(400, "Ordonnance signée : modification refusée")
    adm = session.get(Admission, pr.admission_id)
    p = session.get(Patient, adm.patient_id) if adm else None
    warnings = []
    if body.notes is not None:
        pr.notes = body.notes
    if body.lines is not None:
        warnings = _apply_lines(session, pr, p, body.lines)
    audit(session, user, "update", "prescription", prescription_id)
    session.commit()
    d = _out(session, pr)
    d["warnings"] = warnings
    return d


@router.post("/{prescription_id}/sign")
def sign_prescription(prescription_id: int, force: bool = False, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_write_medical_docs)):
    pr = session.get(Prescription, prescription_id)
    if not pr:
        raise HTTPException(404, "Ordonnance introuvable")
    d = _out(session, pr)
    if not d["lines"]:
        raise HTTPException(400, "Ordonnance sans ligne")
    if d["has_allergy_warning"] and not force:
        raise HTTPException(409, "Alerte allergie : confirmer explicitement la signature (force=true)")
    pr.status = "signed"
    pr.signed_at = datetime.now(timezone.utc)
    pr.prescriber = user.name or user.username
    audit(session, user, "sign", "prescription", prescription_id, {"forced_allergy": d["has_allergy_warning"]})
    session.commit()
    return _out(session, pr)


@router.delete("/{prescription_id}", status_code=204)
def delete_prescription(prescription_id: int, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_write_medical_docs)):
    pr = session.get(Prescription, prescription_id)
    if not pr:
        raise HTTPException(404, "Ordonnance introuvable")
    if pr.status == "signed":
        raise HTTPException(400, "Ordonnance signée : suppression refusée")
    for ln in session.exec(select(PrescriptionLine).where(PrescriptionLine.prescription_id == pr.id)).all():
        session.delete(ln)
    session.delete(pr)
    audit(session, user, "delete", "prescription", prescription_id)
    session.commit()
    return None

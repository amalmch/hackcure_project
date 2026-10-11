"""Pharmacie : médicaments (stock, seuil, péremption), traitements en cours, alertes."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import auth as authlib
from ..audit import audit
from ..db import get_session
from ..models import Admission, Medication, Patient, Treatment

router = APIRouter(prefix="/api/pharmacy", tags=["pharmacy"])


class MedicationIn(BaseModel):
    dci: str
    brand: str = ""
    form: str = "comprimé"
    dosage: str = ""
    unit: str = "boîte"
    stock: int = 0
    threshold: int = 5
    expiry: Optional[date] = None
    allergen_tags: str = ""


class MedicationPatch(BaseModel):
    dci: Optional[str] = None
    brand: Optional[str] = None
    form: Optional[str] = None
    dosage: Optional[str] = None
    unit: Optional[str] = None
    stock: Optional[int] = None
    threshold: Optional[int] = None
    expiry: Optional[date] = None
    allergen_tags: Optional[str] = None


class TreatmentIn(BaseModel):
    admission_id: int
    medication_id: int
    posology: str
    route: str = "PO"
    prescriber: str = ""


def med_out(m: Medication) -> dict:
    return {"id": m.id, "dci": m.dci, "brand": m.brand, "form": m.form, "dosage": m.dosage, "unit": m.unit, "stock": m.stock, "threshold": m.threshold, "expiry": m.expiry,
            "allergen_tags": m.allergen_tags, "low_stock": m.low_stock, "expiring": m.expiring_within(60), "expired": bool(m.expiry and m.expiry < date.today())}


def allergy_conflicts(med: Medication, allergy_list: list[str]) -> list[str]:
    """Allergies du patient qui correspondent au médicament (DCI, marque ou tags d'allergènes)."""
    tags = [t.strip().lower() for t in med.allergen_tags.split(",") if t.strip()] + [med.dci.lower(), med.brand.lower()]
    hits = []
    for a in allergy_list:
        if any(a in t or t in a for t in tags if t):
            hits.append(a)
    return hits


@router.get("/medications")
def list_medications(q: Optional[str] = None, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_pharmacy"))):
    rows = session.exec(select(Medication).order_by(Medication.dci)).all()
    out = [med_out(m) for m in rows]
    if q:
        ql = q.lower()
        out = [o for o in out if ql in f"{o['dci']} {o['brand']} {o['form']}".lower()]
    return out


@router.get("/alerts")
def alerts(days: int = 60, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_pharmacy"))):
    rows = session.exec(select(Medication)).all()
    return {"days": days, "low_stock": [med_out(m) for m in rows if m.low_stock], "expiring": [med_out(m) for m in rows if m.expiring_within(days)]}


@router.post("/medications", status_code=201)
def create_medication(body: MedicationIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_edit_pharmacy)):
    m = Medication(**body.model_dump())
    session.add(m)
    session.flush()
    audit(session, user, "create", "medication", m.id, {"dci": m.dci})
    session.commit()
    session.refresh(m)
    return med_out(m)


@router.patch("/medications/{med_id}")
def patch_medication(med_id: int, body: MedicationPatch, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_edit_pharmacy)):
    m = session.get(Medication, med_id)
    if not m:
        raise HTTPException(404, "Médicament introuvable")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(m, k, v)
    audit(session, user, "update", "medication", med_id, body.model_dump(exclude_none=True))
    session.commit()
    session.refresh(m)
    return med_out(m)


@router.delete("/medications/{med_id}", status_code=204)
def delete_medication(med_id: int, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_edit_pharmacy)):
    m = session.get(Medication, med_id)
    if not m:
        raise HTTPException(404, "Médicament introuvable")
    if session.exec(select(Treatment).where(Treatment.medication_id == med_id)).first():
        raise HTTPException(400, "Médicament utilisé par un traitement : suppression refusée")
    session.delete(m)
    audit(session, user, "delete", "medication", med_id)
    session.commit()
    return None


@router.get("/treatments")
def list_treatments(admission_id: Optional[int] = None, active_only: bool = True, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_pharmacy"))):
    q = select(Treatment, Medication, Admission, Patient).join(Medication, Medication.id == Treatment.medication_id).join(Admission, Admission.id == Treatment.admission_id).join(Patient, Patient.id == Admission.patient_id)
    if admission_id:
        q = q.where(Treatment.admission_id == admission_id)
    if active_only:
        q = q.where(Treatment.end.is_(None), Admission.discharged_at.is_(None))
    out = []
    for t, m, a, p in session.exec(q.order_by(Admission.room_code)).all():
        out.append({"id": t.id, "admission_id": a.id, "room": a.room_code, "patient": p.full_name, "patient_id": p.patient_id, "allergies": p.allergies, "medication": med_out(m), "posology": t.posology, "route": t.route,
                    "start": t.start, "end": t.end, "prescriber": t.prescriber, "allergy_conflicts": allergy_conflicts(m, p.allergy_list)})
    return out


@router.post("/treatments", status_code=201)
def create_treatment(body: TreatmentIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_edit_pharmacy)):
    adm = session.get(Admission, body.admission_id)
    med = session.get(Medication, body.medication_id)
    if not adm or not med:
        raise HTTPException(404, "Admission ou médicament introuvable")
    p = session.get(Patient, adm.patient_id)
    conflicts = allergy_conflicts(med, p.allergy_list) if p else []
    t = Treatment(admission_id=adm.id, medication_id=med.id, posology=body.posology, route=body.route, prescriber=body.prescriber or user.name or user.username)
    session.add(t)
    session.flush()
    audit(session, user, "create", "treatment", t.id, {"medication": med.dci, "admission": adm.id, "allergy_conflicts": conflicts})
    session.commit()
    return {"id": t.id, "allergy_conflicts": conflicts, "warning": (f"ALLERGIE : {', '.join(conflicts)}" if conflicts else None)}


@router.delete("/treatments/{treatment_id}", status_code=204)
def stop_treatment(treatment_id: int, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_edit_pharmacy)):
    t = session.get(Treatment, treatment_id)
    if not t:
        raise HTTPException(404, "Traitement introuvable")
    t.end = datetime.now(timezone.utc)
    audit(session, user, "stop", "treatment", treatment_id)
    session.commit()
    return None

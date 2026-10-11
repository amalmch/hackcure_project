"""
API « soins » de la V2 (étape 4) :
- /api/diagnostics      hypothèses diagnostiques live + fil de communication médecin ↔ infirmier ;
- /api/treatment-orders ordonnance de traitement hospitalière (allergies, interactions, signature → plan) ;
- /api/care-plan        plan d'administration : à venir, à faire maintenant, en retard, administré ;
- /api/interventions    comptes rendus d'intervention (brouillon IA → validation et signature).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import auth as authlib, care
from ..agents.care import message_out
from ..audit import audit
from ..clinical.diagnostics import interactions
from ..db import get_session
from ..models import (CareMessage, DiagnosticHypothesis, MedicalRecordEntry, MedicationDose, Medication, Patient, Treatment, TreatmentOrder, TreatmentOrderLine)
from ..notify import notify
from ..ws import manager
from .pharmacy import allergy_conflicts

router = APIRouter(tags=["care"])
MENTION_ROLES = {"infirmier": "nurse", "infirmiere": "nurse", "medecin": "general_doctor", "medecin_garde": "duty_doctor", "garde": "duty_doctor", "psychiatre": "psychiatrist", "pharmacien": "pharmacist"}


def _patient(session: Session, patient_id: str) -> Patient:
    p = session.exec(select(Patient).where(Patient.patient_id == patient_id)).first()
    if not p:
        raise HTTPException(404, "Patient introuvable")
    return p


# ─── Diagnostics live ────────────────────────────────────────────────────────
class DecisionIn(BaseModel):
    status: str  # confirmed | rejected | active
    note: str = ""


class MessageIn(BaseModel):
    body: str


@router.get("/api/diagnostics/{patient_id}")
def diagnostics(patient_id: str, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_diagnostics"))):
    p = _patient(session, patient_id)
    adm = care.active_admission(session, p)
    q = select(DiagnosticHypothesis).where(DiagnosticHypothesis.patient_pk == p.id, DiagnosticHypothesis.status != "inactive")
    if adm:
        q = q.where(DiagnosticHypothesis.admission_id == adm.id)
    hyps = session.exec(q.order_by(DiagnosticHypothesis.score.desc())).all()
    msgs = session.exec(select(CareMessage).where(CareMessage.patient_pk == p.id).order_by(CareMessage.created_at.desc()).limit(60)).all()
    ctx = care.clinical_context(session, adm.room_code) if adm else None
    return {"patient_id": patient_id, "name": p.full_name, "room": adm.room_code if adm else None, "hypotheses": [care.hypothesis_out(h) for h in hyps], "messages": [message_out(m) for m in reversed(msgs)],
            "scores": {"news2": ctx["news2"], "qsofa": ctx["qsofa"]} if ctx else {}, "vitals": ctx["vitals"] if ctx else {},
            "disclaimer": "Hypothèses générées par des règles, à confirmer par le médecin. Aide à la décision — validation médicale requise."}


@router.post("/api/diagnostics/hypotheses/{hid}/decision")
async def decide(hid: int, body: DecisionIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("decide_diagnostics"))):
    h = session.get(DiagnosticHypothesis, hid)
    if not h:
        raise HTTPException(404, "Hypothèse introuvable")
    if body.status not in ("confirmed", "rejected", "active"):
        raise HTTPException(400, "Statut : confirmed | rejected | active")
    h.status, h.note, h.decided_by, h.decided_at, h.updated_at = body.status, body.note[:500], user.username, datetime.now(timezone.utc), datetime.now(timezone.utc)
    p = session.get(Patient, h.patient_pk)
    verb = {"confirmed": "confirme", "rejected": "rejette", "active": "rouvre"}[body.status]
    msg = CareMessage(patient_pk=h.patient_pk, room_code=h.room_code, author=user.username, author_name=user.name, role=user.role, kind="decision", hypothesis_id=h.id,
                      body=f"{verb} l'hypothèse « {h.label} »" + (f" — {body.note}" if body.note else ""))
    session.add(msg)
    audit(session, user, "decide", "diagnostic_hypothesis", hid, {"status": body.status})
    session.commit()
    session.refresh(h)
    session.refresh(msg)
    out, mout, pid, room, label = care.hypothesis_out(h), message_out(msg), p.patient_id if p else None, h.room_code, h.label
    await manager.broadcast({"type": "diagnostics", "event": "decision", "room": room, "patient_id": pid, "hypothesis": out})
    await manager.broadcast({"type": "care_message", "patient_id": pid, "message": mout})
    await notify("info", f"Diagnostic {'confirmé' if body.status == 'confirmed' else 'rejeté' if body.status == 'rejected' else 'rouvert'} — chambre {room}", f"{user.name or user.username} {mout['body']}", room=room, target_role="nurse", telegram=False)
    return out


@router.post("/api/diagnostics/{patient_id}/messages", status_code=201)
async def post_message(patient_id: str, body: MessageIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("post_care_message"))):
    p = _patient(session, patient_id)
    text = body.body.strip()[:2000]
    if not text:
        raise HTTPException(400, "Message vide")
    adm = care.active_admission(session, p)
    roles = sorted({MENTION_ROLES[m.lower()] for m in re.findall(r"@([A-Za-zÀ-ÿ_]+)", text) if m.lower() in MENTION_ROLES})
    msg = CareMessage(patient_pk=p.id, room_code=adm.room_code if adm else "", author=user.username, author_name=user.name, role=user.role, body=text, mentions=",".join(roles))
    session.add(msg)
    audit(session, user, "create", "care_message", patient_id, {"mentions": roles})
    session.commit()
    session.refresh(msg)
    out, room, name = message_out(msg), msg.room_code, p.full_name
    await manager.broadcast({"type": "care_message", "patient_id": patient_id, "message": out})
    for role in roles:  # mention @rôle ⇒ notification
        await notify("info", f"Message de {user.name or user.username} — {name}", text[:300], room=room or None, target_role=role, telegram=False)
    return out


# ─── Ordonnance de traitement hospitalière ───────────────────────────────────
class OrderLineIn(BaseModel):
    medication_id: int
    dose: str = ""
    route: str = "PO"
    times: list[str] = []
    duration_days: int = 3
    prn: bool = False
    condition_metric: str = ""
    condition_op: str = ">"
    condition_value: Optional[float] = None
    min_interval_h: float = 6.0


class OrderIn(BaseModel):
    patient_id: str
    indication: str = ""
    lines: list[OrderLineIn] = []


class SignIn(BaseModel):
    force: bool = False  # signer malgré une alerte d'allergie (tracé)
    first_dose_in_s: Optional[float] = None  # démo : première prise dans N secondes


def _check(session: Session, p: Patient, med: Medication, adm_id: Optional[int], others: list[str]) -> tuple[str, str]:
    conflicts = allergy_conflicts(med, p.allergy_list)
    current = list(others)
    if adm_id:
        current += [m.dci for _, m in session.exec(select(Treatment, Medication).join(Medication, Medication.id == Treatment.medication_id).where(Treatment.admission_id == adm_id, Treatment.end.is_(None))).all()]
    inter = interactions(med.dci, [c for c in current if c.lower() != med.dci.lower()])
    return (f"ALLERGIE : patient allergique à {', '.join(conflicts)}" if conflicts else ""), " ".join(inter)


@router.post("/api/treatment-orders/check")
def check_line(body: OrderIn, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_treatment_orders"))):
    """Vérification d'allergie et d'interactions avant d'ajouter une ligne (aucune écriture)."""
    p = _patient(session, body.patient_id)
    adm = care.active_admission(session, p)
    out = []
    meds = [session.get(Medication, ln.medication_id) for ln in body.lines]
    for i, m in enumerate(meds):
        if not m:
            raise HTTPException(404, "Médicament introuvable")
        a, x = _check(session, p, m, adm.id if adm else None, [o.dci for j, o in enumerate(meds) if o and j != i])
        out.append({"medication_id": m.id, "dci": m.dci, "allergy_alert": a, "interaction_alert": x, "stock": m.stock})
    return out


@router.get("/api/treatment-orders")
def list_orders(patient_id: Optional[str] = None, status: Optional[str] = None, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_treatment_orders"))):
    q = select(TreatmentOrder).order_by(TreatmentOrder.id.desc())
    if patient_id:
        q = q.where(TreatmentOrder.patient_pk == _patient(session, patient_id).id)
    if status:
        q = q.where(TreatmentOrder.status == status)
    return [care.order_out(session, o) for o in session.exec(q.limit(100)).all()]


@router.post("/api/treatment-orders", status_code=201)
def create_order(body: OrderIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("write_treatment_orders"))):
    p = _patient(session, body.patient_id)
    adm = care.active_admission(session, p)
    if not adm:
        raise HTTPException(409, "Patient non hospitalisé : pas d'ordonnance de traitement")
    if not body.lines:
        raise HTTPException(400, "Au moins une ligne")
    o = TreatmentOrder(admission_id=adm.id, patient_pk=p.id, room_code=adm.room_code, prescriber=user.username, prescriber_name=user.name, indication=body.indication[:300])
    session.add(o)
    session.flush()
    meds = [session.get(Medication, ln.medication_id) for ln in body.lines]
    for i, (ln, m) in enumerate(zip(body.lines, meds)):
        if not m:
            raise HTTPException(404, "Médicament introuvable")
        times = sorted({t.strip() for t in ln.times if re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", t.strip())})
        if not ln.prn and not times:
            raise HTTPException(400, f"{m.dci} : horaires requis (HH:MM) ou prise conditionnelle")
        a, x = _check(session, p, m, adm.id, [o2.dci for j, o2 in enumerate(meds) if o2 and j != i])
        session.add(TreatmentOrderLine(order_id=o.id, medication_id=m.id, dci=m.dci, dose=ln.dose[:80], route=ln.route, times=",".join(times), duration_days=max(1, min(ln.duration_days, 30)), prn=ln.prn,
                                       condition_metric=ln.condition_metric if ln.prn else "", condition_op=ln.condition_op, condition_value=ln.condition_value if ln.prn else None,
                                       min_interval_h=max(0.0, ln.min_interval_h), allergy_alert=a, interaction_alert=x))
    audit(session, user, "create", "treatment_order", o.id, {"patient": body.patient_id, "lines": len(body.lines)})
    session.commit()
    session.refresh(o)
    return care.order_out(session, o)


@router.post("/api/treatment-orders/{order_id}/sign")
async def sign_order(order_id: int, body: SignIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("write_treatment_orders"))):
    """Signature ⇒ l'ordonnance devient active et le plan d'administration horodaté est généré."""
    o = session.get(TreatmentOrder, order_id)
    if not o:
        raise HTTPException(404, "Ordonnance introuvable")
    if o.status != "draft":
        return care.order_out(session, o)
    lines = session.exec(select(TreatmentOrderLine).where(TreatmentOrderLine.order_id == o.id)).all()
    blocked = [ln for ln in lines if ln.allergy_alert]
    if blocked and not body.force:
        raise HTTPException(409, "Alerte allergie : " + "; ".join(f"{ln.dci} — {ln.allergy_alert}" for ln in blocked) + ". Retirer la ligne, ou signer avec confirmation explicite.")
    o.status, o.signed_at = "active", datetime.now(timezone.utc)
    n = care.build_plan(session, o, first_dose_in_s=body.first_dose_in_s)
    audit(session, user, "sign", "treatment_order", order_id, {"doses": n, "forced": bool(blocked)})
    session.commit()
    session.refresh(o)
    out = care.order_out(session, o)
    await manager.broadcast({"type": "care_plan", "event": "plan_created", "order_id": order_id, "room": o.room_code, "doses": n})
    await notify("info", f"Nouvelle ordonnance de traitement — chambre {out['room']}", f"{out['patient_name']} : {len(out['lines'])} ligne(s), {n} prise(s) planifiée(s) par {user.name or user.username}.", room=out["room"], target_role="nurse", telegram=False)
    return out


@router.post("/api/treatment-orders/{order_id}/stop")
async def stop_order(order_id: int, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("write_treatment_orders"))):
    o = session.get(TreatmentOrder, order_id)
    if not o:
        raise HTTPException(404, "Ordonnance introuvable")
    o.status, o.stopped_at = "stopped", datetime.now(timezone.utc)
    for d in session.exec(select(MedicationDose).where(MedicationDose.order_id == o.id, MedicationDose.status == "scheduled")).all():
        d.status, d.reason = "cancelled", f"ordonnance arrêtée par {user.username}"
    audit(session, user, "stop", "treatment_order", order_id)
    session.commit()
    session.refresh(o)
    return care.order_out(session, o)


# ─── Plan de soins ───────────────────────────────────────────────────────────
class GiveIn(BaseModel):
    note: str = ""


class SkipIn(BaseModel):
    reason: str


@router.get("/api/care-plan")
def care_plan(room: Optional[str] = None, patient_id: Optional[str] = None, hours: int = 24, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_care_plan"))):
    now = datetime.now(timezone.utc)
    q = select(MedicationDose).where(MedicationDose.due_at >= now - timedelta(hours=24), MedicationDose.due_at <= now + timedelta(hours=max(1, min(hours, 72))), MedicationDose.status != "cancelled")
    if room:
        q = q.where(MedicationDose.room_code == room)
    if patient_id:
        q = q.where(MedicationDose.patient_pk == _patient(session, patient_id).id)
    rows = [care.dose_out(session, d, now) for d in session.exec(q.order_by(MedicationDose.due_at)).all()]
    groups = {k: [r for r in rows if r["state"] == k] for k in ("late", "due", "upcoming", "given", "not_given")}
    return {"now": now.isoformat(), "counts": {k: len(v) for k, v in groups.items()}, **groups}


def _dose(session: Session, dose_id: int) -> MedicationDose:
    d = session.get(MedicationDose, dose_id)
    if not d:
        raise HTTPException(404, "Prise introuvable")
    if d.status != "scheduled":
        raise HTTPException(409, f"Prise déjà {care.STATE_LABELS.get(care.dose_state(d), d.status)}")
    return d


@router.post("/api/care-plan/doses/{dose_id}/give")
async def give_dose(dose_id: int, body: GiveIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("administer_medication"))):
    d = _dose(session, dose_id)
    care.give(session, d, user.username, body.note)
    med = session.get(Medication, d.medication_id)
    audit(session, user, "administer", "medication_dose", dose_id, {"label": d.label, "stock_after": med.stock if med else None})
    session.commit()
    session.refresh(d)
    out = care.dose_out(session, d)
    await manager.broadcast({"type": "care_plan", "event": "given", "dose": out})
    return {**out, "stock_after": med.stock if med else None}


@router.post("/api/care-plan/doses/{dose_id}/skip")
async def skip_dose(dose_id: int, body: SkipIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("administer_medication"))):
    if not body.reason.strip():
        raise HTTPException(400, "Motif requis")
    d = _dose(session, dose_id)
    d.status, d.reason, d.given_by, d.given_at = "not_given", body.reason.strip()[:300], user.username, datetime.now(timezone.utc)
    audit(session, user, "skip", "medication_dose", dose_id, {"reason": d.reason})
    session.commit()
    session.refresh(d)
    out = care.dose_out(session, d)
    await manager.broadcast({"type": "care_plan", "event": "not_given", "dose": out})
    await notify("warning", f"Prise non administrée — chambre {out['room']}", f"{out['patient_name']} : {out['label']} — motif : {d.reason} ({user.name or user.username}).", room=out["room"], target_role="duty_doctor", telegram=False)
    return out


# ─── Comptes rendus d'intervention ───────────────────────────────────────────
class ReportSignIn(BaseModel):
    content: Optional[str] = None


def _report_out(session: Session, e: MedicalRecordEntry) -> dict[str, Any]:
    p = session.get(Patient, e.patient_pk)
    data = json.loads(e.data_json or "{}")
    return {"id": e.id, "patient_id": p.patient_id if p else None, "patient_name": p.full_name if p else "", "room": data.get("room"), "risk_id": data.get("risk_id"), "title": e.title, "summary": e.summary,
            "content": e.content, "status": e.status, "author": e.author, "date": care.aware(e.date).isoformat()}


@router.get("/api/interventions")
def interventions(status: Optional[str] = None, patient_id: Optional[str] = None, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_medical_record"))):
    q = select(MedicalRecordEntry).where(MedicalRecordEntry.type == "intervention").order_by(MedicalRecordEntry.date.desc())
    if status:
        q = q.where(MedicalRecordEntry.status == status)
    if patient_id:
        q = q.where(MedicalRecordEntry.patient_pk == _patient(session, patient_id).id)
    return [_report_out(session, e) for e in session.exec(q.limit(60)).all()]


@router.post("/api/interventions/{entry_id}/sign")
async def sign_intervention(entry_id: int, body: ReportSignIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("administer_medication"))):
    """Le soignant relit (et corrige) le brouillon, puis le signe : le compte rendu est rangé, signé, dans le dossier médical."""
    e = session.get(MedicalRecordEntry, entry_id)
    if not e or e.type != "intervention":
        raise HTTPException(404, "Compte rendu introuvable")
    if e.status == "signed":
        return _report_out(session, e)
    if body.content is not None:
        e.content = body.content
    if not e.content.strip():
        raise HTTPException(409, "Le brouillon n'est pas encore rédigé")
    e.status, e.author = "signed", f"{user.name or user.username} (rédaction assistée par IA)"
    audit(session, user, "sign", "intervention_report", entry_id)
    session.commit()
    session.refresh(e)
    out = _report_out(session, e)
    await manager.broadcast({"type": "intervention_report", "event": "signed", "report": {k: out[k] for k in ("id", "patient_id", "title", "status")}})
    return out

"""
Logique « soins » de la V2 (étape 4) partagée par l'API et les agents :
ordonnance de traitement hospitalière → plan d'administration horodaté, état d'une prise, administration
(stock de la pharmacie décrémenté), contexte des hypothèses diagnostiques.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from .config import settings
from .ingest import handler
from .models import (Admission, DiagnosticHypothesis, LabResult, MedicationDose, Medication, Patient, Risk, TreatmentOrder, TreatmentOrderLine)

HORIZON_H = 72  # le plan est généré pour les 72 prochaines heures (renouvelable)
CONDITION_LABELS = {"tempC": "température", "pain": "douleur (EVA)", "sys": "PAS", "spo2": "SpO2", "glucose": "glycémie", "hr": "FC"}
CONDITION_UNITS = {"tempC": "°C", "pain": "/10", "sys": "mmHg", "spo2": "%", "glucose": "g/L", "hr": "/min"}


def aware(d: Optional[datetime]) -> Optional[datetime]:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def condition_text(line: TreatmentOrderLine) -> str:
    if not line.prn or not line.condition_metric or line.condition_value is None:
        return "si besoin" if line.prn else ""
    return f"si {CONDITION_LABELS.get(line.condition_metric, line.condition_metric)} {line.condition_op} {line.condition_value:g} {CONDITION_UNITS.get(line.condition_metric, '')}".strip()


def line_out(session: Session, ln: TreatmentOrderLine) -> dict[str, Any]:
    m = session.get(Medication, ln.medication_id)
    return {"id": ln.id, "medication_id": ln.medication_id, "dci": ln.dci, "brand": m.brand if m else "", "stock": m.stock if m else None, "dose": ln.dose, "route": ln.route,
            "times": [t for t in ln.times.split(",") if t], "duration_days": ln.duration_days, "prn": ln.prn, "condition": condition_text(ln), "condition_metric": ln.condition_metric,
            "condition_op": ln.condition_op, "condition_value": ln.condition_value, "min_interval_h": ln.min_interval_h, "allergy_alert": ln.allergy_alert, "interaction_alert": ln.interaction_alert}


def order_out(session: Session, o: TreatmentOrder) -> dict[str, Any]:
    p = session.get(Patient, o.patient_pk)
    lines = session.exec(select(TreatmentOrderLine).where(TreatmentOrderLine.order_id == o.id).order_by(TreatmentOrderLine.id)).all()
    doses = session.exec(select(MedicationDose).where(MedicationDose.order_id == o.id)).all()
    iso = lambda d: aware(d).isoformat() if d else None  # noqa: E731
    return {"id": o.id, "admission_id": o.admission_id, "patient_id": p.patient_id if p else None, "patient_name": p.full_name if p else "", "allergies": p.allergies if p else "", "room": o.room_code,
            "prescriber": o.prescriber, "prescriber_name": o.prescriber_name, "indication": o.indication, "status": o.status, "created_at": iso(o.created_at), "signed_at": iso(o.signed_at), "stopped_at": iso(o.stopped_at),
            "lines": [line_out(session, ln) for ln in lines], "doses": {"total": len(doses), "given": sum(1 for d in doses if d.status == "given"), "scheduled": sum(1 for d in doses if d.status == "scheduled")},
            "has_alert": any(ln.allergy_alert for ln in lines)}


def build_plan(session: Session, order: TreatmentOrder, start: Optional[datetime] = None, first_dose_in_s: Optional[float] = None) -> int:
    """Transforme l'ordonnance en plan d'administration horodaté (prise par prise). Renvoie le nombre de prises créées.
    `first_dose_in_s` (démo) : la première prise de chaque ligne programmée est avancée à maintenant + N secondes."""
    now = aware(start) or datetime.now(timezone.utc)
    local_now = now.astimezone()
    created = 0
    for ln in session.exec(select(TreatmentOrderLine).where(TreatmentOrderLine.order_id == order.id)).all():
        if ln.prn or not ln.times:
            continue  # prise conditionnelle : créée par le MedicationAgent quand la condition est remplie
        end = now + timedelta(hours=min(HORIZON_H, ln.duration_days * 24))
        slots: list[datetime] = []
        for day in range(0, ln.duration_days + 1):
            for hm in ln.times.split(","):
                try:
                    h, m = (int(x) for x in hm.strip().split(":"))
                except ValueError:
                    continue
                due = (local_now + timedelta(days=day)).replace(hour=h, minute=m, second=0, microsecond=0).astimezone(timezone.utc)
                if now <= due <= end:
                    slots.append(due)
        slots.sort()
        if first_dose_in_s is not None:
            first = now + timedelta(seconds=first_dose_in_s)
            slots = [first] + [s for s in slots if s > first + timedelta(hours=1)]
        for due in slots:
            session.add(MedicationDose(line_id=ln.id, order_id=order.id, admission_id=order.admission_id, patient_pk=order.patient_pk, room_code=order.room_code, medication_id=ln.medication_id,
                                       label=f"{ln.dci} {ln.dose} {ln.route}".strip(), due_at=due))
            created += 1
    return created


def dose_state(d: MedicationDose, now: Optional[datetime] = None) -> str:
    """à venir | à faire maintenant | en retard | administré | non administré"""
    if d.status == "given":
        return "given"
    if d.status in ("not_given", "cancelled"):
        return "not_given"
    now = now or datetime.now(timezone.utc)
    delta = (now - aware(d.due_at)).total_seconds()
    if delta > settings.med_relaunch_s:
        return "late"
    if delta >= -settings.med_due_window_s:
        return "due"
    return "upcoming"


STATE_LABELS = {"upcoming": "à venir", "due": "à faire maintenant", "late": "en retard", "given": "administré", "not_given": "non administré"}


def dose_out(session: Session, d: MedicationDose, now: Optional[datetime] = None) -> dict[str, Any]:
    p = session.get(Patient, d.patient_pk)
    ln = session.get(TreatmentOrderLine, d.line_id)
    st = dose_state(d, now)
    iso = lambda x: aware(x).isoformat() if x else None  # noqa: E731
    return {"id": d.id, "order_id": d.order_id, "room": d.room_code, "patient_id": p.patient_id if p else None, "patient_name": p.full_name if p else "", "allergies": p.allergies if p else "",
            "label": d.label, "due_at": iso(d.due_at), "status": d.status, "state": st, "state_label": STATE_LABELS[st], "conditional": d.conditional, "condition": condition_text(ln) if ln else "",
            "given_at": iso(d.given_at), "given_by": d.given_by, "note": d.note, "reason": d.reason, "relaunched_at": iso(d.relaunched_at), "escalated_at": iso(d.escalated_at),
            "allergy_alert": ln.allergy_alert if ln else "", "minutes_late": max(0, int((aware(now or datetime.now(timezone.utc)) - aware(d.due_at)).total_seconds() // 60)) if st in ("due", "late") else 0}


def give(session: Session, dose: MedicationDose, by: str, note: str = "") -> None:
    """Enregistre l'administration et décrémente le stock de la pharmacie."""
    dose.status, dose.given_at, dose.given_by, dose.note = "given", datetime.now(timezone.utc), by, (note or "")[:300]
    med = session.get(Medication, dose.medication_id)
    if med is not None and med.stock > 0:
        med.stock -= 1


def overdue_in_room(session: Session, room: str) -> list[MedicationDose]:
    limit = datetime.now(timezone.utc) - timedelta(seconds=settings.med_relaunch_s)
    return session.exec(select(MedicationDose).where(MedicationDose.room_code == room, MedicationDose.status == "scheduled", MedicationDose.due_at <= limit)).all()


def missed_doses(session: Session, patient_pk: int, hours: int = 48) -> list[MedicationDose]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return session.exec(select(MedicationDose).where(MedicationDose.patient_pk == patient_pk, MedicationDose.due_at >= since, MedicationDose.status.in_(["not_given"]))).all() + \
        [d for d in session.exec(select(MedicationDose).where(MedicationDose.patient_pk == patient_pk, MedicationDose.due_at >= since, MedicationDose.status == "scheduled")).all() if dose_state(d) == "late"]


# ─── contexte clinique d'un patient hospitalisé (diagnostics, prédictions) ────
def latest_labs(session: Session, patient_pk: int, days: int = 14) -> dict[str, dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    out: dict[str, dict[str, Any]] = {}
    for r in session.exec(select(LabResult).where(LabResult.patient_pk == patient_pk, LabResult.date >= since, LabResult.value.is_not(None)).order_by(LabResult.date.desc())).all():
        out.setdefault(r.code, {"value": r.value, "unit": r.unit, "date": aware(r.date).date().isoformat(), "abnormal": r.abnormal, "label": r.label})
    return out


def clinical_context(session: Session, room: str) -> Optional[dict[str, Any]]:
    """Tout ce que les règles de diagnostic et de prédiction utilisent pour le patient d'une chambre."""
    from .agents.context import current_news2, room_vitals
    from .clinical.fever import qsofa
    from .risks import patient_context

    ctx = patient_context(session, room)
    pat = ctx.get("patient")
    if not pat:
        return None
    p = session.exec(select(Patient).where(Patient.patient_id == pat["patient_id"])).first()
    v = room_vitals(room)
    rs = handler.room_state(room)
    n2 = current_news2(room)
    risks = [r.type for r in session.exec(select(Risk).where(Risk.room_code == room, Risk.status.in_(["open", "in_progress", "escalated"]))).all()]
    return {"room": room, "patient_pk": p.id if p else None, "patient_id": pat["patient_id"], "name": pat["full_name"], "age": pat["age"], "admission_id": ctx.get("admission_id"),
            "admission_reason": (ctx.get("admission") or {}).get("reason"), "history": pat.get("history") or "", "allergies": pat.get("allergies") or "", "treatments": ctx.get("treatments") or "",
            "vitals": v, "news2": n2.score if n2 else None, "qsofa": qsofa(v.get("rr"), v.get("sys"))["score"], "posture": rs.get("posture"), "activity": rs.get("activity"),
            "expression": rs.get("expression"), "skin_temp": rs.get("skinTempC"), "open_risks": risks, "labs": latest_labs(session, p.id) if p else {}}


def hypothesis_out(h: DiagnosticHypothesis) -> dict[str, Any]:
    iso = lambda d: aware(d).isoformat() if d else None  # noqa: E731
    return {"id": h.id, "code": h.code, "label": h.label, "score": h.score, "probability": h.probability, "pros": json.loads(h.pros_json or "[]"), "cons": json.loads(h.cons_json or "[]"),
            "exams": json.loads(h.exams_json or "[]"), "status": h.status, "note": h.note, "decided_by": h.decided_by, "decided_at": iso(h.decided_at), "updated_at": iso(h.updated_at), "room": h.room_code}


def active_admission(session: Session, patient: Patient) -> Optional[Admission]:
    return session.exec(select(Admission).where(Admission.patient_id == patient.id, Admission.discharged_at.is_(None))).first()

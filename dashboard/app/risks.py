"""Helpers partagés (agents + API) : sérialisation des risques, niveau de risque par chambre, contexte patient."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from .agents.plans import TYPE_LABELS
from .ingest import handler
from .models import ActionPlan, ActionStep, Admission, Medication, Patient, Risk, StaffVisit, Treatment

SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
OPEN_STATUSES = ("open", "in_progress", "escalated")


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d else None


def plan_dict(session: Session, plan: ActionPlan) -> dict[str, Any]:
    steps = session.exec(select(ActionStep).where(ActionStep.plan_id == plan.id).order_by(ActionStep.order)).all()
    return {
        "id": plan.id, "summary": plan.summary, "created_by": plan.created_by, "llm_provider": plan.llm_provider, "created_at": _iso(plan.created_at),
        "steps": [{"id": st.id, "order": st.order, "text": st.text, "suggested_by_ai": st.suggested_by_ai, "done": st.done, "done_by": st.done_by, "done_at": _iso(st.done_at)} for st in steps],
        "done_count": sum(1 for st in steps if st.done), "total": len(steps),
    }


def risk_dict(session: Session, r: Risk, with_plan: bool = True) -> dict[str, Any]:
    d = {
        "id": r.id, "room": r.room_code, "admission_id": r.admission_id, "type": r.type, "type_label": TYPE_LABELS.get(r.type, r.type), "title": r.title,
        "severity": r.severity, "status": r.status, "source_agent": r.source_agent, "explanation": r.explanation, "news2": r.news2,
        "detected_at": _iso(r.detected_at), "acknowledged_at": _iso(r.acknowledged_at), "resolved_at": _iso(r.resolved_at), "verified_at": _iso(r.verified_at),
        "escalated_at": _iso(r.escalated_at), "resolved_by": r.resolved_by, "notes": r.notes, "handled_by": r.handled_by,
        "patient_id": None, "patient_name": None,
    }
    if r.admission_id:
        adm = session.get(Admission, r.admission_id)
        if adm:
            p = session.get(Patient, adm.patient_id)
            if p:
                d["patient_id"], d["patient_name"] = p.patient_id, p.full_name
    if with_plan:
        plan = session.exec(select(ActionPlan).where(ActionPlan.risk_id == r.id).order_by(ActionPlan.id.desc())).first()
        d["plan"] = plan_dict(session, plan) if plan else None
        visits = session.exec(select(StaffVisit).where(StaffVisit.risk_id == r.id).order_by(StaffVisit.started_at)).all()
        d["visits"] = [{"id": v.id, "started_at": _iso(v.started_at), "ended_at": _iso(v.ended_at), "persons": v.persons, "staff_name": v.staff_name} for v in visits]
    return d


def room_risk_level(session: Session, room: str) -> tuple[str, int]:
    rows = session.exec(select(Risk).where(Risk.room_code == room, Risk.status.in_(OPEN_STATUSES))).all()
    if not rows:
        return "none", 0
    top = max(rows, key=lambda r: SEVERITY_ORDER.get(r.severity, 0))
    return top.severity, len(rows)


def refresh_room_level(session: Session, room: str) -> None:
    level, n = room_risk_level(session, room)
    handler.set_risk_level(room, level, n)


def refresh_all_levels(session: Session) -> None:
    for room in handler.ROOMS:
        refresh_room_level(session, room)


def open_risks_in_room(session: Session, room: str) -> list[Risk]:
    return session.exec(select(Risk).where(Risk.room_code == room, Risk.status.in_(OPEN_STATUSES)).order_by(Risk.detected_at)).all()


def patient_context(session: Session, room: str) -> dict[str, Any]:
    """Profil patient + traitements + admission pour la chambre (pour les agents et le LLM)."""
    adm = session.exec(select(Admission).where(Admission.room_code == room, Admission.discharged_at.is_(None))).first()
    if not adm:
        return {"room": room, "admission_id": None, "patient": None, "treatments": ""}
    p = session.get(Patient, adm.patient_id)
    treatments = session.exec(select(Treatment, Medication).join(Medication, Medication.id == Treatment.medication_id).where(Treatment.admission_id == adm.id, Treatment.end.is_(None))).all()
    tr_txt = "; ".join(f"{m.dci} ({m.brand}) {t.posology} {t.route}" for t, m in treatments)
    return {
        "room": room, "admission_id": adm.id,
        "admission": {"id": adm.id, "admitted_at": _iso(adm.admitted_at), "reason": adm.reason, "referring_doctor": adm.referring_doctor, "room_code": adm.room_code},
        "patient": None if not p else {
            "patient_id": p.patient_id, "code": p.code, "display_name": p.display_name, "full_name": p.full_name, "age": p.age, "sex": p.sex,
            "allergies": p.allergies, "allergy_list": p.allergy_list, "blood_group": p.blood_group, "fall_risk": p.fall_risk, "history": p.history,
        },
        "treatments": tr_txt,
        "treatment_list": [{"dci": m.dci, "brand": m.brand, "posology": t.posology, "route": t.route, "allergen_tags": m.allergen_tags} for t, m in treatments],
    }


def wait_seconds(severity: str) -> int:
    """Délai d'acquittement avant escalade (critical 2 min, high 10, medium 30 ; raccourci en démo par ESCALATION_*_S)."""
    from .config import settings

    return int({"critical": settings.escalation_critical_s, "high": settings.escalation_high_s}.get(severity, settings.escalation_medium_s))


def n8n_payload(session: Session, risk: Risk) -> dict[str, Any]:
    """Événement complet envoyé à n8n : risque, patient (âge, allergies, traitements, risque de chute),
    dernières constantes, état vision, personnel en service, URL de la plateforme."""
    from .agents.context import current_news2
    from .config import settings
    from .models import Staff

    ctx = patient_context(session, risk.room_code)
    rs = handler.room_state(risk.room_code)
    n2 = current_news2(risk.room_code)
    staff = [{"name": s.name, "role": s.role, "room": s.current_room} for s in session.exec(select(Staff).where(Staff.on_duty.is_(True))).all()]
    return {
        "event": "risk-created",
        "ts": datetime.now(timezone.utc).isoformat(),
        "platform_url": settings.platform_url,
        "risk": risk_dict(session, risk, with_plan=False),
        "wait_seconds": wait_seconds(risk.severity),
        "llm_model": settings.llm_model,
        "telegram_chat_id": settings.telegram_chat_id,
        "patient": ctx.get("patient"),
        "admission": ctx.get("admission"),
        "treatments": ctx.get("treatment_list", []),
        "treatments_text": ctx.get("treatments", ""),
        "vitals": rs.get("vitals") or {},
        "news2": n2.to_dict() if n2 else None,
        "vision": {k: rs.get(k) for k in ("posture", "activity", "zone", "expression", "persons", "skinTempC", "confidence", "visionSource")},
        "env": rs.get("env"),
        "equipment": rs.get("equipment"),
        "staff_on_duty": staff,
        "nurse_present": bool(rs.get("staffPresent")),
    }


def recent_resolved_same(session: Session, room: str, rtype: str, minutes: int = 3) -> Optional[Risk]:
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return session.exec(select(Risk).where(Risk.room_code == room, Risk.type == rtype, Risk.status == "resolved", Risk.resolved_at >= since)).first()

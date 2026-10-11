"""
Psychologie (V2, étape 7) : état psychologique par patient, questionnaire d'admission sur tablette,
prescriptions psychothérapeutiques.

- psychiatre (et owner) : lecture + écriture (prescriptions, notes) ;
- médecins : lecture complète ;
- infirmiers : lecture seule de l'état du patient et des consignes (pas des réponses détaillées) ;
- page tablette `/patient/questionnaire/{token}` : publique, protégée par un jeton à usage unique.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import auth as authlib
from ..agents.psych import questionnaire_out, score_out
from ..audit import audit
from ..bus import bus
from ..clinical import psych as rules
from ..db import get_session
from ..models import Admission, Patient, PsychPrescription, PsychQuestionnaire, PsychScore
from ..notify import notify
from ..ws import manager

router = APIRouter(tags=["psych"])


def _patient(session: Session, patient_id: str) -> Patient:
    p = session.exec(select(Patient).where(Patient.patient_id == patient_id)).first()
    if not p:
        raise HTTPException(404, "Patient introuvable")
    return p


def prescription_out(x: PsychPrescription) -> dict[str, Any]:
    ts = x.created_at if x.created_at.tzinfo else x.created_at.replace(tzinfo=timezone.utc)
    return {"id": x.id, "type": x.type, "frequency": x.frequency, "goals": x.goals, "instructions": x.instructions, "author": x.author, "author_name": x.author_name, "active": x.active, "created_at": ts.isoformat()}


@router.get("/api/psych/patients")
def psych_patients(session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_psychology"))):
    out = []
    for adm in session.exec(select(Admission).where(Admission.discharged_at.is_(None)).order_by(Admission.room_code)).all():
        p = session.get(Patient, adm.patient_id)
        scores = session.exec(select(PsychScore).where(PsychScore.admission_id == adm.id).order_by(PsychScore.id.desc()).limit(8)).all()
        q = session.exec(select(PsychQuestionnaire).where(PsychQuestionnaire.admission_id == adm.id).order_by(PsychQuestionnaire.id.desc())).first()
        last = scores[0] if scores else None
        trend = (last.wellbeing - scores[-1].wellbeing) if len(scores) > 1 else 0
        detail = json.loads(last.detail_json) if last else {}
        out.append({"patient_id": p.patient_id, "name": p.full_name, "room": adm.room_code, "wellbeing": last.wellbeing if last else None, "level": last.level if last else None,
                    "trend": "hausse" if trend >= 4 else "baisse" if trend <= -4 else "stable", "q9_positive": bool(detail.get("q9_positive")),
                    "levels": {k: detail[k]["level"] for k in ("depression", "anxiety", "insomnia") if k in detail}, "questionnaire": q.status if q else "absent"})
    return out


@router.get("/api/psych/{patient_id}")
def psych_detail(patient_id: str, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("view_psychology"))):
    p = _patient(session, patient_id)
    adm = session.exec(select(Admission).where(Admission.patient_id == p.id, Admission.discharged_at.is_(None))).first()
    full = user.can("view_psych_answers")
    # le séjour en cours d'abord : un patient réadmis a un nouveau questionnaire et une nouvelle série de scores
    sq, qq = select(PsychScore).where(PsychScore.patient_pk == p.id), select(PsychQuestionnaire).where(PsychQuestionnaire.patient_pk == p.id)
    if adm:
        sq, qq = sq.where(PsychScore.admission_id == adm.id), qq.where(PsychQuestionnaire.admission_id == adm.id)
    scores = session.exec(sq.order_by(PsychScore.id.desc()).limit(120)).all()
    q = session.exec(qq.order_by(PsychQuestionnaire.id.desc())).first()
    rx = session.exec(select(PsychPrescription).where(PsychPrescription.patient_pk == p.id).order_by(PsychPrescription.id.desc())).all()
    latest = score_out(scores[0]) if scores else None
    if latest and not full:  # infirmier : état et consignes, sans le détail des réponses
        latest.pop("inputs", None)
    return {"patient_id": patient_id, "name": p.full_name, "room": adm.room_code if adm else None, "latest": latest, "history": [{"ts": score_out(s)["ts"], "wellbeing": s.wellbeing} for s in reversed(scores)],
            "questionnaire": questionnaire_out(q, with_answers=full) if q else None, "prescriptions": [prescription_out(x) for x in rx], "labels": rules.LABELS, "scope": "full" if full else "consignes",
            "items": {k: v["items"] for k, v in rules.QUESTIONNAIRES.items()} if full else None, "scale": rules.SCALE,
            "disclaimer": "Niveau de risque estimé à partir de questionnaires et d'observations : ce n'est jamais un diagnostic. Aide à la décision — validation médicale requise."}


class PrescriptionIn(BaseModel):
    type: str
    frequency: str = ""
    goals: str = ""
    instructions: str = ""


@router.post("/api/psych/{patient_id}/prescriptions", status_code=201)
async def add_prescription(patient_id: str, body: PrescriptionIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("write_psychology"))):
    p = _patient(session, patient_id)
    if not body.type.strip():
        raise HTTPException(400, "Type de suivi requis")
    adm = session.exec(select(Admission).where(Admission.patient_id == p.id, Admission.discharged_at.is_(None))).first()
    x = PsychPrescription(patient_pk=p.id, admission_id=adm.id if adm else None, type=body.type.strip()[:120], frequency=body.frequency[:120], goals=body.goals[:600], instructions=body.instructions[:800],
                          author=user.username, author_name=user.name)
    session.add(x)
    audit(session, user, "create", "psych_prescription", patient_id, {"type": x.type})
    session.commit()
    session.refresh(x)
    out, room, name = prescription_out(x), adm.room_code if adm else None, p.full_name
    await manager.broadcast({"type": "psych", "event": "prescription", "patient_id": patient_id, "prescription": out})
    await notify("info", f"Prescription psychothérapeutique — {name}", f"{x.type} ({x.frequency}). Consignes à l'équipe : {x.instructions or '—'}", room=room, target_role="nurse", telegram=False)
    return out


@router.post("/api/psych/prescriptions/{rx_id}/stop")
def stop_prescription(rx_id: int, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("write_psychology"))):
    x = session.get(PsychPrescription, rx_id)
    if not x:
        raise HTTPException(404, "Prescription introuvable")
    x.active = False
    audit(session, user, "stop", "psych_prescription", rx_id)
    session.commit()
    session.refresh(x)
    return prescription_out(x)


# ─── page tablette (publique, par jeton) ─────────────────────────────────────
def _by_token(session: Session, token: str) -> PsychQuestionnaire:
    q = session.exec(select(PsychQuestionnaire).where(PsychQuestionnaire.token == token)).first()
    if not q:
        raise HTTPException(404, "Questionnaire introuvable")
    return q


@router.get("/api/psych/questionnaire/{token}")
def questionnaire_form(token: str, session: Session = Depends(get_session)):
    q = _by_token(session, token)
    p = session.get(Patient, q.patient_pk)
    return {"status": q.status, "first_name": p.first_name if p else "", "scale": rules.SCALE,
            "sections": [{"key": k, "title": v["title"], "intro": v["intro"], "items": v["items"]} for k, v in rules.QUESTIONNAIRES.items()]}


class AnswersIn(BaseModel):
    phq9: list[int]
    gad7: list[int]
    sleep: list[int]


@router.post("/api/psych/questionnaire/{token}")
async def questionnaire_submit(token: str, body: AnswersIn, session: Session = Depends(get_session)):
    q = _by_token(session, token)
    if q.status == "completed":
        raise HTTPException(409, "Ce questionnaire a déjà été rempli")
    try:
        scores = rules.score_answers(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    q.answers_json, q.scores_json = json.dumps(body.model_dump()), json.dumps(scores, ensure_ascii=False)
    q.status, q.completed_at, q.q9_positive = "completed", datetime.now(timezone.utc), scores["q9_positive"]
    audit(session, "patient", "complete", "psych_questionnaire", q.id, {"q9_positive": scores["q9_positive"]})
    session.commit()
    qid = q.id
    await bus.publish("internal/psych/questionnaire", {"id": qid})
    return {"status": "completed", "message": "Merci. Vos réponses ont été transmises à l'équipe soignante."}


@router.get("/patient/questionnaire/{token}", response_class=HTMLResponse)
def questionnaire_page(token: str, request: Request, session: Session = Depends(get_session)):
    _by_token(session, token)
    from ..config import STATIC_DIR

    return HTMLResponse((STATIC_DIR / "questionnaire.html").read_text(encoding="utf-8"))

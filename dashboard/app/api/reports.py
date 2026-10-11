"""Rapports médecin (brouillon IA, édition, signature) et rapports de garde (génération IA, validation)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import auth as authlib
from ..agents import manager as agent_manager
from ..audit import audit
from ..db import get_session
from ..models import Admission, MedicalReport, Patient, ShiftReport

router = APIRouter(tags=["reports"])


class ReportIn(BaseModel):
    admission_id: int
    title: str = "Compte rendu médical"
    content: str = ""


class ReportPatch(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


class DraftIn(BaseModel):
    admission_id: int


class ShiftGenerateIn(BaseModel):
    hours: int = 12


class ShiftPatch(BaseModel):
    content: Optional[str] = None


def _report_out(session: Session, r: MedicalReport) -> dict:
    adm = session.get(Admission, r.admission_id)
    p = session.get(Patient, adm.patient_id) if adm else None
    return {"id": r.id, "admission_id": r.admission_id, "room": adm.room_code if adm else None, "patient": p.full_name if p else None, "patient_id": p.patient_id if p else None, "patient_code": p.code if p else None,
            "author": r.author, "title": r.title, "content": r.content, "status": r.status, "ai_draft": r.ai_draft, "created_at": r.created_at, "signed_at": r.signed_at}


# ─── Rapports médecin ────────────────────────────────────────────────────────
@router.get("/api/reports")
def list_reports(admission_id: Optional[int] = None, patient_id: Optional[str] = None, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_medical_docs"))):
    q = select(MedicalReport)
    if admission_id:
        q = q.where(MedicalReport.admission_id == admission_id)
    if patient_id:
        p = session.exec(select(Patient).where(Patient.patient_id == patient_id)).first()
        if p:
            ids = [a.id for a in session.exec(select(Admission).where(Admission.patient_id == p.id)).all()]
            q = q.where(MedicalReport.admission_id.in_(ids))
    return [_report_out(session, r) for r in session.exec(q.order_by(MedicalReport.created_at.desc())).all()]


@router.get("/api/reports/{report_id}")
def get_report(report_id: int, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_medical_docs"))):
    r = session.get(MedicalReport, report_id)
    if not r:
        raise HTTPException(404, "Rapport introuvable")
    return _report_out(session, r)


@router.post("/api/reports", status_code=201)
def create_report(body: ReportIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_write_medical_docs)):
    if not session.get(Admission, body.admission_id):
        raise HTTPException(404, "Admission introuvable")
    r = MedicalReport(admission_id=body.admission_id, author=user.name or user.username, title=body.title, content=body.content, status="draft", ai_draft=False)
    session.add(r)
    session.flush()
    audit(session, user, "create", "medical_report", r.id)
    session.commit()
    return _report_out(session, r)


@router.post("/api/reports/draft", status_code=201)
async def draft_report(body: DraftIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_write_medical_docs)):
    if not session.get(Admission, body.admission_id):
        raise HTTPException(404, "Admission introuvable")
    rid = await agent_manager.report_agent().draft_medical_report(body.admission_id, author=user.name or user.username)
    audit(session, user, "ai_draft", "medical_report", rid)
    session.commit()
    return _report_out(session, session.get(MedicalReport, rid))


@router.patch("/api/reports/{report_id}")
def patch_report(report_id: int, body: ReportPatch, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_write_medical_docs)):
    r = session.get(MedicalReport, report_id)
    if not r:
        raise HTTPException(404, "Rapport introuvable")
    if r.status == "signed":
        raise HTTPException(400, "Rapport signé : modification refusée")
    if body.title is not None:
        r.title = body.title
    if body.content is not None:
        r.content = body.content
    audit(session, user, "update", "medical_report", report_id)
    session.commit()
    return _report_out(session, r)


@router.post("/api/reports/{report_id}/sign")
def sign_report(report_id: int, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_write_medical_docs)):
    r = session.get(MedicalReport, report_id)
    if not r:
        raise HTTPException(404, "Rapport introuvable")
    if not r.content.strip():
        raise HTTPException(400, "Rapport vide")
    r.status = "signed"
    r.signed_at = datetime.now(timezone.utc)
    r.author = user.name or user.username
    audit(session, user, "sign", "medical_report", report_id)
    session.commit()
    return _report_out(session, r)


# ─── Rapports de garde ───────────────────────────────────────────────────────
def _shift_out(r: ShiftReport) -> dict:
    return {"id": r.id, "shift_start": r.shift_start, "shift_end": r.shift_end, "author": r.author, "content": r.content, "status": r.status, "validated_by": r.validated_by, "created_at": r.created_at, "validated_at": r.validated_at}


@router.get("/api/shift-reports")
def list_shift_reports(session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_shift_report"))):
    return [_shift_out(r) for r in session.exec(select(ShiftReport).order_by(ShiftReport.created_at.desc()).limit(50)).all()]


@router.get("/api/shift-reports/{report_id}")
def get_shift_report(report_id: int, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_shift_report"))):
    r = session.get(ShiftReport, report_id)
    if not r:
        raise HTTPException(404, "Rapport de garde introuvable")
    return _shift_out(r)


@router.post("/api/shift-reports/generate", status_code=201)
async def generate_shift(body: ShiftGenerateIn, local: bool = False, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("edit_shift_report"))):
    from .. import n8n

    if not local and n8n.enabled() and await n8n.probe():
        ok = await n8n.send_event("shift-report", {"event": "shift-report", "hours": body.hours, "triggered_by": user.username, "platform_url": n8n.settings.platform_url, "llm_model": n8n.settings.llm_model, "telegram_chat_id": n8n.settings.telegram_chat_id, "ts": datetime.now(timezone.utc).isoformat()})
        if ok:
            audit(session, user, "generate_n8n", "shift_report", None, {"hours": body.hours})
            session.commit()
            return JSONResponse(status_code=202, content={"status": "n8n", "message": "Rapport en cours de rédaction par n8n (workflow shift-report) ; il apparaîtra dans la liste."})
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=max(1, min(body.hours, 48)))
    rid = await agent_manager.report_agent().generate_shift_report(start, end, author=f"ReportAgent (demandé par {user.username})")
    audit(session, user, "generate", "shift_report", rid)
    session.commit()
    return _shift_out(session.get(ShiftReport, rid))


@router.patch("/api/shift-reports/{report_id}")
def patch_shift(report_id: int, body: ShiftPatch, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("edit_shift_report"))):
    r = session.get(ShiftReport, report_id)
    if not r:
        raise HTTPException(404, "Rapport de garde introuvable")
    if r.status == "validated":
        raise HTTPException(400, "Rapport validé : modification refusée")
    if body.content is not None:
        r.content = body.content
    audit(session, user, "update", "shift_report", report_id)
    session.commit()
    return _shift_out(r)


@router.post("/api/shift-reports/{report_id}/validate")
def validate_shift(report_id: int, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("edit_shift_report"))):
    r = session.get(ShiftReport, report_id)
    if not r:
        raise HTTPException(404, "Rapport de garde introuvable")
    r.status = "validated"
    r.validated_by = user.name or user.username
    r.validated_at = datetime.now(timezone.utc)
    audit(session, user, "validate", "shift_report", report_id)
    session.commit()
    return _shift_out(r)

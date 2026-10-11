"""Pages d'impression HTML (ordonnance, rapport médecin, rapport de garde) → « Imprimer / PDF » du navigateur."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from .. import auth as authlib
from ..config import TEMPLATES_DIR
from ..db import get_session
from ..models import MedicalReport, Prescription, ShiftReport
from .prescriptions import _out as prescription_out
from .reports import _report_out, _shift_out

router = APIRouter(prefix="/print", tags=["print"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR / "print"))


def _fmt(d) -> str:
    if not d:
        return "—"
    if isinstance(d, datetime):
        return d.astimezone().strftime("%d/%m/%Y %H:%M")
    return str(d)


templates.env.filters["fmt"] = _fmt


def _md_to_html(md: str) -> str:
    """Markdown minimal (titres, listes, gras) sans dépendance."""
    import html
    import re

    out, in_list = [], False
    for line in md.splitlines():
        s = html.escape(line.rstrip())
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"_(.+?)_", r"<i>\1</i>", s)
        if s.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{s[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if s.startswith("### "):
            out.append(f"<h3>{s[4:]}</h3>")
        elif s.startswith("## "):
            out.append(f"<h2>{s[3:]}</h2>")
        elif s.startswith("# "):
            out.append(f"<h1>{s[2:]}</h1>")
        elif s.strip() == "":
            out.append("<br>")
        else:
            out.append(f"<p>{s}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


@router.get("/prescription/{prescription_id}", response_class=HTMLResponse)
def print_prescription(prescription_id: int, request: Request, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("view_medical_docs"))):
    pr = session.get(Prescription, prescription_id)
    if not pr:
        raise HTTPException(404, "Ordonnance introuvable")
    return templates.TemplateResponse(request, "prescription.html", {"p": prescription_out(session, pr), "user": user, "now": datetime.now()})


@router.get("/report/{report_id}", response_class=HTMLResponse)
def print_report(report_id: int, request: Request, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("view_medical_docs"))):
    r = session.get(MedicalReport, report_id)
    if not r:
        raise HTTPException(404, "Rapport introuvable")
    d = _report_out(session, r)
    d["content_html"] = _md_to_html(d["content"])
    return templates.TemplateResponse(request, "report.html", {"r": d, "user": user, "now": datetime.now()})


@router.get("/shift/{report_id}", response_class=HTMLResponse)
def print_shift(report_id: int, request: Request, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("view_shift_report"))):
    r = session.get(ShiftReport, report_id)
    if not r:
        raise HTTPException(404, "Rapport de garde introuvable")
    d = _shift_out(r)
    d["content_html"] = _md_to_html(d["content"])
    return templates.TemplateResponse(request, "shift.html", {"r": d, "user": user, "now": datetime.now()})


# ─── V2 : dossier médical (un document, ou la synthèse IA) ────────────────────
@router.get("/dossier/entry/{entry_id}", response_class=HTMLResponse)
def print_dossier_entry(entry_id: int, request: Request, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("view_medical_record"))):
    import json

    from ..audit import audit
    from ..models import MedicalRecordEntry, Patient

    e = session.get(MedicalRecordEntry, entry_id)
    if not e:
        raise HTTPException(404, "Document introuvable")
    patient = session.get(Patient, e.patient_pk)
    body = e.content
    ai = e.type == "synthese"
    if ai:
        data = json.loads(e.data_json or "{}")
        parts = [e.summary, ""]
        for title, key in (("Allergies", "allergies"), ("Maladies chroniques", "chronic"), ("Antécédents", "history"), ("Traitements actifs", "active_treatments"), ("Points d'attention", "attention")):
            parts += [f"## {title}"] + [f"- {x}" for x in data.get(key) or ["—"]] + [""]
        body = "\n".join(parts)
    d = {"id": e.id, "title": e.title, "date": e.date, "author": e.author, "service": e.service, "facility": e.facility, "content_html": _md_to_html(body), "ai": ai}
    from ..db import session_scope

    pid = patient.patient_id if patient else None
    with session_scope() as s2:  # trace hors de la session de lecture (verrou SQLite)
        audit(s2, user, "print", "medical_record_entry", entry_id, {"patient": pid})
    return templates.TemplateResponse(request, "dossier.html", {"d": d, "patient": patient, "user": user, "now": datetime.now()})


@router.get("/dossier/summary/{patient_id}", response_class=HTMLResponse)
def print_dossier_summary(patient_id: str, request: Request, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("view_medical_record"))):
    from sqlmodel import select

    from ..models import MedicalRecordEntry, Patient

    p = session.exec(select(Patient).where(Patient.patient_id == patient_id)).first()
    e = p and session.exec(select(MedicalRecordEntry).where(MedicalRecordEntry.patient_pk == p.id, MedicalRecordEntry.type == "synthese").order_by(MedicalRecordEntry.date.desc())).first()
    if not e:
        raise HTTPException(404, "Aucune synthèse : la générer d'abord depuis le dossier médical")
    return print_dossier_entry(e.id, request, session, user)

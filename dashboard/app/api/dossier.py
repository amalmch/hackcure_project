"""
Dossier médical (V2, étape 2) : frise chronologique sur plusieurs années, filtres, recherche plein texte,
résultats biologiques dans le temps, synthèse IA mise en cache, profil clinique, impression.

Accès (côté serveur) :
- médecins, owner, psychiatre : lecture et écriture ;
- infirmiers : lecture ;
- réceptionniste : identité et admissions seulement ;
- pharmacien : allergies et traitements seulement.
Tout accès au dossier est tracé dans `AuditLog`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlmodel import Session, select

from .. import auth as authlib, orchestration
from ..audit import audit
from ..db import get_session, session_scope
from ..models import Admission, LabResult, MedicalRecordEntry, Medication, Patient, Treatment

router = APIRouter(prefix="/api/dossier", tags=["dossier"])

TYPE_LABELS = {
    "consultation": "Consultation", "hospitalisation": "Hospitalisation", "operation": "Compte rendu opératoire", "biologie": "Biologie", "imagerie": "Imagerie",
    "vaccination": "Vaccination", "allergie": "Allergie", "chronique": "Maladie chronique", "familial": "Antécédents familiaux", "traitement": "Traitement au long cours",
    "ordonnance": "Ordonnance", "psychologie": "Évaluation psychologique", "intervention": "Compte rendu d'intervention", "synthese": "Synthèse IA",
}
SCOPES = {"identity": ["hospitalisation"], "pharmacy": ["allergie", "traitement", "ordonnance"]}


def scope_of(user: authlib.CurrentUser) -> str:
    if user.can("view_medical_record"):
        return "full"
    if user.can("view_record_pharmacy"):
        return "pharmacy"
    if user.can("view_record_identity"):
        return "identity"
    raise HTTPException(403, "Votre rôle n'a pas accès au dossier médical")


def audit_read(user: authlib.CurrentUser, action: str, entity: str, entity_id: Any = None, details: Any = None) -> None:
    """Trace un accès en lecture dans une transaction courte et séparée : avec SQLite, écrire dans la session de la
    requête après y avoir lu bloque les requêtes simultanées (la vue en lance plusieurs en parallèle)."""
    with session_scope() as s:
        audit(s, user, action, entity, entity_id, details)


def _patient(session: Session, patient_id: str) -> Patient:
    p = session.exec(select(Patient).where(Patient.patient_id == patient_id)).first()
    if not p:
        raise HTTPException(404, "Patient introuvable")
    return p


def entry_out(e: MedicalRecordEntry, full: bool = False, identity_only: bool = False) -> dict[str, Any]:
    d = {"id": e.id, "type": e.type, "type_label": TYPE_LABELS.get(e.type, e.type), "date": e.date.isoformat(), "title": e.title, "author": e.author, "service": e.service,
         "facility": e.facility, "summary": "" if identity_only else e.summary, "source": e.source, "status": e.status}
    if identity_only:  # réceptionniste : dates et lieux d'admission, aucun contenu clinique
        d["title"] = "Hospitalisation"
        return d
    if full:
        d["content"] = e.content
        d["data"] = json.loads(e.data_json or "{}")
    return d


def clinical_profile(session: Session, p: Patient) -> dict[str, Any]:
    """Profil clinique extrait du dossier (déterministe) : allergies, maladies chroniques, antécédents, traitements actifs."""
    rows = session.exec(select(MedicalRecordEntry).where(MedicalRecordEntry.patient_pk == p.id, MedicalRecordEntry.type.in_(["allergie", "chronique", "traitement", "hospitalisation", "operation", "familial"]))
                        .order_by(MedicalRecordEntry.date)).all()
    allergies = {a: None for a in p.allergy_list}
    chronic, history, family, long_term = [], [], [], []
    for e in rows:
        data = json.loads(e.data_json or "{}")
        if e.type == "allergie":
            allergies[(data.get("allergen") or e.title).lower()] = e.date.year
        elif e.type == "chronique":
            chronic.append({"label": data.get("condition") or e.title.replace("Diagnostic : ", ""), "since": e.date.year, "service": e.service})
        elif e.type in ("hospitalisation", "operation"):
            history.append({"label": e.title.replace("Compte rendu opératoire — ", "").replace("Hospitalisation — ", ""), "year": e.date.year, "type": e.type})
        elif e.type == "familial":
            family.append(e.content)
        elif e.type == "traitement" and data.get("active", True):
            long_term.append({"dci": data.get("dci") or e.title, "posology": data.get("posology", ""), "since": e.date.year, "indication": data.get("condition", "")})
    adm = session.exec(select(Admission).where(Admission.patient_id == p.id, Admission.discharged_at.is_(None))).first()
    current = []
    if adm:
        for t, m in session.exec(select(Treatment, Medication).join(Medication, Medication.id == Treatment.medication_id).where(Treatment.admission_id == adm.id, Treatment.end.is_(None))).all():
            current.append({"dci": m.dci, "brand": m.brand, "posology": t.posology, "route": t.route})
    return {
        "patient_id": p.patient_id, "code": p.code, "name": p.full_name, "age": p.age, "sex": p.sex, "blood_group": p.blood_group, "fall_risk": p.fall_risk,
        "allergies": [{"allergen": a, "since": y} for a, y in allergies.items()], "chronic": chronic, "history": history[-12:], "family": family,
        "long_term_treatments": long_term, "hospital_treatments": current, "room": adm.room_code if adm else None, "admission_reason": adm.reason if adm else None,
    }


@router.get("/patients")
def patients(session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.get_current_user)):
    scope = scope_of(user)
    counts = dict(session.exec(select(MedicalRecordEntry.patient_pk, func.count()).group_by(MedicalRecordEntry.patient_pk)).all())
    first = dict(session.exec(select(MedicalRecordEntry.patient_pk, func.min(MedicalRecordEntry.date)).group_by(MedicalRecordEntry.patient_pk)).all())
    out = []
    for p in session.exec(select(Patient).order_by(Patient.code)).all():
        adm = session.exec(select(Admission).where(Admission.patient_id == p.id, Admission.discharged_at.is_(None))).first()
        f = first.get(p.id)
        out.append({"patient_id": p.patient_id, "code": p.code, "name": p.full_name, "age": p.age, "room": adm.room_code if adm else None,
                    "documents": counts.get(p.id, 0) if scope == "full" else None, "since": (f.year if hasattr(f, "year") else str(f)[:4]) if f else None})
    return {"scope": scope, "patients": out, "types": TYPE_LABELS}


@router.get("/{patient_id}/profile")
def profile(patient_id: str, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.get_current_user)):
    scope = scope_of(user)
    p = _patient(session, patient_id)
    prof = clinical_profile(session, p)
    if scope == "identity":
        prof = {k: prof[k] for k in ("patient_id", "code", "name", "age", "sex", "room")}
    elif scope == "pharmacy":
        prof = {k: prof[k] for k in ("patient_id", "code", "name", "age", "allergies", "long_term_treatments", "hospital_treatments", "room")}
    audit_read(user, "read", "medical_record_profile", patient_id, {"scope": scope})
    return {"scope": scope, **prof}


@router.get("/{patient_id}/entries")
def entries(patient_id: str, type: Optional[str] = None, service: Optional[str] = None, q: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
            offset: int = 0, limit: int = Query(40, le=200), session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.get_current_user)):
    scope = scope_of(user)
    p = _patient(session, patient_id)
    base = select(MedicalRecordEntry).where(MedicalRecordEntry.patient_pk == p.id, MedicalRecordEntry.type != "synthese")
    if scope != "full":
        base = base.where(MedicalRecordEntry.type.in_(SCOPES[scope]))
    facets_rows = session.exec(select(MedicalRecordEntry.type, MedicalRecordEntry.service, func.count()).where(MedicalRecordEntry.patient_pk == p.id, MedicalRecordEntry.type != "synthese")
                               .group_by(MedicalRecordEntry.type, MedicalRecordEntry.service)).all()
    query = base
    types = [t for t in (type or "").split(",") if t]
    if types:
        query = query.where(MedicalRecordEntry.type.in_(types))
    if service:
        query = query.where(MedicalRecordEntry.service == service)
    if q and scope != "identity":
        like = f"%{q.strip()}%"
        from .. import crypto

        if crypto.enabled():  # contenu chiffré au repos : recherche dans le texte déchiffré en mémoire (≈ 100 documents par patient)
            needle = q.strip().lower()
            ids = [e.id for e in session.exec(base).all() if needle in (e.content or "").lower()]
            query = query.where(or_(MedicalRecordEntry.title.ilike(like), MedicalRecordEntry.summary.ilike(like), MedicalRecordEntry.author.ilike(like), MedicalRecordEntry.id.in_(ids)))
        else:
            query = query.where(or_(MedicalRecordEntry.title.ilike(like), MedicalRecordEntry.summary.ilike(like), MedicalRecordEntry.content.ilike(like), MedicalRecordEntry.author.ilike(like)))
    try:
        if date_from:
            query = query.where(MedicalRecordEntry.date >= datetime.fromisoformat(date_from[:10]).replace(tzinfo=timezone.utc))
        if date_to:
            query = query.where(MedicalRecordEntry.date <= datetime.fromisoformat(date_to[:10] + "T23:59:59").replace(tzinfo=timezone.utc))
    except ValueError:
        raise HTTPException(400, "Date invalide (AAAA-MM-JJ)")
    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    rows = session.exec(query.order_by(MedicalRecordEntry.date.desc()).offset(max(0, offset)).limit(limit)).all()
    allowed = None if scope == "full" else set(SCOPES[scope])
    type_counts: dict[str, int] = {}
    services: dict[str, int] = {}
    for t, s, n in facets_rows:
        if allowed is None or t in allowed:
            type_counts[t] = type_counts.get(t, 0) + n
            if s:
                services[s] = services.get(s, 0) + n
    bounds = session.exec(select(func.min(MedicalRecordEntry.date), func.max(MedicalRecordEntry.date)).where(MedicalRecordEntry.patient_pk == p.id)).one()
    audit_read(user, "read", "medical_record", patient_id, {"scope": scope, "q": q, "type": type, "offset": offset, "returned": len(rows)})
    return {"scope": scope, "total": total, "offset": offset, "limit": limit, "items": [entry_out(e, identity_only=scope == "identity") for e in rows],
            "facets": {"types": type_counts, "services": services if scope != "identity" else {}}, "first_date": str(bounds[0])[:10] if bounds[0] else None, "last_date": str(bounds[1])[:10] if bounds[1] else None}


@router.get("/entries/{entry_id}")
def entry(entry_id: int, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.get_current_user)):
    scope = scope_of(user)
    e = session.get(MedicalRecordEntry, entry_id)
    if not e:
        raise HTTPException(404, "Document introuvable")
    if scope != "full" and e.type not in SCOPES[scope]:
        raise HTTPException(403, "Ce document n'est pas accessible à votre rôle")
    p = session.get(Patient, e.patient_pk)
    d = entry_out(e, full=scope != "identity", identity_only=scope == "identity")
    d["patient_id"] = p.patient_id if p else None
    if scope == "full" and e.type == "biologie":
        d["labs"] = [{"code": r.code, "label": r.label, "value": r.value, "text": r.text, "unit": r.unit, "ref_low": r.ref_low, "ref_high": r.ref_high, "abnormal": r.abnormal}
                     for r in session.exec(select(LabResult).where(LabResult.entry_id == e.id).order_by(LabResult.id)).all()]
    audit_read(user, "read", "medical_record_entry", entry_id, {"type": e.type, "patient": d["patient_id"], "scope": scope})
    return d


class EntryIn(BaseModel):
    type: str = "consultation"
    title: str
    content: str = ""
    summary: str = ""
    service: str = ""
    date: Optional[datetime] = None


class EntryPatch(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = None


@router.post("/{patient_id}/entries", status_code=201)
def create_entry(patient_id: str, body: EntryIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("write_medical_record"))):
    p = _patient(session, patient_id)
    if body.type not in TYPE_LABELS or body.type == "synthese":
        raise HTTPException(400, "Type de document inconnu")
    adm = session.exec(select(Admission).where(Admission.patient_id == p.id, Admission.discharged_at.is_(None))).first()
    e = MedicalRecordEntry(patient_pk=p.id, admission_id=adm.id if adm else None, type=body.type, date=body.date or datetime.now(timezone.utc), title=body.title.strip()[:200], author=user.name or user.username,
                           service=body.service or "Clinique HackCure", facility="Clinique HackCure", summary=(body.summary or body.content)[:200], content=body.content, source="plateforme")
    session.add(e)
    session.flush()
    audit(session, user, "create", "medical_record_entry", e.id, {"patient": patient_id, "type": e.type})
    session.commit()
    session.refresh(e)
    return entry_out(e, full=True)


@router.patch("/entries/{entry_id}")
def patch_entry(entry_id: int, body: EntryPatch, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("write_medical_record"))):
    e = session.get(MedicalRecordEntry, entry_id)
    if not e:
        raise HTTPException(404, "Document introuvable")
    if e.source == "historique":
        raise HTTPException(409, "Un document d'archive ne se modifie pas : ajouter un nouveau document")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(e, k, v)
    audit(session, user, "update", "medical_record_entry", entry_id, body.model_dump(exclude_none=True))
    session.commit()
    session.refresh(e)
    return entry_out(e, full=True)


@router.get("/{patient_id}/labs")
def lab_series(patient_id: str, code: Optional[str] = None, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("view_medical_record"))):
    """Sans `code` : examens disponibles (nombre de valeurs, dernière valeur). Avec `code` : série chronologique."""
    p = _patient(session, patient_id)
    if not code:
        rows = session.exec(select(LabResult).where(LabResult.patient_pk == p.id, LabResult.value.is_not(None)).order_by(LabResult.date)).all()
        codes: dict[str, dict[str, Any]] = {}
        for r in rows:
            c = codes.setdefault(r.code, {"code": r.code, "label": r.label, "unit": r.unit, "count": 0, "ref_low": r.ref_low, "ref_high": r.ref_high})
            c.update(count=c["count"] + 1, last=r.value, last_date=r.date.date().isoformat(), last_abnormal=r.abnormal)
        return sorted(codes.values(), key=lambda c: -c["count"])
    rows = session.exec(select(LabResult).where(LabResult.patient_pk == p.id, LabResult.code == code.upper(), LabResult.value.is_not(None)).order_by(LabResult.date)).all()
    audit_read(user, "read", "medical_record_labs", patient_id, {"code": code})
    return {"code": code.upper(), "label": rows[0].label if rows else code, "unit": rows[0].unit if rows else "", "ref_low": rows[0].ref_low if rows else None, "ref_high": rows[0].ref_high if rows else None,
            "points": [{"date": r.date.isoformat(), "value": r.value, "abnormal": r.abnormal, "entry_id": r.entry_id} for r in rows]}


# ─── synthèse IA du dossier (mise en cache, régénérable) ─────────────────────
def summary_context(session: Session, p: Patient) -> dict[str, Any]:
    prof = clinical_profile(session, p)
    last_labs: dict[str, Any] = {}
    for r in session.exec(select(LabResult).where(LabResult.patient_pk == p.id, LabResult.value.is_not(None)).order_by(LabResult.date.desc()).limit(200)).all():
        last_labs.setdefault(r.code, {"examen": r.label, "valeur": r.value, "unite": r.unit, "date": r.date.date().isoformat(), "anormal": r.abnormal})
    recent = session.exec(select(MedicalRecordEntry).where(MedicalRecordEntry.patient_pk == p.id, MedicalRecordEntry.type.in_(["consultation", "hospitalisation", "operation", "imagerie", "psychologie", "intervention"]))
                          .order_by(MedicalRecordEntry.date.desc()).limit(14)).all()
    total = session.exec(select(func.count()).where(MedicalRecordEntry.patient_pk == p.id)).one()
    return {"task": "record_summary", "patient": {"nom": prof["name"], "age": prof["age"], "sexe": prof["sex"], "groupe_sanguin": prof["blood_group"], "risque_de_chute": prof["fall_risk"]},
            "documents_au_dossier": total, "allergies": prof["allergies"], "maladies_chroniques": prof["chronic"], "antecedents": prof["history"], "antecedents_familiaux": prof["family"],
            "traitements_au_long_cours": prof["long_term_treatments"], "traitements_hospitaliers_en_cours": prof["hospital_treatments"], "hospitalisation_en_cours": prof["admission_reason"],
            "dernieres_valeurs_biologiques": {k: v for k, v in last_labs.items() if v["anormal"] or k in ("HBA1C", "CREAT", "HB", "BNP")},
            "documents_recents": [{"date": e.date.date().isoformat(), "type": e.type, "titre": e.title, "resume": e.summary} for e in recent]}


def _summary_out(e: Optional[MedicalRecordEntry]) -> dict[str, Any]:
    if not e:
        return {"status": "none"}
    return {"status": "ready", "id": e.id, "generated_at": e.date.isoformat(), "author": e.author, "summary": e.summary, **json.loads(e.data_json or "{}"), "disclaimer": orchestration.DISCLAIMER}


@orchestration.handler("record-summary")
async def on_summary(ref: str, result: dict[str, Any], meta: dict[str, Any]) -> Optional[str]:
    from ..ws import manager

    clean = lambda xs: [str(x)[:300] for x in (xs or []) if str(x).strip()][:12]  # noqa: E731
    data = {"allergies": clean(result.get("allergies")), "chronic": clean(result.get("chronic")), "history": clean(result.get("history")), "active_treatments": clean(result.get("active_treatments")),
            "attention": clean(result.get("attention")), "provider": meta.get("provider") or "anthropic (n8n)", "fallback": bool(meta.get("fallback"))}
    with session_scope() as s:
        p = s.exec(select(Patient).where(Patient.patient_id == ref)).first()
        if not p:
            return None
        for old in s.exec(select(MedicalRecordEntry).where(MedicalRecordEntry.patient_pk == p.id, MedicalRecordEntry.type == "synthese")).all():
            s.delete(old)
        e = MedicalRecordEntry(patient_pk=p.id, type="synthese", date=datetime.now(timezone.utc), title="Synthèse IA du dossier médical", author=data["provider"], service="Hospital Copilot", facility="Clinique HackCure",
                               summary=str(result.get("summary") or "")[:1500], content="", data_json=json.dumps(data, ensure_ascii=False), source="ia", status="draft")
        s.add(e)
        s.flush()
        out = _summary_out(e)
    await manager.broadcast({"type": "dossier_summary", "patient_id": ref, "summary": out})
    return None


@router.get("/{patient_id}/summary")
def get_summary(patient_id: str, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("view_medical_record"))):
    p = _patient(session, patient_id)
    e = session.exec(select(MedicalRecordEntry).where(MedicalRecordEntry.patient_pk == p.id, MedicalRecordEntry.type == "synthese").order_by(MedicalRecordEntry.date.desc())).first()
    return _summary_out(e)


@router.post("/{patient_id}/summary", status_code=202)
async def regenerate_summary(patient_id: str, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("view_medical_record"))):
    p = _patient(session, patient_id)
    ctx = summary_context(session, p)
    audit(session, user, "generate", "medical_record_summary", patient_id)
    session.commit()
    path = await orchestration.ask("record-summary", patient_id, ctx)
    return {"status": "pending", "via": path}

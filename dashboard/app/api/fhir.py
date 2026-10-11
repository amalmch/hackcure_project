"""
API HL7 FHIR R4 en LECTURE SEULE (V3, étape 4 — interopérabilité).

    GET /fhir/metadata                          CapabilityStatement
    GET /fhir/Patient/{id}                      Patient (identifiant = pseudonyme « PAT-0001 »)
    GET /fhir/Observation?patient=              constantes vitales (LOINC / UCUM) + biologie
    GET /fhir/Condition?patient=                maladies chroniques, antécédents, motif d'hospitalisation
    GET /fhir/AllergyIntolerance?patient=       allergies
    GET /fhir/MedicationRequest?patient=        ordonnances de traitement hospitalières (`inpatient`) + ordonnance de sortie signée (`discharge`)
    GET /fhir/Encounter?patient=                admissions
    GET /fhir/DocumentReference?patient=        rapports médecin signés et comptes rendus de sortie (texte pseudonymisé, base64)
    GET /fhir/Patient/{id}/$everything          Bundle de tout ce que le rôle peut lire

Droits : les mêmes que le dossier médical (`app/api/dossier.py`) —
- médecins, owner, psychiatre, infirmiers (`view_medical_record`) : toutes les ressources ;
- pharmacien (`view_record_pharmacy`) : Patient pseudonymisé, AllergyIntolerance, MedicationRequest ;
- réceptionniste (`view_record_identity`) : Patient et Encounter (dates et lieu, sans motif clinique).
Identité (nom, date de naissance complète) : seulement avec la permission `view_identity` ; sinon ressource pseudonymisée.
Chaque lecture écrit une ligne `AuditLog` (action « fhir_read ») dans une transaction courte et séparée.
Interrupteur : `FHIR_ENABLED` (activé par défaut) ; désactivé, toutes les routes répondent 404 (OperationOutcome).
"""

from __future__ import annotations

import functools
import logging
import os
import re
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from .. import auth as authlib, fhir as fmap, privacy, state
from ..audit import audit
from ..db import get_session, session_scope
from ..models import (Admission, LabResult, MedicalRecordEntry, MedicalReport, Medication, Patient, Prescription, PrescriptionLine, Treatment, TreatmentOrder,
                      TreatmentOrderLine, VitalReading)

logger = logging.getLogger("hackcure.fhir")

router = APIRouter(prefix="/fhir", tags=["fhir"])

# type de ressource -> portées du dossier médical autorisées (voir `dossier.scope_of`)
ACCESS: dict[str, set[str]] = {
    "Patient": {"full", "pharmacy", "identity"},
    "Observation": {"full"},
    "Condition": {"full"},
    "AllergyIntolerance": {"full", "pharmacy"},
    "MedicationRequest": {"full", "pharmacy"},
    "Encounter": {"full", "identity"},
    "DocumentReference": {"full"},
}
# métrique -> type d'appareil qui la mesure (horodatage et appareil de la dernière valeur en direct)
METRIC_DEVICE = {"hr": "ecg", "rr": "ecg", "spo2": "spo2", "sys": "bp", "dia": "bp", "map": "bp", "tempC": "thermometer", "glucose": "glucometer"}
MAX_LABS = 1000


class FhirResponse(JSONResponse):
    media_type = fmap.FHIR_MEDIA_TYPE


class FhirError(Exception):
    def __init__(self, status: int, code: str, diagnostics: str):
        super().__init__(diagnostics)
        self.status, self.code, self.diagnostics = status, code, diagnostics


def fhir_enabled() -> bool:
    """Lu à chaque requête (variable d'environnement `FHIR_ENABLED`, activé par défaut)."""
    return os.getenv("FHIR_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


def can_see_identity(user: authlib.CurrentUser) -> bool:
    return user.can("view_identity")


def scope_of(user: authlib.CurrentUser) -> str:
    """Même découpage par rôle que le dossier médical."""
    if user.can("view_medical_record"):
        return "full"
    if user.can("view_record_pharmacy"):
        return "pharmacy"
    if user.can("view_record_identity"):
        return "identity"
    raise FhirError(403, "forbidden", "Votre rôle n'a pas accès au dossier médical")


def fhir_route(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Interrupteur FHIR_ENABLED + erreurs rendues en OperationOutcome (`application/fhir+json`)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            if not fhir_enabled():
                raise FhirError(404, "not-supported", "L'API FHIR est désactivée (FHIR_ENABLED=0)")
            return FhirResponse(fn(*args, **kwargs))
        except FhirError as e:
            return FhirResponse(fmap.operation_outcome(e.code, e.diagnostics), status_code=e.status)

    return wrapper


def _user(request: Request) -> authlib.CurrentUser:
    user = authlib.optional_user(request)
    if user is None:
        raise FhirError(401, "login", "Authentification requise")
    return user


def _audit(user: authlib.CurrentUser, entity: str, entity_id: Any, details: dict[str, Any], action: str = "fhir_read") -> None:
    """Transaction courte et séparée (SQLite : ne jamais écrire dans la session de lecture de la requête)."""
    try:
        with session_scope() as s:
            audit(s, user, action, entity, entity_id, details)
    except Exception:  # la traçabilité ne doit pas faire échouer une lecture
        logger.warning("Audit FHIR non écrit", exc_info=True)


def _authorize(user: authlib.CurrentUser, rtype: str, ref: Optional[str] = None) -> str:
    scope = scope_of(user)
    if scope not in ACCESS[rtype]:
        _audit(user, f"fhir:{rtype}", ref, {"scope": scope}, action="fhir_denied")
        raise FhirError(403, "forbidden", f"Rôle « {authlib.ROLE_LABELS.get(user.role, user.role)} » : la ressource {rtype} n'est pas accessible")
    return scope


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/fhir"


def _patient(session: Session, ref: Optional[str]) -> Patient:
    """Accepte le pseudonyme (« PAT-0001 »), l'identifiant interne (« patient_01 ») ou une référence (« Patient/PAT-0001 »)."""
    raw = (ref or "").strip()
    if not raw:
        raise FhirError(400, "required", "Paramètre de recherche « patient » obligatoire (ex. ?patient=PAT-0001)")
    key = raw.rsplit("/", 1)[-1].strip()
    p = session.exec(select(Patient).where(Patient.code == key.upper())).first() or session.exec(select(Patient).where(Patient.patient_id == key)).first()
    if not p:
        raise FhirError(404, "not-found", f"Patient « {raw} » introuvable")
    return p


def _admissions(session: Session, p: Patient) -> list[Admission]:
    return list(session.exec(select(Admission).where(Admission.patient_id == p.id).order_by(Admission.admitted_at.desc())).all())


# ─── lecture des données par type de ressource ───────────────────────────────
def _vitals(session: Session, p: Patient) -> list[dict[str, Any]]:
    """Dernières constantes : valeurs en direct de la chambre (état temps réel), complétées par les mesures persistées (`VitalReading`)."""
    adms = _admissions(session, p)
    active = next((a for a in adms if a.discharged_at is None), None)
    values: dict[str, Any] = {}
    times: dict[str, Any] = {}
    devices: dict[str, str] = {}
    if active is not None:
        rs = state.room_states.get(active.room_code) or {}
        if rs.get("patient_id") in (None, p.patient_id):
            live = rs.get("vitals") or {}
            by_type = {d.get("type"): (dev_id, d) for dev_id, d in (rs.get("devices") or {}).items()}
            for metric, dtype in METRIC_DEVICE.items():
                if isinstance(live.get(metric), (int, float)) and not isinstance(live.get(metric), bool):
                    values[metric] = live[metric]
                    dev_id, d = by_type.get(dtype, (None, {}))
                    times[metric] = d.get("ts") or rs.get("ts")
                    if dev_id:
                        devices[metric] = dev_id
    adm_ids = [a.id for a in adms]
    if adm_ids:
        for metric in METRIC_DEVICE:
            if metric in values:
                continue
            r = session.exec(select(VitalReading).where(VitalReading.admission_id.in_(adm_ids), VitalReading.metric == metric).order_by(VitalReading.ts.desc()).limit(1)).first()
            if r is not None:
                values[metric], times[metric], devices[metric] = r.value, r.ts, r.device_id
    return fmap.vital_observations(p.code, values, times, devices, encounter_id=f"enc-{active.id}" if active is not None else None)


def _labs(session: Session, p: Patient) -> list[dict[str, Any]]:
    rows = session.exec(select(LabResult).where(LabResult.patient_pk == p.id).order_by(LabResult.date.desc()).limit(MAX_LABS)).all()
    return [fmap.lab_observation(r, p.code) for r in rows]


def _observations(session: Session, p: Patient, category: Optional[str] = None) -> list[dict[str, Any]]:
    cats = {c.rsplit("|", 1)[-1].strip() for c in (category or "").split(",") if c.strip()}
    out: list[dict[str, Any]] = []
    if not cats or "vital-signs" in cats:
        out += _vitals(session, p)
    if not cats or "laboratory" in cats:
        out += _labs(session, p)
    return out


def _conditions(session: Session, p: Patient) -> list[dict[str, Any]]:
    chronic = session.exec(select(MedicalRecordEntry).where(MedicalRecordEntry.patient_pk == p.id, MedicalRecordEntry.type == "chronique").order_by(MedicalRecordEntry.date)).all()
    active = session.exec(select(Admission).where(Admission.patient_id == p.id, Admission.discharged_at.is_(None))).first()
    return fmap.condition_resources(p, chronic, active)


def _allergies(session: Session, p: Patient) -> list[dict[str, Any]]:
    entries = session.exec(select(MedicalRecordEntry).where(MedicalRecordEntry.patient_pk == p.id, MedicalRecordEntry.type == "allergie").order_by(MedicalRecordEntry.date)).all()
    return fmap.allergy_resources(p, entries)


def _medication_requests(session: Session, p: Patient) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    rows = session.exec(select(TreatmentOrderLine, TreatmentOrder, Medication).join(TreatmentOrder, TreatmentOrder.id == TreatmentOrderLine.order_id)
                        .join(Medication, Medication.id == TreatmentOrderLine.medication_id, isouter=True).where(TreatmentOrder.patient_pk == p.id)
                        .order_by(TreatmentOrder.created_at.desc(), TreatmentOrderLine.id)).all()
    out += [fmap.medication_request_from_line(line, order, med, p.code) for line, order, med in rows]
    adm_ids = [a.id for a in _admissions(session, p)]
    if adm_ids:
        for t, med in session.exec(select(Treatment, Medication).join(Medication, Medication.id == Treatment.medication_id).where(Treatment.admission_id.in_(adm_ids)).order_by(Treatment.start.desc())).all():
            out.append(fmap.medication_request_from_treatment(t, med, p.code))
        # ordonnance de sortie (`Prescription`) : seulement les ordonnances SIGNÉES
        rows2 = session.exec(select(PrescriptionLine, Prescription, Medication).join(Prescription, Prescription.id == PrescriptionLine.prescription_id)
                             .join(Medication, Medication.id == PrescriptionLine.medication_id, isouter=True)
                             .where(Prescription.admission_id.in_(adm_ids), Prescription.status == "signed").order_by(Prescription.created_at.desc(), PrescriptionLine.id)).all()
        out += [fmap.medication_request_from_prescription_line(line, pr, med, p.code, notes=_pseudonymise(pr.notes, p)) for line, pr, med in rows2]
    return out


def _pseudonymise(value: Optional[str], p: Patient) -> str:
    """Texte qui QUITTE la plateforme : les noms de patients connus (`privacy.text`) puis, par sécurité, le nom et le prénom
    de ce patient (sans tenir compte de la casse) sont remplacés par le pseudonyme. Appliqué quel que soit le rôle de l'appelant."""
    out = privacy.text(value or "")
    first, last = (p.first_name or "").strip(), (p.last_name or "").strip()
    variants = sorted({v for v in (f"{first} {last}", f"{last} {first}", f"{last}, {first}", last, first) if len(v.strip()) >= 2}, key=len, reverse=True)
    if variants and out:
        out = re.sub(r"(?<![\w-])(?:" + "|".join(re.escape(v) for v in variants) + r")(?![\w-])", p.code, out, flags=re.IGNORECASE)
    return out


DISCHARGE_TITLE = re.compile(r"sortie|hospitalisation", re.IGNORECASE)


def _documents(session: Session, p: Patient) -> list[dict[str, Any]]:
    """Rapports médecin SIGNÉS (`MedicalReport`) et comptes rendus de sortie. Il n'existe pas de table « rapport de sortie » :
    un rapport signé est un compte rendu de sortie (LOINC 18842-5) quand son séjour est terminé ou que son titre le dit
    (« sortie », « hospitalisation ») ; sinon c'est un rapport médecin (11488-4). S'y ajoutent les comptes rendus
    d'hospitalisation signés du dossier médical (`MedicalRecordEntry` de type « hospitalisation »). Texte toujours pseudonymisé."""
    out: list[dict[str, Any]] = []
    adms = {a.id: a for a in _admissions(session, p)}
    if adms:
        for r in session.exec(select(MedicalReport).where(MedicalReport.admission_id.in_(list(adms)), MedicalReport.status == "signed").order_by(MedicalReport.signed_at.desc(), MedicalReport.id.desc())).all():
            adm = adms.get(r.admission_id)
            kind = "discharge" if (adm is not None and adm.discharged_at is not None) or DISCHARGE_TITLE.search(r.title or "") else "report"
            title = _pseudonymise(r.title, p) or "Rapport médical"
            out.append(fmap.document_reference(f"docref-report-{r.id}", p.code, kind, title, _pseudonymise(r.content, p), when=r.signed_at or r.created_at, author=r.author,
                                               description=title, encounter_id=f"enc-{r.admission_id}"))
    entries = session.exec(select(MedicalRecordEntry).where(MedicalRecordEntry.patient_pk == p.id, MedicalRecordEntry.type == "hospitalisation", MedicalRecordEntry.status == "signed")
                           .order_by(MedicalRecordEntry.date.desc())).all()
    for e in entries:
        title = _pseudonymise(e.title, p) or "Hospitalisation"
        out.append(fmap.document_reference(f"docref-record-{e.id}", p.code, "discharge", title, _pseudonymise(e.content or e.summary, p), when=e.date, author=e.author,
                                           description=_pseudonymise(e.summary, p) or title, encounter_id=f"enc-{e.admission_id}" if e.admission_id else None))
    return out


def _encounters(session: Session, p: Patient, scope: str) -> list[dict[str, Any]]:
    return [fmap.encounter_resource(a, p.code, clinical=scope == "full") for a in _admissions(session, p)]


def _search(request: Request, session: Session, rtype: str, patient: Optional[str], loader: Callable[[Session, Patient, str], list[dict[str, Any]]]) -> dict[str, Any]:
    user = _user(request)
    scope = _authorize(user, rtype, patient)
    p = _patient(session, patient)
    resources = loader(session, p, scope)
    _audit(user, f"fhir:{rtype}", p.code, {"scope": scope, "returned": len(resources), "query": str(request.url.query)[:200]})
    return fmap.bundle(resources, _base(request), self_url=str(request.url))


# ─── routes ──────────────────────────────────────────────────────────────────
@router.get("/metadata")
@fhir_route
def metadata(request: Request):
    _user(request)
    return fmap.capability_statement(_base(request))


@router.get("/Patient/{patient_id}/$everything")
@fhir_route
def patient_everything(patient_id: str, request: Request, session: Session = Depends(get_session)):
    """Bundle de toutes les ressources du patient que le rôle de l'appelant peut lire."""
    user = _user(request)
    scope = _authorize(user, "Patient", patient_id)
    p = _patient(session, patient_id)
    identity = can_see_identity(user)
    resources: list[dict[str, Any]] = [fmap.patient_resource(p, identity=identity)]
    loaders: list[tuple[str, Callable[[], list[dict[str, Any]]]]] = [
        ("Encounter", lambda: _encounters(session, p, scope)),
        ("Condition", lambda: _conditions(session, p)),
        ("AllergyIntolerance", lambda: _allergies(session, p)),
        ("MedicationRequest", lambda: _medication_requests(session, p)),
        ("Observation", lambda: _observations(session, p)),
        ("DocumentReference", lambda: _documents(session, p)),
    ]
    included = ["Patient"]
    for rtype, load in loaders:
        if scope in ACCESS[rtype]:
            resources += load()
            included.append(rtype)
    _audit(user, "fhir:Patient/$everything", p.code, {"scope": scope, "identity": identity, "returned": len(resources), "types": included})
    return fmap.bundle(resources, _base(request), self_url=str(request.url))


@router.get("/Patient/{patient_id}")
@fhir_route
def read_patient(patient_id: str, request: Request, session: Session = Depends(get_session)):
    user = _user(request)
    scope = _authorize(user, "Patient", patient_id)
    p = _patient(session, patient_id)
    identity = can_see_identity(user)
    _audit(user, "fhir:Patient", p.code, {"scope": scope, "identity": identity})
    return fmap.patient_resource(p, identity=identity)


@router.get("/Observation")
@fhir_route
def search_observation(request: Request, patient: Optional[str] = None, subject: Optional[str] = None, category: Optional[str] = None, session: Session = Depends(get_session)):
    return _search(request, session, "Observation", patient or subject, lambda s, p, _scope: _observations(s, p, category))


@router.get("/Condition")
@fhir_route
def search_condition(request: Request, patient: Optional[str] = None, subject: Optional[str] = None, session: Session = Depends(get_session)):
    return _search(request, session, "Condition", patient or subject, lambda s, p, _scope: _conditions(s, p))


@router.get("/AllergyIntolerance")
@fhir_route
def search_allergy(request: Request, patient: Optional[str] = None, session: Session = Depends(get_session)):
    return _search(request, session, "AllergyIntolerance", patient, lambda s, p, _scope: _allergies(s, p))


@router.get("/MedicationRequest")
@fhir_route
def search_medication_request(request: Request, patient: Optional[str] = None, subject: Optional[str] = None, session: Session = Depends(get_session)):
    return _search(request, session, "MedicationRequest", patient or subject, lambda s, p, _scope: _medication_requests(s, p))


@router.get("/Encounter")
@fhir_route
def search_encounter(request: Request, patient: Optional[str] = None, subject: Optional[str] = None, session: Session = Depends(get_session)):
    return _search(request, session, "Encounter", patient or subject, lambda s, p, scope: _encounters(s, p, scope))


@router.get("/DocumentReference")
@fhir_route
def search_document_reference(request: Request, patient: Optional[str] = None, subject: Optional[str] = None, session: Session = Depends(get_session)):
    return _search(request, session, "DocumentReference", patient or subject, lambda s, p, _scope: _documents(s, p))

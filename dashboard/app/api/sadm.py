"""
SADM — système d'aide à la décision médicale (V3, étape 6).

Pour toute recommandation affichée (risque et plan d'action, parcours fièvre et bilan biologique proposé,
hypothèse diagnostique, prédiction, score psychologique) :
- un **indice de confiance mesurable** (0–100 %) calculé par une formule déterministe, publiée avec le résultat ;
- les **paramètres cliniques déclencheurs** ;
- la **décision du soignant** (valider / rejeter, motif facultatif), tracée dans `AuditLog` (qui, quand, quoi, IP).

L'indice n'est PAS une probabilité clinique validée : il mesure la solidité des données qui fondent la
recommandation (confiance du détecteur, persistance du signal, concordance, complétude). Voir docs/biais.md.

Interrupteur : `SADM_ENABLED` (activé par défaut).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import auth as authlib
from ..audit import audit
from ..db import get_session
from ..ingest import handler
from ..models import AuditLog, DiagnosticHypothesis, FeverPathway, Patient, Prediction, PsychScore, Risk

router = APIRouter(prefix="/api/sadm", tags=["sadm"])

BANNER = "Recommandation consultative — la décision et la signature restent celles du médecin"
DECIDERS = {"nurse", "duty_doctor", "general_doctor", "psychiatrist", "owner"}  # rôles soignants : valident ou rejettent une recommandation
KINDS = {"risk", "fever", "hypothesis", "prediction", "psych"}
VISION_TYPES = {"fall", "unaccompanied_bed_exit", "bed_exit", "toilet_too_long", "patient_out_of_room", "pain", "behavioral_risk"}
LEVEL_PCT = {"faible": 45, "modérée": 65, "modéré": 65, "élevée": 85, "élevé": 85}


def enabled() -> bool:
    return os.getenv("SADM_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


def level(pct: int) -> str:
    return "élevée" if pct >= 80 else ("modérée" if pct >= 60 else "faible")


def clamp(v: float, lo: int = 20, hi: int = 97) -> int:
    return int(max(lo, min(hi, round(v))))


def _vitals_line(v: dict[str, Any]) -> list[str]:
    out = []
    for key, label, unit in (("hr", "FC", "/min"), ("spo2", "SpO2", " %"), ("sys", "PAS", " mmHg"), ("tempC", "T°", " °C"), ("rr", "FR", "/min"), ("glucose", "glycémie", " g/L")):
        if v.get(key) is not None:
            out.append(f"{label} {v[key]}{unit}")
    return out


# ── calcul de l'indice par type de recommandation (fonctions pures, testées) ──
def risk_confidence(rtype: str, notes: str, detector_conf: Optional[float], other_open: int, prediction_conf: Optional[str] = None, criterion: str = "") -> dict[str, Any]:
    parts: list[tuple[str, float]] = []
    if rtype.startswith("predicted_"):
        base = LEVEL_PCT.get(prediction_conf or "", 55)
        parts.append((f"confiance de la prédiction « {prediction_conf or 'non renseignée'} »", base))
    elif rtype in VISION_TYPES:
        base = clamp((detector_conf if detector_conf is not None else 0.7) * 100, 50, 92)
        parts.append((f"confiance du détecteur de vision ({(detector_conf if detector_conf is not None else 0.7):.0%})", base))
    elif rtype == "fever":
        base = 85 if "confirmée" in criterion else 72
        parts.append(("température centrale " + ("confirmée sur 3 lectures" if base == 85 else "au-dessus du seuil à deux reprises"), base))
    elif rtype == "equipment_fault":
        base = 88
        parts.append(("panne déclarée par l'appareil ou le pipeline", base))
    elif rtype in ("news2_high", "sepsis_trend"):
        base = 78
        parts.append(("score standardisé calculé sur les constantes du moment", base))
    else:
        base = 72
        parts.append(("seuil franchi sur 3 lectures consécutives", base))
    repeats = min(2, notes.count("signal répété"))
    if repeats:
        parts.append((f"signal confirmé {repeats} fois depuis l'ouverture", 5 * repeats))
    if other_open:
        parts.append(("autre risque ouvert concordant dans la chambre", 5))
    if "signal revenu dans les limites" in notes or "revenu à la normale" in notes:
        parts.append(("signal revenu dans les limites depuis", -15))
    pct = clamp(sum(p for _, p in parts), 30, 97)
    return {"pct": pct, "level": level(pct), "method": "Indice = " + " ; ".join(f"{t} ({'+' if p >= 0 and i else ''}{p:.0f})" for i, (t, p) in enumerate(parts)) + f" → {pct} % (borné à 30–97)."}


def hypothesis_confidence(probability: str, pros: list[str], cons: list[str]) -> dict[str, Any]:
    base = {"faible": 35, "modérée": 60, "élevée": 85}.get(probability, 50)
    pct = clamp(base + 3 * min(4, len(pros)) - 5 * min(4, len(cons)), 20, 95)
    return {"pct": pct, "level": level(pct), "method": f"Indice = probabilité des règles « {probability} » ({base}) + 3 × éléments pour ({len(pros)}) − 5 × éléments contre ({len(cons)}) → {pct} %."}


def prediction_confidence(conf: str, factors: list[str]) -> dict[str, Any]:
    base = LEVEL_PCT.get(conf, 45)
    pct = clamp(base + 2 * min(5, len(factors)), 30, 95)
    return {"pct": pct, "level": level(pct), "method": f"Indice = quantité de données disponibles pour cette condition, niveau « {conf} » ({base}) + 2 × facteurs présents ({len(factors)}) → {pct} %. Ce n'est pas la probabilité de la crise."}


def psych_confidence(inputs: dict[str, Any]) -> dict[str, Any]:
    parts = [("base", 25)]
    if inputs.get("questionnaire"):
        parts.append(("questionnaire d'admission rempli", 45))
    if int((inputs.get("expressions") or {}).get("total") or 0) >= 20:
        parts.append(("au moins 20 observations d'expression", 15))
    if inputs.get("sleep_hours") is not None:
        parts.append(("sommeil mesuré", 10))
    if any((inputs.get("behavior") or {}).values()):
        parts.append(("indicateurs comportementaux", 5))
    pct = clamp(sum(p for _, p in parts), 25, 95)
    return {"pct": pct, "level": level(pct), "method": "Indice = complétude des données : " + " ; ".join(f"{t} (+{p})" for t, p in parts) + f" → {pct} %."}


# ── lecture des objets ───────────────────────────────────────────────────────
def _patient(session: Session, patient_id: str) -> Patient:
    p = session.exec(select(Patient).where(Patient.patient_id == patient_id)).first()
    if not p:
        raise HTTPException(404, "Patient introuvable")
    return p


def explain(session: Session, kind: str, ref: Optional[str], patient: Optional[str] = None, label: Optional[str] = None) -> dict[str, Any]:
    if kind not in KINDS:
        raise HTTPException(400, f"Type de recommandation inconnu : {kind}")
    if kind in ("risk", "fever"):
        r = session.get(Risk, int(ref)) if ref and str(ref).isdigit() else None
        if not r:
            raise HTTPException(404, "Risque introuvable")
        rs = handler.room_state(r.room_code)
        path = session.exec(select(FeverPathway).where(FeverPathway.risk_id == r.id)).first()
        pred = None
        if r.type.startswith("predicted_"):
            from ..clinical.prediction import RISK_TYPES

            key = next((k for k, v in RISK_TYPES.items() if v == r.type), None)
            pred = session.exec(select(Prediction).where(Prediction.room_code == r.room_code, Prediction.key == key).order_by(Prediction.id.desc())).first() if key else None
        others = len(session.exec(select(Risk.id).where(Risk.room_code == r.room_code, Risk.id != r.id, Risk.status.in_(("open", "in_progress", "escalated")))).all())
        conf = risk_confidence(r.type, r.notes or "", rs.get("confidence") if r.type in VISION_TYPES else None, others, pred.confidence if pred else None, path.criterion if path else "")
        triggers = [f"{r.title or r.type} — sévérité {r.severity} (fixée par les règles, pas par l'IA)"]
        if kind == "fever" and path:
            triggers = [f"Critère : {path.criterion}", f"qSOFA {path.qsofa}/3" + (f" · NEWS2 {path.news2}" if path.news2 is not None else "")]
            triggers += [f"{x.get('label')} : {x.get('motif') or x.get('justification') or 'règle'}" for x in json.loads(path.labs_json or "[]") if x.get("selected")][:8]
        else:
            if r.type in VISION_TYPES:
                triggers.append(f"Vision : posture {rs.get('posture')}, activité {rs.get('activity')}, zone {rs.get('zone')}, expression {rs.get('expression')}")
            if pred:
                triggers += json.loads(pred.factors_json or "[]")[:6]
            faults = rs.get("deviceFaults") or {}
            if r.type == "equipment_fault" and faults:
                triggers += [f"{f.get('name')} : {f.get('label')}" for f in faults.values()]
            vit = _vitals_line(rs.get("vitals") or {})
            if vit:
                triggers.append("Constantes au moment de la lecture : " + " · ".join(vit))
            if r.news2 is not None:
                triggers.append(f"NEWS2 à l'ouverture : {r.news2}")
        return {"key": f"{kind}:{r.id}", "kind": kind, "ref": str(r.id), "title": r.title, "confidence": conf, "triggers": triggers}
    if kind == "hypothesis":
        h = session.get(DiagnosticHypothesis, int(ref)) if ref and str(ref).isdigit() else None
        if h is None and patient and label:
            p = _patient(session, patient)
            h = session.exec(select(DiagnosticHypothesis).where(DiagnosticHypothesis.patient_pk == p.id, DiagnosticHypothesis.label == label).order_by(DiagnosticHypothesis.id.desc())).first()
        if not h:
            raise HTTPException(404, "Hypothèse introuvable")
        pros, cons = json.loads(h.pros_json or "[]"), json.loads(h.cons_json or "[]")
        return {"key": f"hypothesis:{h.id}", "kind": kind, "ref": str(h.id), "title": h.label, "confidence": hypothesis_confidence(h.probability, pros, cons),
                "triggers": [f"Pour : {x}" for x in pros[:6]] + [f"Contre : {x}" for x in cons[:4]]}
    if kind == "prediction":
        pid, _, key = (ref or "").partition(":")
        p = _patient(session, pid or patient or "")
        if not key and label:
            from ..clinical.prediction import LABELS

            key = next((k for k, v in LABELS.items() if v == label or label.startswith(v) or v.startswith(label)), "")
        row = session.exec(select(Prediction).where(Prediction.patient_pk == p.id, Prediction.key == key).order_by(Prediction.id.desc())).first()
        if not row:
            raise HTTPException(404, "Prédiction introuvable")
        factors = json.loads(row.factors_json or "[]")
        window = json.loads(row.window_json or "null") if row.window_json else None
        return {"key": f"prediction:{p.patient_id}:{key}", "kind": kind, "ref": f"{p.patient_id}:{key}", "title": f"Prédiction — {key}", "confidence": prediction_confidence(row.confidence, factors),
                "triggers": [f"Risque {row.risk}/100 ({row.level})" + (f", fenêtre estimée {window.get('text')}" if isinstance(window, dict) and window.get("text") else "")] + factors[:8]}
    # psych
    p = _patient(session, ref or patient or "")
    row = session.exec(select(PsychScore).where(PsychScore.patient_pk == p.id).order_by(PsychScore.id.desc())).first()
    if not row:
        raise HTTPException(404, "Score psychologique introuvable")
    d = json.loads(row.detail_json or "{}")
    triggers = [f"Bien-être {row.wellbeing}/100 (niveau de risque {row.level})"]
    for k, name in (("depression", "Dépression"), ("anxiety", "Anxiété"), ("insomnia", "Insomnie")):
        for f in (d.get(k) or {}).get("factors", [])[:2]:
            triggers.append(f"{name} : {f}")
    return {"key": f"psych:{p.patient_id}", "kind": kind, "ref": p.patient_id, "title": "Score de bien-être psychologique", "confidence": psych_confidence(d.get("inputs") or {}), "triggers": triggers}


def last_decision(session: Session, kind: str, ref: str) -> Optional[dict[str, Any]]:
    row = session.exec(select(AuditLog).where(AuditLog.entity == f"recommendation:{kind}", AuditLog.entity_id == str(ref), AuditLog.action.in_(("ai_validate", "ai_reject"))).order_by(AuditLog.id.desc())).first()
    if not row:
        return None
    try:
        details = json.loads(row.details or "{}")
    except ValueError:
        details = {}
    ts = row.ts if row.ts.tzinfo else row.ts.replace(tzinfo=timezone.utc)
    return {"decision": "validated" if row.action == "ai_validate" else "rejected", "by": row.user, "role": row.role, "at": ts.isoformat(), "reason": details.get("reason", "")}


# ── API ──────────────────────────────────────────────────────────────────────
@router.get("/config")
def config(user: authlib.CurrentUser = Depends(authlib.get_current_user)):
    return {"enabled": enabled(), "banner": BANNER, "can_decide": user.role in DECIDERS, "max_actions": 3}


@router.get("/explain")
def explain_api(kind: str, ref: Optional[str] = None, patient: Optional[str] = None, label: Optional[str] = None, session: Session = Depends(get_session),
                user: authlib.CurrentUser = Depends(authlib.can_view_clinical)):
    if not enabled():
        raise HTTPException(404, "SADM désactivé (SADM_ENABLED=0)")
    out = explain(session, kind, ref, patient, label)
    out.update(decision=last_decision(session, kind, out["ref"]), can_decide=user.role in DECIDERS, banner=BANNER,
               disclaimer="Indice calculé par une formule déterministe : il mesure la solidité des données, pas une probabilité clinique validée.")
    return out


class DecisionIn(BaseModel):
    kind: str
    ref: str
    decision: str  # validated | rejected
    reason: str = ""


@router.post("/decisions", status_code=201)
def decide(body: DecisionIn, request: Request, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.get_current_user)):
    """Validation ou rejet d'une recommandation par un soignant — tracé (qui, quand, quoi, IP), jamais automatique."""
    if not enabled():
        raise HTTPException(404, "SADM désactivé (SADM_ENABLED=0)")
    if user.role not in DECIDERS:
        raise HTTPException(403, "Seul un soignant peut valider ou rejeter une recommandation")
    if body.decision not in ("validated", "rejected"):
        raise HTTPException(400, "Décision attendue : validated ou rejected")
    info = explain(session, body.kind, body.ref)
    reason = re.sub(r"\s+", " ", body.reason).strip()[:300]
    ip = request.client.host if request.client else ""
    audit(session, user, "ai_validate" if body.decision == "validated" else "ai_reject", f"recommendation:{body.kind}", info["ref"],
          {"title": info["title"], "reason": reason, "confidence_pct": info["confidence"]["pct"], "triggers": info["triggers"][:5], "ip": ip})
    if body.kind in ("risk", "fever"):  # la décision apparaît aussi dans l'historique du risque
        r = session.get(Risk, int(info["ref"]))
        stamp = datetime.now().strftime("%H:%M:%S")
        r.notes = (r.notes + "\n" if r.notes else "") + f"{stamp} recommandation {'validée' if body.decision == 'validated' else 'rejetée'} par {user.username}" + (f" — {reason}" if reason else "")
    session.commit()
    return {"key": info["key"], "decision": last_decision(session, body.kind, info["ref"])}


@router.get("/decisions")
def decisions(limit: int = 50, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.can_view_clinical)):
    rows = session.exec(select(AuditLog).where(AuditLog.action.in_(("ai_validate", "ai_reject"))).order_by(AuditLog.id.desc()).limit(max(1, min(200, limit)))).all()
    return [{"id": r.id, "user": r.user, "role": r.role, "decision": "validated" if r.action == "ai_validate" else "rejected", "kind": r.entity.split(":", 1)[-1], "ref": r.entity_id,
             "at": (r.ts if r.ts.tzinfo else r.ts.replace(tzinfo=timezone.utc)).isoformat(), "details": json.loads(r.details or "{}")} for r in rows]


@router.get("/to-sign")
def to_sign(session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.get_current_user)):
    """Documents en attente de signature pour ce médecin (raccourci « 3 actions maximum » depuis la cloche)."""
    from ..models import Prescription, TreatmentOrder

    out: list[dict[str, Any]] = []
    if user.role in authlib.DOCTORS:
        for pr in session.exec(select(Prescription).where(Prescription.status == "draft").order_by(Prescription.id.desc()).limit(10)).all():
            out.append({"type": "prescription", "id": pr.id, "label": f"Ordonnance #{pr.id}", "sign_url": f"/api/prescriptions/{pr.id}/sign", "view": "prescription"})
        for o in session.exec(select(TreatmentOrder).where(TreatmentOrder.status == "draft").order_by(TreatmentOrder.id.desc()).limit(10)).all():
            out.append({"type": "treatment_order", "id": o.id, "label": f"Ordonnance de traitement #{o.id}", "sign_url": f"/api/treatment-orders/{o.id}/sign", "view": "treatment"})
    return out

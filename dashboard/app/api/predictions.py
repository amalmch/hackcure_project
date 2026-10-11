"""Prédictions de crise (V2, étape 8) : risque et fenêtre de temps par patient et par condition. Estimation de prototype, non validée cliniquement."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from .. import auth as authlib
from ..agents import manager as agent_manager
from ..agents.prediction import DISCLAIMER, prediction_out
from ..clinical.prediction import LABELS
from ..db import get_session
from ..models import Admission, Patient, Prediction

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


def _current(session: Session, adm: Admission) -> list[dict[str, Any]]:
    """Dernière prédiction de chaque condition (mémoire de l'agent, sinon dernière ligne enregistrée)."""
    agent = agent_manager.get("PredictionAgent")
    live = dict(agent.current.get(adm.room_code, {})) if agent else {}
    out = []
    for key in LABELS:
        row = session.exec(select(Prediction).where(Prediction.admission_id == adm.id, Prediction.key == key).order_by(Prediction.id.desc())).first()
        base = prediction_out(row) if row else {"key": key, "label": LABELS[key], "risk": 0, "level": "faible", "window": None, "confidence": "faible", "factors": [], "ai": None, "ts": None}
        if key in live:
            base.update({k: live[key][k] for k in ("risk", "level", "window", "confidence", "factors")})
        out.append(base)
    return out


@router.get("")
def predictions(session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_predictions"))):
    rows = []
    for adm in session.exec(select(Admission).where(Admission.discharged_at.is_(None)).order_by(Admission.room_code)).all():
        p = session.get(Patient, adm.patient_id)
        preds = _current(session, adm)
        rows.append({"patient_id": p.patient_id, "name": p.full_name, "room": adm.room_code, "predictions": preds, "max_risk": max(x["risk"] for x in preds)})
    return {"disclaimer": DISCLAIMER, "patients": rows}


@router.get("/{patient_id}")
def prediction_detail(patient_id: str, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.require("view_predictions"))):
    p = session.exec(select(Patient).where(Patient.patient_id == patient_id)).first()
    if not p:
        raise HTTPException(404, "Patient introuvable")
    adm = session.exec(select(Admission).where(Admission.patient_id == p.id, Admission.discharged_at.is_(None))).first()
    history = [prediction_out(r) for r in session.exec(select(Prediction).where(Prediction.patient_pk == p.id).order_by(Prediction.id.desc()).limit(300)).all()]
    return {"patient_id": patient_id, "name": p.full_name, "room": adm.room_code if adm else None, "predictions": _current(session, adm) if adm else [], "disclaimer": DISCLAIMER,
            "history": {key: [{"ts": h["ts"], "risk": h["risk"], "level": h["level"], "window": h["window"]} for h in reversed(history) if h["key"] == key] for key in LABELS}}

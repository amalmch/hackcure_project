"""Parcours fièvre (V2, étape 3) : checklist d'examen clinique, validation du bilan biologique par le médecin, résultats."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import auth as authlib
from ..agents import fever as fever_agent
from ..agents import manager as agent_manager
from ..audit import audit
from ..db import get_session
from ..models import FeverPathway

router = APIRouter(prefix="/api/fever", tags=["fever"])


class CheckIn(BaseModel):
    key: str
    done: bool = True
    note: Optional[str] = None


class LabsIn(BaseModel):
    codes: Optional[list[str]] = None


@router.get("")
def list_pathways(room: Optional[str] = None, risk_id: Optional[int] = None, open_only: bool = False, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.can_view_clinical)):
    q = select(FeverPathway).order_by(FeverPathway.id.desc())
    if room:
        q = q.where(FeverPathway.room_code == room)
    if risk_id:
        q = q.where(FeverPathway.risk_id == risk_id)
    if open_only:
        q = q.where(FeverPathway.stage != "resolved")
    return [fever_agent.pathway_dict(p) for p in session.exec(q.limit(50)).all()]


@router.get("/{pid}")
def get_pathway(pid: int, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.can_view_clinical)):
    p = session.get(FeverPathway, pid)
    if not p:
        raise HTTPException(404, "Parcours introuvable")
    return fever_agent.pathway_dict(p)


@router.post("/{pid}/checklist")
async def check(pid: int, body: CheckIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_manage_risks)):
    try:
        d = fever_agent.set_check(pid, body.key, body.done, body.note, user.username)
    except KeyError:
        raise HTTPException(404, "Parcours introuvable")
    except ValueError:
        raise HTTPException(400, "Point de checklist inconnu")
    audit(session, user, "fever_check", "fever_pathway", pid, {"key": body.key, "done": body.done})
    session.commit()
    await fever_agent.broadcast(d)
    return d


@router.post("/{pid}/exam-done")
async def exam_done(pid: int, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_write_medical_docs)):
    """Le médecin déclare le bilan clinique terminé : le bilan biologique proposé peut alors être validé."""
    try:
        d = fever_agent.finish_exam(pid, user.username)
    except KeyError:
        raise HTTPException(404, "Parcours introuvable")
    audit(session, user, "fever_exam_done", "fever_pathway", pid)
    session.commit()
    await fever_agent.broadcast(d)
    agent = agent_manager.get("FeverAgent")
    if agent:
        done = sum(1 for c in d["checklist"] if c["done"])
        await agent.log(d["room"], input=f"bilan clinique terminé par {user.username} ({done}/{len(d['checklist'])} points cochés)", reasoning="Étape 1 validée par le médecin. Le bilan biologique proposé attend sa validation.",
                        output="étape 2/4 : bilan biologique à valider", risk_id=d["risk_id"])
    return d


@router.post("/{pid}/labs/validate")
async def validate_labs(pid: int, body: LabsIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_write_medical_docs)):
    try:
        d = fever_agent.validate_labs(pid, body.codes, user.username)
    except KeyError:
        raise HTTPException(404, "Parcours introuvable")
    except PermissionError as exc:
        raise HTTPException(409, str(exc))
    audit(session, user, "fever_labs_validated", "fever_pathway", pid, {"codes": [x["code"] for x in d["labs"] if x.get("selected")]})
    session.commit()
    await fever_agent.broadcast(d)
    agent = agent_manager.get("FeverAgent")
    if agent:
        await agent.log(d["room"], input=f"bilan biologique validé par {user.username} : {', '.join(x['label'] for x in d['labs'] if x.get('selected'))}",
                        reasoning="Étape 2 validée par le médecin : prélèvements demandés, résultats attendus. Le bilan clinique et le bilan biologique étant lancés, l'EnvironmentAgent peut maintenant ajuster la chambre — mesure de confort, pas un traitement.",
                        output="étape 3/4 : confort de la chambre", risk_id=d["risk_id"])
    # 3) ensuite seulement : confort
    env = agent_manager.get("EnvironmentAgent")
    if env is not None:
        note = await env.comfort_for_fever(d["room"])
        d = fever_agent.set_comfort_note(pid, note)
        await fever_agent.broadcast(d)
    return d

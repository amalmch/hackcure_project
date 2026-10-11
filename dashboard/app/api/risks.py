"""Centre de détection / centre de commande : risques, plans d'action, étapes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, func, select

from .. import auth as authlib
from ..audit import audit
from ..bus import bus
from ..db import get_session
from ..models import ActionPlan, ActionStep, AgentLog, Notification, Risk
from ..risks import OPEN_STATUSES, SEVERITY_ORDER, refresh_room_level, risk_dict
from ..ws import manager

router = APIRouter(prefix="/api/risks", tags=["risks"])


class RiskPatch(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    severity: Optional[str] = None


class StepIn(BaseModel):
    text: str


class StepPatch(BaseModel):
    done: bool


@router.get("")
def list_risks(status: Optional[str] = None, room: Optional[str] = None, severity: Optional[str] = None, open_only: bool = False, limit: int = Query(100, le=500),
               session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.can_view_clinical)):
    q = select(Risk)
    if status:
        q = q.where(Risk.status.in_(status.split(",")))
    if open_only:
        q = q.where(Risk.status.in_(OPEN_STATUSES))
    if room:
        q = q.where(Risk.room_code == room)
    if severity:
        q = q.where(Risk.severity.in_(severity.split(",")))
    rows = session.exec(q.order_by(Risk.detected_at.desc()).limit(limit)).all()
    rows.sort(key=lambda r: (r.status in OPEN_STATUSES, SEVERITY_ORDER.get(r.severity, 0), r.detected_at), reverse=True)
    return [risk_dict(session, r, with_plan=True) for r in rows]


@router.get("/summary")
def summary(session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.can_view_clinical)):
    rows = session.exec(select(Risk.status, Risk.severity, Risk.room_code, func.count(Risk.id)).group_by(Risk.status, Risk.severity, Risk.room_code)).all()
    out = {"by_status": {}, "by_severity_open": {}, "by_room_open": {}}
    for st, sev, room, n in rows:
        out["by_status"][st] = out["by_status"].get(st, 0) + n
        if st in OPEN_STATUSES:
            out["by_severity_open"][sev] = out["by_severity_open"].get(sev, 0) + n
            out["by_room_open"][room] = out["by_room_open"].get(room, 0) + n
    return out


@router.get("/{risk_id}")
def get_risk(risk_id: int, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.can_view_clinical)):
    r = session.get(Risk, risk_id)
    if not r:
        raise HTTPException(404, "Risque introuvable")
    d = risk_dict(session, r)
    d["notifications"] = [{"id": n.id, "level": n.level, "title": n.title, "target_role": n.target_role, "channels": n.channels, "telegram_sent": n.telegram_sent, "created_at": n.created_at} for n in session.exec(select(Notification).where(Notification.risk_id == risk_id).order_by(Notification.created_at)).all()]
    d["logs"] = [{"id": l.id, "agent": l.agent, "input": l.input, "reasoning": l.reasoning, "output": l.output, "status": l.status, "ts": l.ts} for l in session.exec(select(AgentLog).where(AgentLog.risk_id == risk_id).order_by(AgentLog.ts)).all()]
    return d


@router.patch("/{risk_id}")
async def patch_risk(risk_id: int, body: RiskPatch, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_manage_risks)):
    r = session.get(Risk, risk_id)
    if not r:
        raise HTTPException(404, "Risque introuvable")
    now = datetime.now(timezone.utc)
    if body.status:
        if body.status not in ("open", "in_progress", "resolved", "escalated"):
            raise HTTPException(400, "Statut inconnu")
        r.status = body.status
        if body.status == "in_progress":
            r.acknowledged_at = r.acknowledged_at or now
        elif body.status == "resolved":
            r.resolved_at, r.resolved_by = now, f"{user.username} (manuel, non vérifié)"
        elif body.status == "escalated":
            r.escalated_at = now
    if body.severity:
        if body.severity not in SEVERITY_ORDER:
            raise HTTPException(400, "Sévérité inconnue")
        r.severity = body.severity
    if body.notes is not None:
        r.notes = (r.notes + "\n" if r.notes else "") + f"{now.strftime('%H:%M:%S')} {user.username} : {body.notes}"
    audit(session, user, "update", "risk", risk_id, body.model_dump(exclude_none=True))
    session.commit()
    session.refresh(r)
    refresh_room_level(session, r.room_code)
    payload = risk_dict(session, r)
    await manager.broadcast({"type": "risk", "event": "updated", "risk": payload})
    return payload


class ResolveIn(BaseModel):
    verified: bool = False
    justification: str = ""
    source: str = "n8n:risk-verify"


@router.post("/{risk_id}/resolve")
async def request_resolution(risk_id: int, body: Optional[ResolveIn] = None, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_manage_risks)):
    """« Marquer résolu » : passe en cours et déclenche la vérification différée du FollowUpAgent.
    Avec `{"verified": true, "justification": ...}` (n8n `risk-verify`) : résolution vérifiée immédiate."""
    r = session.get(Risk, risk_id)
    if not r:
        raise HTTPException(404, "Risque introuvable")
    if r.status == "resolved":
        return risk_dict(session, r)
    now = datetime.now(timezone.utc)
    if body and body.verified:
        r.status = "resolved"
        r.resolved_at = now
        r.verified_at = now
        r.resolved_by = f"{body.source} (vérifié) — {body.justification[:160]}" if body.justification else f"{body.source} (vérifié)"
        audit(session, user, "resolve_verified", "risk", risk_id, {"source": body.source})
        session.commit()
        session.refresh(r)
        refresh_room_level(session, r.room_code)
        payload = risk_dict(session, r)
        await manager.broadcast({"type": "risk", "event": "resolved", "risk": payload})
        from .. import n8n
        from ..notify import notify

        n8n.release_soon([risk_id], "risque résolu")
        await bus.publish("internal/risk/resolved", {"risk_id": risk_id, "room": r.room_code, "type": r.type, "by": body.source, "detail": body.justification})

        await notify("info", f"Résolu — {r.title}", body.justification or "Vérifié par n8n.", room=r.room_code, risk_id=risk_id, target_role="nurse", telegram=False)
        return payload
    r.status = "in_progress"
    r.acknowledged_at = r.acknowledged_at or now
    r.notes = (r.notes + "\n" if r.notes else "") + f"{now.strftime('%H:%M:%S')} résolution demandée par {user.username} (vérification FollowUpAgent)"
    audit(session, user, "resolve_request", "risk", risk_id)
    session.commit()
    session.refresh(r)
    refresh_room_level(session, r.room_code)
    payload = risk_dict(session, r)
    await manager.broadcast({"type": "risk", "event": "updated", "risk": payload})
    await bus.publish("internal/risk/resolve_request", {"risk_id": risk_id, "room": r.room_code, "by": user.username})
    return payload


@router.post("/{risk_id}/steps", status_code=201)
async def add_step(risk_id: int, body: StepIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_manage_risks)):
    r = session.get(Risk, risk_id)
    if not r:
        raise HTTPException(404, "Risque introuvable")
    plan = session.exec(select(ActionPlan).where(ActionPlan.risk_id == risk_id).order_by(ActionPlan.id.desc())).first()
    if not plan:
        plan = ActionPlan(risk_id=risk_id, summary="Plan manuel", created_by=user.username, llm_provider="manual")
        session.add(plan)
        session.flush()
    n = session.exec(select(func.count(ActionStep.id)).where(ActionStep.plan_id == plan.id)).one()
    st = ActionStep(plan_id=plan.id, order=n + 1, text=body.text.strip(), suggested_by_ai=False)
    session.add(st)
    audit(session, user, "create", "action_step", None, {"risk_id": risk_id, "text": body.text})
    session.commit()
    payload = risk_dict(session, r)
    await manager.broadcast({"type": "risk", "event": "updated", "risk": payload})
    return payload


@router.patch("/{risk_id}/steps/{step_id}")
async def toggle_step(risk_id: int, step_id: int, body: StepPatch, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_manage_risks)):
    r = session.get(Risk, risk_id)
    st = session.get(ActionStep, step_id)
    if not r or not st:
        raise HTTPException(404, "Étape introuvable")
    st.done = body.done
    st.done_by = user.username if body.done else None
    st.done_at = datetime.now(timezone.utc) if body.done else None
    if r.status == "open" and body.done:
        r.status = "in_progress"
        r.acknowledged_at = r.acknowledged_at or datetime.now(timezone.utc)
    audit(session, user, "update", "action_step", step_id, {"risk_id": risk_id, "done": body.done})
    session.commit()
    session.refresh(r)
    refresh_room_level(session, r.room_code)
    payload = risk_dict(session, r)
    await manager.broadcast({"type": "risk", "event": "updated", "risk": payload})
    return payload

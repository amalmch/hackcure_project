"""
Endpoints appelés par n8n (jeton de service `PLATFORM_SERVICE_TOKEN`, rôle owner) et par l'interface
pour l'orchestration : plan d'action, escalade, résolution vérifiée, risque persistant, acquittement,
rapport de garde, journal des exécutions n8n, déclencheurs manuels.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import auth as authlib, n8n
from ..audit import audit
from ..db import get_session
from ..ingest import handler
from ..models import ActionPlan, ActionStep, AgentLog, Risk, ShiftReport
from ..notify import notify
from ..risks import refresh_room_level, risk_dict
from ..ws import manager

router = APIRouter(tags=["n8n"])


class PlanIn(BaseModel):
    explanation: str = ""
    steps: list[Any] = []
    source: str = "n8n:risk-triage"
    llm_provider: str = "anthropic (n8n)"
    fallback: bool = False
    resume_url: Optional[str] = None
    severity_comment: Optional[str] = None


class ReasonIn(BaseModel):
    reason: str = ""
    justification: str = ""
    source: str = "n8n"


class ShiftIn(BaseModel):
    content: str
    hours: int = 12
    shift_start: Optional[datetime] = None
    shift_end: Optional[datetime] = None
    source: str = "n8n:shift-report"
    fallback: bool = False


class AgentLogIn(BaseModel):
    agent: str = "n8n"
    room: Optional[str] = None
    input: str = ""
    reasoning: str = ""
    output: str = ""
    status: str = "ok"
    risk_id: Optional[int] = None
    duration_ms: int = 0


def _risk(session: Session, risk_id: int) -> Risk:
    r = session.get(Risk, risk_id)
    if not r:
        raise HTTPException(404, "Risque introuvable")
    return r


async def _broadcast(session: Session, r: Risk, event: str) -> dict:
    payload = risk_dict(session, r)
    await manager.broadcast({"type": "risk", "event": event, "risk": payload})
    return payload


# ─── Appelés par n8n ─────────────────────────────────────────────────────────
@router.post("/api/risks/{risk_id}/plan")
async def set_plan(risk_id: int, body: PlanIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_manage_risks)):
    r = _risk(session, risk_id)
    steps = [str(s.get("text") if isinstance(s, dict) else s).strip() for s in body.steps]
    steps = [s for s in steps if s][:6]
    if body.explanation.strip():
        r.explanation = body.explanation.strip()
    if body.resume_url:
        r.n8n_resume_url = body.resume_url
    r.handled_by = "n8n"
    provider = body.llm_provider if not body.fallback else "secours (LLM indisponible) via n8n"
    if steps:
        plan = ActionPlan(risk_id=risk_id, summary=f"Plan d'action ({body.source})", created_by=body.source, llm_provider=provider)
        session.add(plan)
        session.flush()
        for i, text in enumerate(steps, start=1):
            session.add(ActionStep(plan_id=plan.id, order=i, text=text, suggested_by_ai=True))
    audit(session, user, "plan", "risk", risk_id, {"source": body.source, "steps": len(steps), "fallback": body.fallback})
    session.commit()
    session.refresh(r)
    return await _broadcast(session, r, "updated")


@router.post("/api/risks/{risk_id}/escalate")
async def escalate(risk_id: int, body: ReasonIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_manage_risks)):
    r = _risk(session, risk_id)
    if body.source.startswith("n8n"):  # l'attente du workflow est terminée : l'URL de reprise est périmée
        r.n8n_resume_url = None
    if r.status in ("resolved", "in_progress"):  # déjà pris en charge (acquittement ou personnel dans la chambre)
        session.commit()
        session.refresh(r)
        return {**risk_dict(session, r), "escalated": False}
    now = datetime.now(timezone.utc)
    r.status = "escalated"
    r.escalated_at = r.escalated_at or now
    r.notes = (r.notes + "\n" if r.notes else "") + f"{now.strftime('%H:%M:%S')} escalade ({body.source}) : {body.reason or 'sans acquittement dans le délai'}"
    audit(session, user, "escalate", "risk", risk_id, {"source": body.source})
    session.commit()
    session.refresh(r)
    refresh_room_level(session, r.room_code)
    payload = await _broadcast(session, r, "escalated")
    await notify("critical" if r.severity == "critical" else "warning", f"Escalade — {r.title}", body.reason or "Aucune prise en charge dans le délai. Médecin de garde sollicité.", room=r.room_code, risk_id=risk_id, target_role="duty_doctor", telegram=False)
    return {**payload, "escalated": True}


@router.post("/api/risks/{risk_id}/persistent")
async def persistent(risk_id: int, body: ReasonIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_manage_risks)):
    r = _risk(session, risk_id)
    now = datetime.now(timezone.utc)
    r.status = "escalated"
    r.escalated_at = now
    r.notes = (r.notes + "\n" if r.notes else "") + f"{now.strftime('%H:%M:%S')} risque persistant après visite ({body.source}) : {body.justification or body.reason}"
    audit(session, user, "persistent", "risk", risk_id, {"source": body.source})
    session.commit()
    session.refresh(r)
    refresh_room_level(session, r.room_code)
    payload = await _broadcast(session, r, "escalated")
    await notify("critical" if r.severity == "critical" else "warning", f"Risque persistant — {r.title}", body.justification or body.reason, room=r.room_code, risk_id=risk_id, target_role="duty_doctor", telegram=False)
    return payload


# ─── Acquittement « Je prends en charge » (interface) ────────────────────────
@router.post("/api/risks/{risk_id}/ack")
async def acknowledge(risk_id: int, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_manage_risks)):
    r = _risk(session, risk_id)
    now = datetime.now(timezone.utc)
    if r.status in ("open", "escalated"):
        r.status = "in_progress"
    r.acknowledged_at = r.acknowledged_at or now
    r.notes = (r.notes + "\n" if r.notes else "") + f"{now.strftime('%H:%M:%S')} pris en charge par {user.username}"
    resume_url, room = r.n8n_resume_url, r.room_code
    audit(session, user, "ack", "risk", risk_id)
    session.commit()
    session.refresh(r)
    refresh_room_level(session, room)
    payload = await _broadcast(session, r, "in_progress")
    n8n_ok = None
    if r.handled_by == "n8n" and n8n.enabled():
        ack = {"risk_id": risk_id, "room": room, "acknowledged": True, "by": user.username, "ts": now.isoformat()}
        n8n_ok = await n8n.resume(resume_url, ack) if resume_url else False
        if n8n_ok:  # l'URL de reprise ne sert qu'une fois (session dédiée : celle de la requête a déjà lu)
            from ..db import session_scope

            with session_scope() as s2:
                s2.get(Risk, risk_id).n8n_resume_url = None
    payload["n8n_resumed"] = n8n_ok
    # simulation : un soignant virtuel intervient (scénario de résolution du type de risque) ; en vision réelle, rien n'est simulé
    from .. import resolutions
    from ..agents import manager as agent_manager

    res = resolutions.start_for(room, r.type, by_role=user.role)
    payload["resolution"] = res
    agent = agent_manager.get("FollowUpAgent")
    if agent is not None:
        await agent.log(room, input=f"« Je prends en charge » sur le risque #{risk_id} ({r.type}) par {user.username}",
                        reasoning=(f"Chambre simulée : intervention « {res['scenario']} » lancée — {res['role_label']} dans la chambre pendant ~{res['duration']:.0f} s. {res['description']}" if res
                                   else "Chambre en vision réelle (ou simulateur arrêté) : aucune intervention simulée, c'est la présence détectée d'un soignant qui compte.")
                                  + " La sortie du soignant déclenchera la revérification déterministe.",
                        output=f"risque #{risk_id} en cours" + (f" — {res['role_label']} en route" if res else ""), risk_id=risk_id)
    return payload


# ─── Rapport de garde déposé par n8n ─────────────────────────────────────────
@router.post("/api/shift-reports", status_code=201)
async def create_shift_report(body: ShiftIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.require("edit_shift_report"))):
    end = body.shift_end or datetime.now(timezone.utc)
    start = body.shift_start or (end - timedelta(hours=max(1, min(body.hours, 48))))
    rep = ShiftReport(shift_start=start, shift_end=end, author=body.source + (" — secours" if body.fallback else ""), content=body.content, status="draft")
    session.add(rep)
    session.flush()
    audit(session, user, "create", "shift_report", rep.id, {"source": body.source})
    session.commit()
    out = {"id": rep.id, "shift_start": rep.shift_start, "shift_end": rep.shift_end, "author": rep.author, "status": rep.status, "created_at": rep.created_at, "content": rep.content, "print_url": f"/print/shift/{rep.id}"}
    await manager.broadcast({"type": "shift_report", "event": "created", "id": rep.id, "author": rep.author, "source": body.source})
    return out


# ─── Journal des exécutions n8n → panneau Agents ─────────────────────────────
@router.post("/api/agents/log", status_code=201)
async def n8n_log(body: AgentLogIn, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.get_current_user)):
    agent = body.agent if body.agent.startswith("n8n") else f"n8n:{body.agent}"
    row = AgentLog(agent=agent, room_code=body.room, input=body.input[:2000], reasoning=body.reasoning[:4000], output=body.output[:4000], status=body.status, risk_id=body.risk_id, duration_ms=body.duration_ms)
    session.add(row)
    session.commit()
    session.refresh(row)
    await manager.broadcast({"type": "agent_log", "id": row.id, "agent": agent, "room": body.room, "input": body.input[:600], "reasoning": body.reasoning[:1200], "output": body.output[:1200], "status": body.status, "risk_id": body.risk_id, "duration_ms": body.duration_ms, "ts": row.ts.isoformat()})
    await manager.broadcast({"type": "agent_status", "agent": agent, "status": "idle", "last_run": row.ts.isoformat(), "runs": None, "errors": None})
    return {"id": row.id}


# ─── Résultat d'un workflow d'agent V2 (raisonnement LLM) ────────────────────
class AgentResultIn(BaseModel):
    workflow: str
    ref: str
    result: Optional[dict[str, Any]] = None
    context: Optional[dict[str, Any]] = None
    fallback: bool = False
    error: Optional[str] = None
    model: Optional[str] = None
    anthropic_id: Optional[str] = None
    room: Optional[str] = None
    risk_id: Optional[int] = None
    duration_ms: int = 0


@router.post("/api/agents/result")
async def agent_result(body: AgentResultIn, _: authlib.CurrentUser = Depends(authlib.can_manage_risks)):
    """Appelé par n8n à la fin du raisonnement d'un agent : le résultat est remis au gestionnaire Python de l'agent."""
    from .. import orchestration
    from ..agents.specs import validate

    result = body.result
    error = body.error or (validate(body.workflow, result) if body.workflow in orchestration._handlers else None)
    meta = {"source": "n8n", "fallback": body.fallback or error is not None, "error": error, "provider": f"anthropic {body.model or n8n.settings.llm_model} (n8n)", "anthropic_id": body.anthropic_id,
            "room": body.room, "risk_id": body.risk_id, "duration_ms": body.duration_ms, "context": body.context}
    try:
        return await orchestration.deliver(body.workflow, body.ref, None if meta["fallback"] else result, meta)
    except KeyError:
        raise HTTPException(404, f"Workflow d'agent inconnu : {body.workflow}")


# ─── Statut et déclencheurs manuels ──────────────────────────────────────────
@router.get("/api/n8n/status")
async def n8n_status(_: authlib.CurrentUser = Depends(authlib.get_current_user)):
    await n8n.probe()
    return n8n.info()


@router.post("/api/n8n/trigger/{name}")
async def trigger(name: str, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.get_current_user)):
    """Déclenche un workflow depuis l'interface : shift-report, pharmacy-alerts."""
    perms = {"shift-report": "edit_shift_report", "pharmacy-alerts": "view_pharmacy"}
    if name not in perms:
        raise HTTPException(404, "Webhook inconnu")
    if not user.can(perms[name]):
        raise HTTPException(403, "Permission refusée")
    if not n8n.enabled():
        raise HTTPException(503, "n8n désactivé (N8N_ENABLED=0)")
    payload = {"event": name, "triggered_by": user.username, "platform_url": n8n.settings.platform_url, "llm_model": n8n.settings.llm_model,
               "telegram_chat_id": n8n.settings.telegram_chat_id, "ts": datetime.now(timezone.utc).isoformat()}
    if name == "shift-report":
        payload["hours"] = 12
    ok = await n8n.send_event(name, payload)
    if not ok:
        raise HTTPException(503, "n8n injoignable ou workflow inactif : utiliser le repli local")
    audit(session, user, "trigger", "n8n", name)
    session.commit()
    return {"status": "sent", "webhook": name}

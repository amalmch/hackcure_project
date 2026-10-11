"""Panneau Agents : statut des agents et journal (AgentLog)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlmodel import Session, select

from .. import auth as authlib, n8n
from ..agents import manager as agent_manager
from ..config import settings
from ..db import get_session
from ..models import AgentLog

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
def list_agents(session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.get_current_user)):
    # activité des workflows n8n (étapes reçues sur POST /api/agents/log) pour leurs cartes du panneau Agents
    rows = session.exec(select(AgentLog.agent, func.count(), func.max(AgentLog.ts)).where(AgentLog.agent.like("n8n:%")).group_by(AgentLog.agent)).all()
    workflows = {name: {"runs": runs, "last_run": last.isoformat() if hasattr(last, "isoformat") else last} for name, runs, last in rows}
    return {"agents": agent_manager.infos(), "llm_provider": settings.llm_provider, "llm_model": settings.llm_model, "enabled": settings.agents_enabled, "n8n": {**n8n.info(), "workflows": workflows}}


@router.get("/map")
def agents_map(_: authlib.CurrentUser = Depends(authlib.get_current_user)):
    """Carte des agents : quel agent, quel workflow n8n, quels déclencheurs."""
    from .. import orchestration
    from ..agents.specs import agent_map

    rows = agent_map()
    for r in rows:
        r["calls"] = orchestration.stats.get(r["workflow"], {})
    return {"n8n": n8n.info(), "rows": rows, "principle": "La détection temps réel et la sévérité restent dans le backend Python ; n8n orchestre le raisonnement LLM, les notifications, les escalades, les attentes et les comptes rendus. Repli local automatique si n8n est indisponible."}


@router.get("/logs")
def logs(agent: Optional[str] = None, room: Optional[str] = None, risk_id: Optional[int] = None, limit: int = Query(50, le=500), session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.get_current_user)):
    q = select(AgentLog)
    if agent:
        q = q.where(AgentLog.agent == agent)
    if room:
        q = q.where(AgentLog.room_code == room)
    if risk_id:
        q = q.where(AgentLog.risk_id == risk_id)
    rows = session.exec(q.order_by(AgentLog.ts.desc()).limit(limit)).all()
    return [{"id": l.id, "agent": l.agent, "room": l.room_code, "input": l.input, "reasoning": l.reasoning, "output": l.output, "status": l.status, "risk_id": l.risk_id, "duration_ms": l.duration_ms, "ts": l.ts} for l in rows]

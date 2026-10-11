"""
Orchestration LLM des agents V2 (étape 9).

Principe conservé : la détection et la sévérité sont déterministes dans le backend. Le **raisonnement LLM**
(explication, synthèse, justification, compte rendu) est délégué au workflow n8n de l'agent :

    ask(workflow, ref, context)
        ├─ n8n joignable  → POST /webhook/<workflow> ; n8n appelle Claude puis POST /api/agents/result
        └─ sinon (repli)  → même prompt exécuté ici (API Anthropic directe, ou réponse simulée), même gestionnaire

Le gestionnaire enregistré par l'agent (`@handler("fever-pathway")`) reçoit `(ref, result, meta)` et peut
renvoyer le texte d'un message Telegram (envoyé par n8n, ou par la plateforme en repli).
Les prompts vivent dans `agents/specs.py` : une seule source pour n8n (`n8n/build_workflows.py`) et pour le repli.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from .config import settings

logger = logging.getLogger("hackcure.orchestration")

DISCLAIMER = "Aide à la décision — validation médicale requise."
Handler = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[Optional[str]]]
_handlers: dict[str, Handler] = {}
_tasks: set[asyncio.Task] = set()
stats: dict[str, dict[str, int]] = {}


def handler(workflow: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _handlers[workflow] = fn
        return fn

    return deco


def _count(workflow: str, key: str) -> None:
    stats.setdefault(workflow, {"n8n": 0, "local": 0, "fallback": 0})[key] += 1


async def ask(workflow: str, ref: str, context: dict[str, Any], room: Optional[str] = None, risk_id: Optional[int] = None) -> str:
    """Demande le raisonnement LLM d'un agent. Renvoie le chemin pris : 'n8n' ou 'local' (résultat traité en tâche de fond)."""
    from . import n8n
    from .agents.specs import SPECS

    spec = SPECS[workflow]
    if n8n.enabled() and await n8n.probe():
        payload = {"event": workflow, "workflow": workflow, "ref": str(ref), "room": room, "risk_id": risk_id, "context": context,
                   "platform_url": settings.platform_url, "llm_model": settings.llm_model, "telegram_chat_id": settings.telegram_chat_id,
                   "ts": datetime.now(timezone.utc).isoformat()}
        if await n8n.send_event(spec["webhook"], payload):
            _count(workflow, "n8n")
            return "n8n"
    task = asyncio.create_task(_run_local(workflow, str(ref), context, room, risk_id), name=f"llm-{workflow}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return "local"


async def _run_local(workflow: str, ref: str, context: dict[str, Any], room: Optional[str], risk_id: Optional[int]) -> None:
    """Repli : même prompt que le workflow n8n, exécuté par la plateforme."""
    from .agents.llm import FALLBACK_LABEL, MockLlm, get_llm
    from .agents.specs import SPECS, build_prompt, validate

    spec = SPECS[workflow]
    t0 = time.time()
    llm = get_llm()
    result, fallback, error = None, False, None
    if isinstance(llm, MockLlm):
        result = spec["mock"](context)
    else:
        system, user = build_prompt(workflow, context)
        try:
            data = await llm.complete_json(system, user, max_tokens=spec.get("max_tokens", 8000))
            error = validate(workflow, data)
            result = data if error is None else None
        except Exception as exc:  # pragma: no cover - réseau
            error = exc.__class__.__name__
        if result is None:
            result, fallback = spec["mock"](context), True
    _count(workflow, "fallback" if fallback else "local")
    provider = "mock" if isinstance(llm, MockLlm) else (FALLBACK_LABEL if fallback else f"{llm.name} {settings.llm_model} (plateforme)")
    await deliver(workflow, ref, result, {"source": "local", "fallback": fallback, "error": error, "provider": provider, "room": room, "risk_id": risk_id,
                                           "duration_ms": int((time.time() - t0) * 1000)})


async def deliver(workflow: str, ref: str, result: Optional[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    """Remet le résultat au gestionnaire de l'agent, journalise l'exécution, renvoie le texte Telegram éventuel."""
    from .agents.specs import SPECS
    from .db import session_scope
    from .models import AgentLog
    from .ws import manager

    spec = SPECS.get(workflow)
    if spec is None or workflow not in _handlers:
        raise KeyError(workflow)
    if result is None:  # n8n n'a pas obtenu de JSON valide : réponse de secours déterministe
        result, meta = spec["mock"](meta.get("context") or {}), {**meta, "fallback": True}
    telegram_text = await _handlers[workflow](ref, result, meta)
    via_n8n = meta.get("source") == "n8n"
    agent = f"n8n:{workflow}" if via_n8n else spec["agent"]
    reasoning = ("RÉPONSE DE SECOURS (LLM indisponible" + (f" : {meta['error']}" if meta.get("error") else "") + "). " if meta.get("fallback") else "") + \
        f"{spec['title']} — {meta.get('provider') or 'n8n'}" + (f" (réponse {meta['anthropic_id']})" if meta.get("anthropic_id") else "") + ". " + DISCLAIMER
    out = json.dumps(result, ensure_ascii=False)[:600]
    with session_scope() as s:
        row = AgentLog(agent=agent, room_code=meta.get("room"), input=f"{spec['title']} ({ref})"[:2000], reasoning=reasoning[:4000], output=out, status="error" if meta.get("fallback") else "ok",
                       risk_id=meta.get("risk_id"), duration_ms=int(meta.get("duration_ms") or 0))
        s.add(row)
        s.flush()
        log = {"type": "agent_log", "id": row.id, "agent": agent, "room": row.room_code, "input": row.input, "reasoning": row.reasoning, "output": row.output, "status": row.status,
               "risk_id": row.risk_id, "duration_ms": row.duration_ms, "ts": row.ts.isoformat()}
    await manager.broadcast(log)
    if telegram_text and not via_n8n:
        from .notify.telegram import send_telegram

        try:
            await send_telegram(telegram_text)
        except Exception:
            logger.debug("Telegram (repli) non envoyé", exc_info=True)
    return {"ok": True, "telegram_text": telegram_text or "", "fallback": bool(meta.get("fallback"))}


async def drain(timeout: float = 5.0) -> None:
    """Attend la fin des raisonnements locaux en cours (tests)."""
    if _tasks:
        await asyncio.wait(list(_tasks), timeout=timeout)

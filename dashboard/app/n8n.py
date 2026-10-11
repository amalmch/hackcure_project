"""
Client n8n : la plateforme DÉTECTE, n8n ORCHESTRE la réponse.

- `send_event(name, payload)` : `POST {N8N_BASE_URL}/webhook/{name}` avec `X-Hospital-Secret`, 3 tentatives,
  asynchrone ; renvoie True si n8n a accepté l'événement (sinon l'appelant applique le repli local).
- `status()` : `online | offline | disabled` (sondé toutes les 20 s via /healthz) — affiché dans l'interface.
- `resume(url, payload)` : reprise d'un nœud Wait (acquittement « Je prends en charge »).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import httpx

from .config import settings

logger = logging.getLogger("hackcure.n8n")

_last_probe = 0.0
_online = False
_last_error: Optional[str] = None
stats = {"sent": 0, "failed": 0, "fallbacks": 0}


def enabled() -> bool:
    return bool(settings.n8n_enabled and settings.n8n_base_url)


def headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if settings.n8n_webhook_secret:
        h["X-Hospital-Secret"] = settings.n8n_webhook_secret
    return h


async def probe(force: bool = False) -> bool:
    """Vérifie /healthz (cache 20 s)."""
    global _last_probe, _online, _last_error
    if not enabled():
        _online = False
        return False
    now = time.time()
    if not force and now - _last_probe < 20:
        return _online
    _last_probe = now
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.n8n_base_url}/healthz")
            _online = r.status_code == 200
            _last_error = None if _online else f"HTTP {r.status_code}"
    except Exception as exc:
        _online = False
        _last_error = exc.__class__.__name__
    return _online


def status() -> str:
    if not enabled():
        return "disabled"
    return "online" if _online else "offline"


def info() -> dict[str, Any]:
    return {"enabled": enabled(), "status": status(), "base_url": settings.n8n_base_url if enabled() else None, "last_error": _last_error, **stats}


async def send_event(name: str, payload: dict[str, Any], attempts: int = 3) -> bool:
    """Envoie un événement au webhook n8n `name`. 3 tentatives ; False ⇒ repli local."""
    from . import privacy

    payload = privacy.outbound("n8n", payload)  # V3 : webhooks pseudonymisés
    if not enabled():
        return False
    url = f"{settings.n8n_base_url}/webhook/{name}"
    delay = 0.5
    for i in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.post(url, json=payload, headers=headers())
            if r.status_code < 300:
                stats["sent"] += 1
                _mark(True)
                return True
            logger.warning("n8n %s : HTTP %s (%s) tentative %d/%d", name, r.status_code, r.text[:120], i, attempts)
            if r.status_code == 404:  # workflow non activé : inutile d'insister
                break
        except Exception as exc:
            logger.warning("n8n %s : %s tentative %d/%d", name, exc.__class__.__name__, i, attempts)
        await asyncio.sleep(delay)
        delay *= 2
    stats["failed"] += 1
    stats["fallbacks"] += 1
    _mark(False)
    return False


async def resume(resume_url: str, payload: dict[str, Any]) -> bool:
    """Reprend un nœud Wait (URL `webhook-waiting/...`)."""
    from . import privacy

    payload = privacy.outbound("n8n", payload)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(resume_url, json=payload, headers=headers())
        ok = r.status_code < 300
        if not ok:
            logger.warning("n8n resume : HTTP %s %s", r.status_code, r.text[:120])
        return ok
    except Exception as exc:
        logger.warning("n8n resume : %s", exc.__class__.__name__)
        return False


async def release(risk_ids: list[int], reason: str, acknowledged: bool = False) -> None:
    """Lève l'attente d'acquittement de risk-triage pour des risques pris en charge ou résolus par un autre chemin
    (personnel entré dans la chambre, résolution vérifiée, levée automatique) : l'exécution n8n se termine au lieu
    de rester en attente jusqu'au délai d'escalade."""
    if not enabled() or not risk_ids:
        return
    from .db import session_scope
    from .models import Risk

    todo: list[tuple[int, str, str]] = []
    with session_scope() as s:
        for rid in risk_ids:
            r = s.get(Risk, rid)
            if r and r.handled_by == "n8n" and r.n8n_resume_url:
                todo.append((rid, r.room_code, r.n8n_resume_url))
                r.n8n_resume_url = None
    for rid, room, url in todo:
        await resume(url, {"risk_id": rid, "room": room, "acknowledged": acknowledged, "by": reason})


def release_soon(risk_ids: list[int], reason: str, acknowledged: bool = False) -> None:
    if enabled() and risk_ids:
        asyncio.create_task(release(list(risk_ids), reason, acknowledged), name="n8n-release")


def _mark(ok: bool) -> None:
    global _online, _last_probe
    _online = ok
    _last_probe = time.time()


async def start() -> list[asyncio.Task]:
    """Sonde périodique de disponibilité (statut affiché dans l'interface)."""
    if not enabled():
        logger.info("n8n désactivé (N8N_ENABLED=0) : agents locaux")
        return []

    async def loop():
        while True:
            try:
                before = _online
                await probe(force=True)
                if before != _online:
                    logger.info("n8n %s (%s)", "joignable" if _online else "injoignable → repli local", settings.n8n_base_url)
                    try:
                        from .ws import manager

                        await manager.broadcast({"type": "n8n_status", **info()})
                    except Exception:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("sonde n8n", exc_info=True)
            await asyncio.sleep(20)

    return [asyncio.create_task(loop(), name="n8n-probe")]

"""Journal d'audit : toute modification passe par `audit(...)`."""

from __future__ import annotations

import contextvars
import json
import logging
from typing import Any

from sqlmodel import Session

from .auth import CurrentUser
from .models import AuditLog

logger = logging.getLogger("hackcure.audit")

# V3 (non-répudiation) : adresse du poste de la requête en cours, posée par `ClientIpMiddleware`
client_ip: contextvars.ContextVar[str] = contextvars.ContextVar("client_ip", default="")


class ClientIpMiddleware:
    """Middleware ASGI minimal : mémorise l'adresse du client pour la durée de la requête (lue par `audit`)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        ip = (scope.get("client") or ("", 0))[0] or ""
        for k, v in scope.get("headers", []):  # derrière un tunnel ou un proxy : première adresse de X-Forwarded-For
            if k.lower() == b"x-forwarded-for" and v:
                ip = v.decode("latin-1").split(",")[0].strip() or ip
                break
        token = client_ip.set(ip)
        try:
            await self.app(scope, receive, send)
        finally:
            client_ip.reset(token)


def audit(
    session: Session,
    user: CurrentUser | str | None,
    action: str,
    entity: str,
    entity_id: Any = None,
    details: Any = None,
) -> AuditLog:
    if isinstance(user, CurrentUser):
        username, role = user.username, user.role
    else:
        username, role = (user or "system"), ""
    if details is not None and not isinstance(details, str):
        details = json.dumps(details, ensure_ascii=False, default=str)
    row = AuditLog(user=username, role=role, action=action, entity=entity, entity_id=str(entity_id) if entity_id is not None else None, details=details or "", ip=client_ip.get())
    session.add(row)
    logger.info("AUDIT %s %s %s#%s", username, action, entity, entity_id)
    return row

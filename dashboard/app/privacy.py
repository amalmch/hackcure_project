"""
Pseudonymisation (V3, étape 2 — Privacy by Design).

Règle : tout ce qui SORT de la plateforme — prompts du LLM, webhooks n8n, messages Telegram, journaux du serveur —
ne porte que le pseudonyme du patient (`PAT-0001`), sa chambre, son âge, son sexe et ses données cliniques.
Jamais le nom, le prénom ni la date de naissance complète.

Deux protections complémentaires, appliquées aux points de sortie (pas chez chaque appelant, pour qu'un nouvel
agent ne puisse pas l'oublier) :
1. les champs d'identité d'un objet (`full_name`, `first_name`, `last_name`, `patient_name`, `birth_date`…) sont
   remplacés par le pseudonyme (la date de naissance est réduite à l'année) ;
2. tout texte libre est relu : les noms connus des patients y sont remplacés par leur pseudonyme.

Dans l'interface, l'identité complète n'est servie qu'aux rôles qui ont la permission `view_identity`
(`for_role`, appliqué aux réponses de l'API et aux messages WebSocket).

Interrupteur : `PSEUDONYMIZE_OUTBOUND` (activé par défaut).
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import deque
from typing import Any, Optional

logger = logging.getLogger("hackcure.privacy")

NAME_KEYS = {"full_name", "patient_name", "first_name", "last_name", "patient_full_name", "nom", "prenom"}
DATE_KEYS = {"birth_date", "date_naissance", "birthDate"}
PSEUDONYM = "pseudonyme"
_TTL_S = 20.0

_registry: dict[str, Any] = {"at": 0.0, "by_name": {}, "by_pid": {}, "rx": None}
sent: deque[tuple[str, str]] = deque(maxlen=400)  # (canal, texte réellement sorti) — lu par les tests et l'audit


def enabled() -> bool:
    return os.getenv("PSEUDONYMIZE_OUTBOUND", "1").strip().lower() not in ("0", "false", "no", "off")


def invalidate() -> None:
    _registry["at"] = 0.0


def _load() -> None:
    """Noms connus → pseudonyme. Rechargé toutes les 20 s et à chaque création / modification de patient."""
    by_name: dict[str, str] = {}
    by_pid: dict[str, str] = {}
    try:
        from sqlmodel import select

        from .db import session_scope
        from .models import Patient

        with session_scope() as s:
            for p in s.exec(select(Patient)).all():
                by_pid[p.patient_id] = p.code
                first, last = (p.first_name or "").strip(), (p.last_name or "").strip()
                for variant in (f"{first} {last}", f"{last} {first}", f"{last}, {first}", last, first):
                    if len(variant) >= 3:
                        by_name.setdefault(variant, p.code)
    except Exception as exc:  # base pas encore prête : on réessaiera
        logger.debug("registre des pseudonymes indisponible (%s)", exc.__class__.__name__)
        _registry["at"] = time.time() - _TTL_S + 2
        return
    names = sorted(by_name, key=len, reverse=True)  # les formes longues d'abord (« Ali Mezghani » avant « Ali »)
    rx = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(n) for n in names) + r")(?![\w-])") if names else None
    _registry.update(at=time.time(), by_name=by_name, by_pid=by_pid, rx=rx)


def _fresh() -> dict[str, Any]:
    if time.time() - _registry["at"] > _TTL_S:
        _load()
    return _registry


def code_for(patient_id: Optional[str]) -> Optional[str]:
    return _fresh()["by_pid"].get(patient_id or "")


def text(value: str) -> str:
    """Remplace dans un texte libre les noms de patients connus par leur pseudonyme."""
    reg = _fresh()
    rx = reg["rx"]
    if not rx or not value:
        return value
    return rx.sub(lambda m: reg["by_name"].get(m.group(0), "patient"), value)


def scrub(obj: Any, _code: Optional[str] = None) -> Any:
    """Copie pseudonymisée d'une structure JSON (dict / list / str), sans modifier l'original."""
    if isinstance(obj, str):
        return text(obj)
    if isinstance(obj, list):
        return [scrub(x, _code) for x in obj]
    if isinstance(obj, tuple):
        return tuple(scrub(x, _code) for x in obj)
    if not isinstance(obj, dict):
        return obj
    reg = _fresh()
    identity = any(k in obj for k in NAME_KEYS)
    code = (obj.get("code") if isinstance(obj.get("code"), str) and str(obj.get("code")).startswith("PAT-") else None) or reg["by_pid"].get(str(obj.get("patient_id") or "")) or _code
    if identity and not code:
        for k in ("full_name", "patient_name"):
            code = code or reg["by_name"].get(str(obj.get(k) or ""))
    out: dict[str, Any] = {}
    for k, v in obj.items():
        if k in NAME_KEYS:
            out[k] = (code or "patient") if k in ("full_name", "patient_name", "patient_full_name", "first_name", "prenom") else ""
        elif k in DATE_KEYS:
            out[k] = str(v)[:4] if v else v  # année de naissance seulement
        elif k == "name" and identity:
            out[k] = code or "patient"
        else:
            out[k] = scrub(v, code)
    if identity and code:
        out.setdefault(PSEUDONYM, code)
    return out


def outbound(channel: str, obj: Any) -> Any:
    """Point de sortie : ce qui part vers `channel` (llm, n8n, telegram). Renvoie la version à envoyer."""
    out = scrub(obj) if enabled() else obj
    try:
        import json

        sent.append((channel, out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, default=str)))
    except Exception:
        pass
    return out


# ── journaux du serveur ──────────────────────────────────────────────────────
class LogFilter(logging.Filter):
    """Les journaux ne portent jamais de nom de patient (le message formaté est relu avant écriture)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if enabled():
            try:
                msg = record.getMessage()
                clean = text(msg)
                if clean != msg:
                    record.msg, record.args = clean, ()
            except Exception:
                pass
        return True


_log_filter = LogFilter()


def install_log_filter() -> None:
    names = ["", "uvicorn", "uvicorn.error", "uvicorn.access"]
    for name in names:
        lg = logging.getLogger(name)
        for h in lg.handlers:
            if _log_filter not in h.filters:
                h.addFilter(_log_filter)
    root = logging.getLogger()
    if _log_filter not in root.filters:  # pytest (caplog) et gestionnaires ajoutés plus tard : le filtre du journal racine ne suffit pas seul,
        root.addFilter(_log_filter)      # d'où aussi `logging.setLogRecordFactory` ci-dessous
    if not getattr(install_log_filter, "_factory", None):
        base = logging.getLogRecordFactory()

        def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = base(*args, **kwargs)
            if record.name.startswith(("hackcure", "edge", "uvicorn")):
                _log_filter.filter(record)
            return record

        logging.setLogRecordFactory(factory)
        install_log_filter._factory = factory  # type: ignore[attr-defined]


# ── interface : identité réservée aux rôles qui en ont besoin ────────────────
def can_see_identity(role: Optional[str]) -> bool:
    from .auth import PERMISSIONS

    return bool(role) and role in PERMISSIONS["view_identity"]


def for_role(role: Optional[str], obj: Any) -> Any:
    """Réponse d'API ou message WebSocket tel que le rôle a le droit de le voir (pseudonyme si pas `view_identity`)."""
    return obj if can_see_identity(role) else scrub(obj)


def install() -> None:
    """Appelé au démarrage : filtre des journaux + invalidation du registre quand un patient est créé ou modifié."""
    install_log_filter()
    if getattr(install, "_done", False):
        return
    try:
        from sqlalchemy import event

        from .models import Patient

        for name in ("after_insert", "after_update", "after_delete"):
            event.listen(Patient, name, lambda *a, **k: invalidate())
        install._done = True  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover
        logger.warning("suivi des patients pour la pseudonymisation indisponible : %s", exc)


class IdentityGuard:
    """Middleware ASGI : les réponses JSON de l'API servies à un rôle sans `view_identity` (pharmacien) portent le
    pseudonyme à la place du nom. Les autres requêtes traversent sans aucune modification (ni tampon ni copie)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(("/api/", "/fhir/")):
            return await self.app(scope, receive, send)
        role = self._role(scope)
        if role is None or can_see_identity(role):  # anonyme : pages publiques par jeton (questionnaire du patient) et endpoints legacy
            return await self.app(scope, receive, send)
        start: dict[str, Any] = {}
        chunks: list[bytes] = []
        passthrough = False

        async def guarded(message: dict[str, Any]) -> None:
            nonlocal passthrough
            if message["type"] == "http.response.start":
                ctype = next((v.decode("latin-1") for k, v in message.get("headers", []) if k.lower() == b"content-type"), "")
                if "json" not in ctype:
                    passthrough = True
                    return await send(message)
                start.update(message)
                return
            if passthrough or message["type"] != "http.response.body":
                return await send(message)
            chunks.append(message.get("body", b""))
            if message.get("more_body"):
                return
            body = b"".join(chunks)
            try:
                import json

                body = json.dumps(scrub(json.loads(body)), ensure_ascii=False).encode("utf-8")
            except Exception:
                pass
            start["headers"] = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"] + [(b"content-length", str(len(body)).encode())]
            await send(start)
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, guarded)

    @staticmethod
    def _role(scope: dict[str, Any]) -> Optional[str]:
        try:
            from http.cookies import SimpleCookie

            from . import auth
            from .config import settings

            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            token = None
            if "cookie" in headers:
                c = SimpleCookie()
                c.load(headers["cookie"])
                token = c[settings.cookie_name].value if settings.cookie_name in c else None
            if not token and headers.get("authorization", "").lower().startswith("bearer "):
                token = headers["authorization"][7:].strip()
            user = auth.service_user_from_token(token) or auth.user_from_token(token)
            return user.role if user else None
        except Exception:
            return None

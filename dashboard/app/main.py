"""
Application FastAPI — Hospital Copilot.

Point d'entrée conservé : `cd dashboard && uvicorn server:app --reload --host 0.0.0.0 --port 8000`
(`server.py` importe `app` depuis ce module).
"""

from __future__ import annotations

from typing import Any

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import state
from .config import STATIC_DIR, settings
from .ws import manager

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hackcure.server")
# httpx journalise les URL complètes (jeton Telegram dans le chemin) : on le limite aux avertissements
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_background_tasks: list[asyncio.Task] = []


def _import_optional(path: str):
    """Import d'un sous-module de phase ultérieure sans casser le démarrage s'il manque."""
    try:
        import importlib

        return importlib.import_module(path, package=__package__)
    except ModuleNotFoundError as exc:  # pragma: no cover - dépend des phases livrées
        if exc.name and exc.name.startswith("app."):
            return None
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("%s v%s", settings.app_name, settings.version)
    logger.info("Dashboard: http://localhost:8000")
    logger.info("WebSocket: ws://localhost:8000/ws")
    logger.info("DB: %s", settings.database_url.split("@")[-1])
    logger.info("LLM: %s (%s)", settings.llm_provider, settings.llm_model)
    logger.info("=" * 60)

    db = _import_optional(".db")
    if db is not None:
        db.init_db()
        seed = _import_optional(".seed")
        if seed is not None and settings.seed_on_startup:
            seed.seed_all()
    privacy = _import_optional(".privacy")
    if privacy is not None:  # V3 : journaux sans nom de patient ; registre des pseudonymes tenu à jour
        privacy.install()
        logger.info("Pseudonymisation des sorties (LLM, n8n, Telegram, journaux) : %s", "active" if privacy.enabled() else "DÉSACTIVÉE (PSEUDONYMIZE_OUTBOUND=0)")
    for w in security_status()["warnings"]:  # avertissements visibles : la plateforme démarre quand même (mode démo)
        logger.warning("SÉCURITÉ — %s", w)

    for mod_name, starter in (
        (".ingest.mqtt", "start"),
        (".n8n", "start"),
        (".sim.embedded", "start"),
        (".agents.manager", "start"),
        (".agents.llm", "start_health_check"),
    ):
        mod = _import_optional(mod_name)
        if mod is not None and hasattr(mod, starter):
            try:
                tasks = await getattr(mod, starter)()
                if tasks:
                    _background_tasks.extend(tasks)
            except Exception:  # pragma: no cover
                logger.exception("Démarrage de %s impossible", mod_name)

    import os

    if os.getenv("LOOP_WATCHDOG", "0") == "1":  # diagnostic : pile des threads si la boucle se fige
        from . import watchdog

        _background_tasks.extend(await watchdog.start(float(os.getenv("LOOP_WATCHDOG_S", "1.5"))))

    try:
        yield
    finally:
        for t in _background_tasks:
            t.cancel()
        for t in _background_tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        _background_tasks.clear()


def security_status() -> dict[str, Any]:
    """État des mécanismes de conformité V3 (chacun a son interrupteur dans .env ; la plateforme démarre toujours)."""
    import os

    from . import crypto

    privacy = _import_optional(".privacy")
    integrity = _import_optional(".ingest.integrity")
    https = os.getenv("HTTPS", "").strip().lower() in ("1", "true", "yes", "on") and os.getenv("HACKCURE_TLS_ACTIVE") == "1"
    hmac_on = bool(os.getenv("EDGE_HMAC_KEY", "").strip()) and integrity is not None
    out = {
        "https": https, "tls_min_version": "TLSv1.3" if https else None,
        "encryption_at_rest": crypto.enabled(), "encryption_algorithm": "AES-256-GCM",
        "pseudonymisation": bool(privacy and privacy.enabled()),
        "frame_integrity": "hmac-sha256" if hmac_on else "demo",
        "warnings": [],
    }
    if not https:
        out["warnings"].append("HTTP en clair : activer HTTPS=true (scripts/make-cert) ou passer par le tunnel")
    if not out["encryption_at_rest"]:
        out["warnings"].append("Chiffrement au repos inactif : définir DATA_ENCRYPTION_KEY (scripts/make-key)")
    if not hmac_on:
        out["warnings"].append("Trames IoT non vérifiées : définir EDGE_HMAC_KEY (scripts/make-key)")
    if not out["pseudonymisation"]:
        out["warnings"].append("Pseudonymisation des sorties désactivée (PSEUDONYMIZE_OUTBOUND=0)")
    return out


def create_app() -> FastAPI:
    app = FastAPI(
        title="HackCure Patient Monitoring",
        description="Privacy-preserving AI patient monitoring with 3D digital twin",
        version=settings.version,
        lifespan=lifespan,
    )

    from .api import demo as demo_api

    app.include_router(demo_api.router)
    privacy = _import_optional(".privacy")
    if privacy is not None:
        app.add_middleware(privacy.IdentityGuard)
    from .audit import ClientIpMiddleware

    app.add_middleware(ClientIpMiddleware)  # V3 : IP du poste dans le journal d'audit

    # Routeurs des phases suivantes (inclus s'ils existent)
    for name in (
        "auth",
        "patients",
        "rooms",
        "devices",
        "risks",
        "commands",
        "pharmacy",
        "staff",
        "reports",
        "prescriptions",
        "agents",
        "ingest",
        "notifications",
        "scenario",
        "users",
        "kpi",
        "camera",
        "edge",
        "n8n",
        "fever",
        "dossier",
        "care",
        "psych",
        "predictions",
        "ambulances",
        "print",
        "fhir",       # V3 : interopérabilité HL7 FHIR R4
        "integrity",  # V3 : intégrité des trames IoT
        "sadm",       # V3 : validation / rejet des recommandations
    ):
        mod = _import_optional(f".api.{name}")
        if mod is not None and hasattr(mod, "router"):
            app.include_router(mod.router)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        role = None
        auth = _import_optional(".auth")
        if auth is not None:
            role = auth.role_from_cookie(websocket.cookies.get(settings.cookie_name))
        await manager.connect(websocket, role)
        try:
            await websocket.send_text(json.dumps(state.init_message(), default=str))
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception as e:  # pragma: no cover
            logger.error("WebSocket error: %s", e)
            manager.disconnect(websocket)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def serve_dashboard(request: Request):
        auth = _import_optional(".auth")
        if auth is not None and settings.auth_required and auth.optional_user(request) is None:
            return RedirectResponse(url="/login", status_code=302)
        return FileResponse(str(STATIC_DIR / "index.html"))

    @app.get("/login")
    async def serve_login():
        page = STATIC_DIR / "login.html"
        if page.exists():
            return FileResponse(str(page))
        return FileResponse(str(STATIC_DIR / "index.html"))

    @app.get("/health")
    async def health():
        return JSONResponse(
            {
                "status": "ok",
                "version": settings.version,
                "mode": state.current_mode["mode"],
                "ws_clients": manager.count,
                "llm_provider": settings.llm_provider,
                "llm_model": settings.llm_model,
                "llm": getattr(_import_optional(".agents.llm"), "health", {}).get("status", "n/a"),
                "llm_detail": getattr(_import_optional(".agents.llm"), "health", {}).get("detail"),
                "mqtt": getattr(_import_optional(".ingest.mqtt"), "status", lambda: "disabled")(),
                "n8n": getattr(_import_optional(".n8n"), "status", lambda: "disabled")(),
                "telegram": settings.telegram_enabled,
                "security": security_status(),
            }
        )

    return app


app = create_app()

"""
Simulateur embarqué dans le serveur (EMBEDDED_SIM=1) : mêmes moteur et scénarios que
`simulator/`, transport direct vers `ingest.handler` (pas de réseau, pas de broker).

La chambre 101 est simulée (vision + thermique) tant qu'aucun edge réel ne parle ;
`notify_real_edge("101")` coupe la vision virtuelle (les appareils restent simulés).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, Optional

from ..config import PROJECT_ROOT, settings
from ..ingest import handler
from ..ws import manager

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulator.engine import Scenario, SimEngine  # noqa: E402

logger = logging.getLogger("hackcure.sim.embedded")

engine: Optional[SimEngine] = None
_task: Optional[asyncio.Task] = None
_real_edge_rooms: set[str] = set()
current_scenario: dict[str, Any] = {"name": None, "room": None, "started_at": None}


def _publish(topic: str, payload: dict[str, Any]) -> None:
    handler.handle_nowait(topic, payload, via="embedded")


def _on_scenario_event(kind: str, data: dict[str, Any]) -> None:
    if kind == "scenario_started":
        current_scenario.update(name=data["name"], room=data.get("room"), started_at=handler._now_iso())
    elif kind in ("scenario_finished", "scenario_stopped"):
        current_scenario.update(name=None, room=None, started_at=None)
    elif kind == "resolution_step" and (data.get("params") or {}).get("hook"):
        _run_hook(data["params"]["hook"], str(data.get("room")))
    elif kind == "scenario_step" and str((data.get("params") or {}).get("hook", "")).startswith("demo_"):
        from .. import demo_v2

        params = {"room": str(data.get("room")), **data["params"]}  # gestes des humains, joués par le pilote automatique
        demo_v2.schedule(params["hook"], params, str(data.get("room")))
    manager.broadcast_nowait({"type": "scenario", "event": kind, **data})


def _run_hook(hook: str, room: str) -> None:
    """Effets côté serveur d'une étape de résolution (ce que le simulateur ne peut pas faire seul)."""
    from .. import state

    if hook == "administer_due":  # le soignant simulé administre les prises dues ou en retard de la chambre
        from datetime import datetime, timezone

        from sqlmodel import select

        from .. import care
        from ..db import session_scope
        from ..models import MedicationDose

        with session_scope() as s:
            for d in s.exec(select(MedicationDose).where(MedicationDose.room_code == room, MedicationDose.status == "scheduled", MedicationDose.due_at <= datetime.now(timezone.utc))).all():
                care.give(s, d, "infirmier (simulation)", "administré pendant la visite")
        manager.broadcast_nowait({"type": "care_plan", "event": "given", "room": room})
        return
    if hook == "equipment_repaired":  # pannes signalées par le pipeline de vision (hors flux d'appareil) : levées par le soignant
        from ..bus import bus

        try:
            asyncio.get_running_loop().create_task(bus.publish("internal/machine_error", {"room": room, "active": False, "machine_type": "", "source": "simulation"}))
        except RuntimeError:
            pass
        return
    if hook == "behavior_recover":
        pid = state.patient_for_room(room)
        if pid:
            try:
                asyncio.get_running_loop().create_task(state.process_event(pid, "recover", source="simulation", confidence=1.0))
            except RuntimeError:  # hors boucle asyncio (moteur piloté à la main par un test)
                pass


async def start() -> list[asyncio.Task]:
    global engine, _task
    if not settings.embedded_sim:
        return []
    engine = SimEngine(publish=_publish, speed=settings.sim_speed, source="sim")
    engine.on_scenario_event = _on_scenario_event
    for r in _real_edge_rooms:
        engine.set_room_virtual(r, False)
    _task = asyncio.create_task(_loop(), name="embedded-sim")
    logger.info("Simulateur embarqué démarré (x%.1f)", settings.sim_speed)
    return [_task]


async def _loop() -> None:
    assert engine is not None
    while True:
        try:
            await asyncio.sleep(0.25)
            # un edge réel silencieux depuis > 30 s : la 101 redevient virtuelle
            for room in list(_real_edge_rooms):
                if not handler.edge_alive(room, within_s=30.0):
                    _real_edge_rooms.discard(room)
                    engine.set_room_virtual(room, True)
                    logger.info("Edge %s silencieux : vision virtuelle réactivée", room)
            engine.tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Boucle du simulateur embarqué")
            await asyncio.sleep(1.0)


def notify_real_edge(room: str) -> None:
    if room not in _real_edge_rooms:
        _real_edge_rooms.add(room)
        if engine is not None:
            engine.set_room_virtual(room, False)
            logger.info("Edge réel détecté en %s : vision virtuelle coupée", room)


def is_running() -> bool:
    return engine is not None and _task is not None and not _task.done()


def start_scenario(name: str, room: str | None = None) -> dict[str, Any]:
    if engine is None:
        raise RuntimeError("Simulateur embarqué désactivé (EMBEDDED_SIM=0)")
    if name == "stop":
        engine.stop_scenario()
    sc = engine.start_scenario(name, room)
    return {"name": sc.name, "room": sc.room, "description": sc.description, "duration": sc.duration, "steps": len(sc.steps)}


def stop_scenario() -> None:
    if engine is not None:
        engine.stop_scenario()


def apply(room: str, action: str, **params: Any) -> None:
    if engine is None:
        raise RuntimeError("Simulateur embarqué désactivé")
    engine.apply(room, action, **params)


def handle_command(room: str, equipment: str, action: str, value: Any = None, command_id: str | None = None) -> bool:
    """Edge virtuel : traite la commande si la chambre n'est pas pilotée par un vrai edge."""
    if engine is None or room in _real_edge_rooms:
        return False
    engine.handle_command(room, equipment, action, value, command_id)
    return True


def available_scenarios() -> list[dict[str, Any]]:
    return Scenario.available()

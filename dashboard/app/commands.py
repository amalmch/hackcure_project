"""
Commandes d'équipement (fenêtre, chauffage, clim, veilleuse, buzzer) : serveur → edge.

Transport, par ordre : MQTT si un vrai edge parle pour la chambre → simulateur embarqué (edge virtuel)
→ MQTT quand même si connecté → **équipement virtuel côté serveur** (ack synthétique) pour que la démo
fonctionne sans aucun transport. Attend `cmd/ack` (délai 4 s).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import select

from .bus import bus
from .db import session_scope
from .ingest import handler, mqtt
from .models import RoomEquipment

logger = logging.getLogger("hackcure.commands")

EQUIPMENTS = ("window", "heater", "ac", "light", "buzzer")
ACTIONS = ("open", "close", "on", "off", "set")


def virtual_state(equipment: str, action: str) -> str:
    if equipment == "window":
        return "open" if action in ("open", "on") else "closed"
    return "on" if action in ("on", "open") else "off"


async def send_command(room: str, equipment: str, action: str, requested_by: str, reason: str, value: Any = None, wait_ack: bool = True, timeout: float = 4.0) -> dict[str, Any]:
    if equipment not in EQUIPMENTS or action not in ACTIONS:
        raise ValueError(f"Commande invalide : {equipment}/{action}")
    cmd_id = uuid.uuid4().hex[:10]
    topic = f"hackcure/room/{room}/cmd/{equipment}"
    payload = {"ts": datetime.now(timezone.utc).isoformat(), "source": "server", "action": action, "value": value, "requestedBy": requested_by, "reason": reason, "commandId": cmd_id}
    q = bus.subscribe(f"hackcure/room/{room}/cmd/ack") if wait_ack else None
    await bus.publish(topic, {"room": room, "kind": "cmd", "data": payload, "groups": {"room": room, "equipment": equipment}, "via": "server"})

    transport: Optional[str] = None
    try:
        from .sim import embedded
    except Exception:  # pragma: no cover
        embedded = None
    if handler.edge_alive(room) and mqtt.connected() and await mqtt.publish(topic, payload):
        transport = "mqtt"
    if transport is None and embedded is not None and embedded.handle_command(room, equipment, action, value, cmd_id):
        transport = "embedded"
    if transport is None and mqtt.connected() and await mqtt.publish(topic, payload):
        transport = "mqtt"
    if transport is None and handler.edge_alive(room):
        # edge réel sans broker : il interroge GET /api/edge/commands et répond par cmd/ack via /api/ingest
        from .api.edge import enqueue

        enqueue(room, payload, equipment)
        transport = "http-poll"
        timeout = max(timeout, 8.0)

    result: Optional[dict[str, Any]] = None
    if transport is None:
        transport = "virtual"
        if q is not None:
            bus.unsubscribe(q)
            q = None
        ack = {"ts": datetime.now(timezone.utc).isoformat(), "source": "server-virtual", "equipment": equipment, "action": action, "ok": True, "state": virtual_state(equipment, action), "commandId": cmd_id}
        await handler.handle(f"hackcure/room/{room}/cmd/ack", ack, via="virtual")
        result = ack
    elif q is not None:
        deadline = time.time() + timeout
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                ev = await asyncio.wait_for(q.get(), timeout=remaining)
                d = ev.payload.get("data", {})
                if d.get("equipment") == equipment and d.get("commandId") in (cmd_id, None):
                    result = d
                    break
        except asyncio.TimeoutError:
            result = None
        finally:
            bus.unsubscribe(q)

    try:
        with session_scope() as s:
            eq = s.exec(select(RoomEquipment).where(RoomEquipment.room_code == room, RoomEquipment.type == equipment)).first()
            if eq:
                eq.last_command_by = requested_by
                if result and result.get("ok"):
                    eq.state = result.get("state", eq.state)
                    eq.updated_at = datetime.now(timezone.utc)
    except Exception:
        logger.debug("RoomEquipment non mis à jour", exc_info=True)

    ok = bool(result and result.get("ok"))
    logger.info("CMD %s/%s %s par %s via %s → %s", room, equipment, action, requested_by, transport, "ok" if ok else "sans ack")
    return {"commandId": cmd_id, "room": room, "equipment": equipment, "action": action, "transport": transport, "ack": result, "ok": ok}

"""
Commandes pour un edge sans MQTT : l'edge interroge `GET /api/edge/commands?room=101` (repli HTTP)
et répond par `cmd/ack` via `POST /api/ingest`. Les commandes sont déposées par `app.commands.send_command`.
"""

from __future__ import annotations

import os
from collections import defaultdict, deque
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException

from ..ingest import handler

router = APIRouter(prefix="/api/edge", tags=["edge"])

pending: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=50))


def enqueue(room: str, payload: dict[str, Any], equipment: str) -> None:
    pending[room].append({**payload, "equipment": equipment})


@router.get("/commands")
def get_commands(room: str, x_api_key: Optional[str] = Header(default=None)):
    expected = os.getenv("INGEST_API_KEY", "")
    if expected and x_api_key != expected:
        raise HTTPException(401, "Clé invalide")
    if room not in handler.ROOMS:
        raise HTTPException(404, "Chambre inconnue")
    handler.edge_seen[room] = __import__("time").time()  # le polling prouve que l'edge est vivant
    items = list(pending[room])
    pending[room].clear()
    return {"room": room, "commands": items}


@router.get("/status")
def edge_status():
    return {r: {"alive": handler.edge_alive(r), "pending_commands": len(pending[r])} for r in handler.ROOMS}

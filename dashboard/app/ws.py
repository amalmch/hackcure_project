"""
Gestionnaire de connexions WebSocket (/ws) — extrait de l'ancien server.py.
Le protocole existant est conservé : `init`, `patient_event`, `reset`, `mode_change`, `pong`.
Les nouveaux types (`room_state`, `agent_log`, `risk`, `notification`, ...) passent
par le même `broadcast`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("hackcure.ws")


class ConnectionManager:
    """Gère les connexions WebSocket et diffuse les messages."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        # Rôle de l'utilisateur par connexion (None = anonyme)
        self.roles: dict[int, str | None] = {}

    async def connect(self, websocket: WebSocket, role: str | None = None) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        self.roles[id(websocket)] = role
        logger.info("Client connected. Total: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        self.roles.pop(id(websocket), None)
        logger.info("Client disconnected. Total: %d", len(self.active_connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Envoie un message JSON à tous les clients connectés."""
        data = json.dumps(message, default=str)
        pseudo: str | None = None  # version pseudonymisée, calculée seulement si un client sans `view_identity` est connecté
        disconnected: list[WebSocket] = []
        for connection in list(self.active_connections):
            try:
                from . import privacy

                if privacy.can_see_identity(self.roles.get(id(connection))):
                    await connection.send_text(data)
                else:
                    if pseudo is None:
                        pseudo = json.dumps(privacy.scrub(json.loads(data)), default=str)
                    await connection.send_text(pseudo)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

    def broadcast_nowait(self, message: dict[str, Any]) -> None:
        """Variante utilisable depuis du code synchrone (planifie la diffusion)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.broadcast(message))

    @property
    def count(self) -> int:
        return len(self.active_connections)


manager = ConnectionManager()

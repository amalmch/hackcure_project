"""
Bus d'événements asyncio interne.

Les sources (ingestion MQTT/HTTP, démo, agents) publient `(topic, payload)` ;
les abonnés (agents, diffusion WebSocket) reçoivent via une file dédiée.
Les motifs d'abonnement acceptent `*` comme joker de segment et `#` en fin de motif.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("hackcure.bus")


@dataclass
class Event:
    topic: str
    payload: dict[str, Any]
    ts: float = field(default_factory=time.time)


def topic_matches(pattern: str, topic: str) -> bool:
    """Correspondance MQTT simplifiée : `+`/`*` = un segment, `#` = le reste."""
    p_parts = pattern.split("/")
    t_parts = topic.split("/")
    for i, p in enumerate(p_parts):
        if p == "#":
            return True
        if i >= len(t_parts):
            return False
        if p in ("+", "*"):
            continue
        if not fnmatch.fnmatchcase(t_parts[i], p):
            return False
    return len(p_parts) == len(t_parts)


class EventBus:
    def __init__(self) -> None:
        self._subs: list[tuple[list[str], asyncio.Queue[Event]]] = []
        self.published = 0

    def subscribe(self, *patterns: str, maxsize: int = 1000) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._subs.append((list(patterns) or ["#"], q))
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        self._subs = [(p, qq) for p, qq in self._subs if qq is not q]

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        ev = Event(topic=topic, payload=payload)
        self.published += 1
        for patterns, q in list(self._subs):
            if any(topic_matches(p, topic) for p in patterns):
                try:
                    q.put_nowait(ev)
                except asyncio.QueueFull:
                    # On jette le plus ancien pour ne jamais bloquer une source
                    try:
                        q.get_nowait()
                        q.put_nowait(ev)
                    except Exception:
                        pass

    def publish_nowait(self, topic: str, payload: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.publish(topic, payload))


bus = EventBus()

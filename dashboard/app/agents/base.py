"""
Classe de base des agents : tâche asyncio abonnée au bus, statut `idle|thinking|acting`,
journal `AgentLog` diffusé en temps réel (`agent_log`), redémarrage automatique sur exception.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from ..bus import Event, bus
from ..db import session_scope
from ..models import AgentLog
from ..ws import manager

logger = logging.getLogger("hackcure.agents")


class Agent:
    name: str = "Agent"
    description: str = ""
    patterns: list[str] = []
    tick_interval: Optional[float] = None

    def __init__(self) -> None:
        self.status = "idle"
        self.last_run: Optional[str] = None
        self.last_output: str = ""
        self.runs = 0
        self.errors = 0
        self.restarts = 0
        self._task: Optional[asyncio.Task] = None
        self._queue: Optional[asyncio.Queue[Event]] = None

    # ── cycle de vie ────────────────────────────────────────────────────────
    def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(self._run(), name=f"agent-{self.name}")
        return self._task

    async def _run(self) -> None:
        while True:
            q = bus.subscribe(*self.patterns)
            self._queue = q
            try:
                await self.on_start()
                next_tick = time.monotonic() + (self.tick_interval or 0)
                while True:
                    # le tick est périodique même quand les messages arrivent en continu (capteurs à 1–2 Hz)
                    try:
                        if self.tick_interval:
                            ev = await asyncio.wait_for(q.get(), timeout=max(0.0, next_tick - time.monotonic()))
                        else:
                            ev = await q.get()
                    except asyncio.TimeoutError:
                        ev = None
                    if ev is not None:
                        await self._safe(self.handle, ev)
                    if self.tick_interval and time.monotonic() >= next_tick:
                        next_tick = time.monotonic() + self.tick_interval
                        await self._safe(self.on_tick)
            except asyncio.CancelledError:
                bus.unsubscribe(q)
                raise
            except Exception:
                # un agent ne s'arrête jamais : log + redémarrage
                self.errors += 1
                self.restarts += 1
                logger.exception("%s : boucle en erreur, redémarrage", self.name)
                bus.unsubscribe(q)
                await asyncio.sleep(1.0)

    async def _safe(self, fn, *args: Any) -> None:
        try:
            await fn(*args)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.errors += 1
            logger.exception("%s : exception dans %s", self.name, fn.__name__)
            try:
                await self.log(None, input=fn.__name__, reasoning=f"Exception : {exc.__class__.__name__}: {exc}", output="ignorée, agent toujours actif", status="error")
            except Exception:
                pass
            if self.status != "idle":
                await self.set_status("idle")

    async def on_start(self) -> None:  # pragma: no cover - surcharge
        pass

    async def on_tick(self) -> None:  # pragma: no cover - surcharge
        pass

    async def handle(self, ev: Event) -> None:  # pragma: no cover - surcharge
        pass

    # ── statut et journal ───────────────────────────────────────────────────
    @asynccontextmanager
    async def working(self, status: str = "thinking"):
        await self.set_status(status)
        try:
            yield
        finally:
            await self.set_status("idle")

    async def set_status(self, status: str) -> None:
        if status == self.status:
            return
        self.status = status
        await manager.broadcast({"type": "agent_status", "agent": self.name, "status": status, "last_run": self.last_run, "runs": self.runs, "errors": self.errors})

    async def log(self, room: Optional[str], input: str, reasoning: str, output: str, status: str = "ok", risk_id: Optional[int] = None, duration_ms: int = 0) -> Optional[int]:
        self.last_run = datetime.now(timezone.utc).isoformat()
        self.runs += 1
        self.last_output = (output or "")[:200]
        log_id: Optional[int] = None
        try:
            with session_scope() as s:
                row = AgentLog(agent=self.name, room_code=room, input=input[:2000], reasoning=reasoning[:4000], output=output[:4000], status=status, risk_id=risk_id, duration_ms=duration_ms)
                s.add(row)
                s.flush()
                log_id = row.id
                ts = row.ts.isoformat()
        except Exception:
            ts = self.last_run
            logger.debug("AgentLog non persisté", exc_info=True)
        await manager.broadcast({
            "type": "agent_log", "id": log_id, "agent": self.name, "room": room, "input": input[:600], "reasoning": reasoning[:1200],
            "output": output[:1200], "status": status, "risk_id": risk_id, "duration_ms": duration_ms, "ts": ts,
        })
        return log_id

    def info(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "status": self.status, "last_run": self.last_run, "last_output": self.last_output, "runs": self.runs, "errors": self.errors, "restarts": self.restarts}


class Stopwatch:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()

    @property
    def ms(self) -> int:
        return int((time.perf_counter() - self.t0) * 1000)

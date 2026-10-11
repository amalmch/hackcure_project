"""Scénarios de démonstration (bouton « Lancer la démo »)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth as authlib
from ..ingest import handler, mqtt
from ..sim import embedded

router = APIRouter(prefix="/api/demo", tags=["demo"])


class ScenarioIn(BaseModel):
    name: str
    room: Optional[str] = None


class SimAction(BaseModel):
    room: str
    action: str
    params: dict[str, Any] = {}


@router.get("/scenarios")
def list_scenarios(_: authlib.CurrentUser = Depends(authlib.require("run_demo"))):
    return {"scenarios": embedded.available_scenarios(), "current": embedded.current_scenario, "embedded": embedded.is_running(), "mqtt": mqtt.status()}


@router.post("/scenario")
async def start_scenario(body: ScenarioIn, _: authlib.CurrentUser = Depends(authlib.require("run_demo"))):
    payload = {"ts": handler._now_iso(), "source": "server", "name": body.name, "room": body.room}
    sent_mqtt = await mqtt.publish("hackcure/sim/scenario", payload)
    started = None
    if embedded.is_running():
        try:
            started = embedded.start_scenario(body.name, body.room)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
    elif not sent_mqtt:
        raise HTTPException(503, "Aucun simulateur disponible (EMBEDDED_SIM=0 et pas de broker MQTT)")
    return {"status": "ok", "scenario": started or {"name": body.name}, "via": "embedded" if started else "mqtt"}


@router.post("/scenario/stop")
async def stop_scenario(_: authlib.CurrentUser = Depends(authlib.require("run_demo"))):
    await mqtt.publish("hackcure/sim/scenario", {"ts": handler._now_iso(), "source": "server", "name": "stop"})
    embedded.stop_scenario()
    return {"status": "ok"}


@router.post("/sim/action")
async def sim_action(body: SimAction, _: authlib.CurrentUser = Depends(authlib.require("run_demo"))):
    """Action directe sur le simulateur embarqué (tests, démo manuelle)."""
    if not embedded.is_running():
        raise HTTPException(503, "Simulateur embarqué désactivé")
    try:
        embedded.apply(body.room, body.action, **body.params)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return {"status": "ok"}


@router.get("/sim/state")
def sim_state(_: authlib.CurrentUser = Depends(authlib.require("run_demo"))):
    if not embedded.is_running() or embedded.engine is None:
        return {"running": False}
    return {"running": True, "speed": embedded.engine.speed, "night": embedded.engine.is_night, "rooms": embedded.engine.snapshot(), "scenario": embedded.current_scenario}

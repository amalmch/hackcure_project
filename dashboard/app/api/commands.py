"""Commandes d'équipement depuis l'interface (fenêtre, chauffage, clim, veilleuse, buzzer)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import auth as authlib
from ..audit import audit
from ..commands import ACTIONS, EQUIPMENTS, send_command
from ..db import get_session
from ..ingest import handler
from ..models import RoomEquipment

router = APIRouter(prefix="/api/commands", tags=["commands"])


class CommandIn(BaseModel):
    room: str
    equipment: str
    action: str
    value: Optional[Any] = None
    reason: str = "commande manuelle"


@router.post("")
async def command(body: CommandIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.can_control_equipment)):
    if body.equipment not in EQUIPMENTS or body.action not in ACTIONS:
        raise HTTPException(400, f"Équipement {EQUIPMENTS} / action {ACTIONS}")
    if body.room not in handler.ROOMS:
        raise HTTPException(404, "Chambre inconnue")
    result = await send_command(body.room, body.equipment, body.action, requested_by=user.username, reason=body.reason, value=body.value)
    audit(session, user, "command", "equipment", f"{body.room}/{body.equipment}", {"action": body.action, "transport": result["transport"], "ok": result["ok"]})
    session.commit()
    return result


@router.get("/equipment")
def equipment(session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.get_current_user)):
    out: dict[str, dict[str, Any]] = {}
    for eq in session.exec(select(RoomEquipment).order_by(RoomEquipment.room_code)).all():
        live = handler.room_state(eq.room_code)["equipment"].get(eq.type, eq.state)
        out.setdefault(eq.room_code, {})[eq.type] = {"state": live, "last_command_by": eq.last_command_by, "updated_at": eq.updated_at}
    return out

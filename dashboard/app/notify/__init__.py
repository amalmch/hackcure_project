"""Notifications : in-app (WebSocket + table Notification) et Telegram (optionnel)."""

from __future__ import annotations

import logging
from typing import Optional

from ..config import settings
from ..db import session_scope
from ..models import Notification
from ..ws import manager
from .telegram import send_telegram

logger = logging.getLogger("hackcure.notify")

LEVEL_ICON = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
ROLE_LABEL = {"nurse": "Infirmier", "duty_doctor": "Médecin de garde", "all": "Tous"}


ROLE_LABEL.setdefault("psychiatrist", "Psychiatre")


async def notify(level: str, title: str, body: str = "", room: Optional[str] = None, risk_id: Optional[int] = None, target_role: str = "nurse", telegram: bool = True) -> Notification:
    channels = ["in_app"]
    use_tg = telegram and settings.telegram_enabled
    if use_tg:
        channels.append("telegram")
    with session_scope() as s:
        n = Notification(level=level, title=title, body=body, room_code=room, risk_id=risk_id, target_role=target_role, channels=",".join(channels))
        s.add(n)
        s.flush()
        payload = {"type": "notification", "id": n.id, "level": level, "title": title, "body": body, "room": room, "risk_id": risk_id, "target_role": target_role, "channels": channels, "created_at": n.created_at.isoformat()}
        nid = n.id
    await manager.broadcast(payload)
    if use_tg:
        text = f"{LEVEL_ICON.get(level, '')} <b>{title}</b>\n{body}\n👤 {ROLE_LABEL.get(target_role, target_role)}" + (f" · 🚪 chambre {room}" if room else "")
        ok = await send_telegram(text)
        if ok:
            with session_scope() as s:
                row = s.get(Notification, nid)
                if row:
                    row.telegram_sent = True
    logger.info("NOTIF [%s] %s → %s", level, title, target_role)
    return n

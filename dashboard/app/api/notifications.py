"""Notifications in-app (cloche)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, func, select

from .. import auth as authlib
from ..db import get_session
from ..models import Notification

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _out(n: Notification) -> dict:
    return {"id": n.id, "level": n.level, "title": n.title, "body": n.body, "room": n.room_code, "risk_id": n.risk_id, "target_role": n.target_role, "channels": n.channels.split(","), "telegram_sent": n.telegram_sent, "read": n.read, "created_at": n.created_at}


@router.get("")
def list_notifications(unread: bool = False, limit: int = Query(40, le=300), session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.get_current_user)):
    q = select(Notification)
    if unread:
        q = q.where(Notification.read.is_(False))
    rows = session.exec(q.order_by(Notification.created_at.desc()).limit(limit)).all()
    unread_count = session.exec(select(func.count(Notification.id)).where(Notification.read.is_(False))).one()
    return {"items": [_out(n) for n in rows], "unread": unread_count}


@router.post("/{notif_id}/read")
def mark_read(notif_id: int, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.get_current_user)):
    n = session.get(Notification, notif_id)
    if not n:
        raise HTTPException(404, "Notification introuvable")
    n.read = True
    session.commit()
    return {"status": "ok"}


@router.post("/read-all")
def read_all(session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.get_current_user)):
    for n in session.exec(select(Notification).where(Notification.read.is_(False))).all():
        n.read = True
    session.commit()
    return {"status": "ok"}

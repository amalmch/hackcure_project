"""Appareils médicaux : dernières valeurs et historiques (mémoire 15 min + base)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from .. import auth as authlib
from ..db import get_session
from ..ingest import handler
from ..models import MedicalDevice, VitalReading

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("")
def list_devices(room: str | None = None, session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.can_view_clinical)):
    q = select(MedicalDevice)
    if room:
        q = q.where(MedicalDevice.room_code == room)
    out = []
    for d in session.exec(q.order_by(MedicalDevice.room_code, MedicalDevice.type)).all():
        live = handler.latest_device.get(d.device_id)
        out.append({
            "device_id": d.device_id, "room": d.room_code, "type": d.type, "label": d.label,
            "status": live["status"] if live else d.status, "metrics": live["metrics"] if live else {},
            "ts": live["ts"] if live else (d.last_seen.isoformat() if d.last_seen else None), "live": live is not None,
            "fault": (handler.room_state(d.room_code).get("deviceFaults") or {}).get(d.type),
        })
    return out


@router.get("/latest")
def latest(_: authlib.CurrentUser = Depends(authlib.can_view_clinical)):
    return list(handler.latest_device.values())


@router.get("/{device_id}/history")
def history(device_id: str, metric: str = Query(...), minutes: int = Query(10, ge=1, le=1440), session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.can_view_clinical)):
    pts = handler.device_history(device_id, metric, minutes * 60)
    if len(pts) < 5 or minutes > 15:
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        rows = session.exec(select(VitalReading).where(VitalReading.device_id == device_id, VitalReading.metric == metric, VitalReading.ts >= since).order_by(VitalReading.ts)).all()
        db_pts = [(r.ts.replace(tzinfo=timezone.utc).timestamp() if r.ts.tzinfo is None else r.ts.timestamp(), r.value) for r in rows]
        if len(db_pts) > len(pts):
            pts = db_pts
    if not pts and device_id not in handler.latest_device and not session.exec(select(MedicalDevice).where(MedicalDevice.device_id == device_id)).first():
        raise HTTPException(404, "Appareil inconnu")
    return {"device_id": device_id, "metric": metric, "unit": handler.DEVICE_UNITS.get(metric, ""), "points": [{"t": round(t, 1), "v": v} for t, v in pts]}

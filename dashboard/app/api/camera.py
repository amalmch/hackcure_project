"""
Aperçu caméra de la chambre 101 : flux MJPEG basse résolution **flouté** relayé depuis l'edge
(`EDGE_CAMERA_URL`, ex. http://raspberrypi:8080/stream), réservé aux rôles médicaux.
Sans edge : 404 → l'interface affiche une vue schématique. Aucune image n'est stockée.
"""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from .. import auth as authlib
from ..ingest import handler

router = APIRouter(prefix="/api/camera", tags=["camera"])


@router.get("/status")
def status(_: authlib.CurrentUser = Depends(authlib.can_view_clinical)):
    url = os.getenv("EDGE_CAMERA_URL", "")
    return {"101": {"configured": bool(url), "edge_alive": handler.edge_alive("101"), "url": "/api/camera/101/stream" if url else None, "blurred": True}}


@router.get("/{room}/stream")
async def stream(room: str, _: authlib.CurrentUser = Depends(authlib.can_view_clinical)):
    url = os.getenv("EDGE_CAMERA_URL", "")
    if room != "101" or not url:
        raise HTTPException(404, "Flux caméra non disponible (EDGE_CAMERA_URL non défini ou chambre sans caméra)")

    async def gen():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None)) as client:
                async with client.stream("GET", url) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        except Exception:
            return

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

"""Repli HTTP du broker MQTT : `POST /api/ingest` (un message ou un lot).

Intégrité des trames (V3) : une trame refusée par `ingest/integrity.py` apparaît dans `rejected` avec sa raison
(`reason`). Si AUCUN message du lot n'est accepté et qu'au moins un l'a été pour cette raison : `401`."""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from .. import contracts
from ..ingest import handler, integrity

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


class IngestMessage(BaseModel):
    topic: str
    payload: dict[str, Any]


class IngestBatch(BaseModel):
    topic: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    messages: Optional[list[IngestMessage]] = None


def _check_key(x_api_key: Optional[str]) -> None:
    expected = os.getenv("INGEST_API_KEY", "")
    if expected and x_api_key != expected:
        raise HTTPException(401, "Clé d'ingestion invalide")


@router.post("", status_code=202)
async def ingest(body: IngestBatch, x_api_key: Optional[str] = Header(default=None)):
    _check_key(x_api_key)
    msgs = body.messages or []
    if body.topic and body.payload is not None:
        msgs = [IngestMessage(topic=body.topic, payload=body.payload)] + msgs
    if not msgs:
        raise HTTPException(422, "Aucun message (attendu {topic, payload} ou {messages:[...]})")
    results, errors, unauthentic = [], [], 0
    for m in msgs:
        try:
            results.append(await handler.handle(m.topic, m.payload, via="http"))
        except contracts.ContractError as exc:
            errors.append({"topic": m.topic, "error": str(exc)})
        except integrity.FrameRejected as exc:
            unauthentic += 1
            errors.append({"topic": m.topic, "error": str(exc), "reason": exc.reason})
    if unauthentic and not results:
        raise HTTPException(401, detail=errors)
    if errors and not results:
        raise HTTPException(422, detail=errors)
    return {"status": "accepted", "accepted": len(results), "rejected": errors}


@router.get("/stats")
async def ingest_stats():
    return {"accepted": handler.stats["accepted"], "rejected": handler.stats["rejected"], "by_via": dict(handler.stats["by_via"]), "edge_seen": {r: handler.edge_alive(r) for r in handler.ROOMS}}

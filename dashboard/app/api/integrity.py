"""Intégrité des trames IoT (V3) : mode (démo / vérification active), compteurs et derniers rejets pour la page Machines."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import auth as authlib
from ..ingest import integrity

router = APIRouter(prefix="/api/integrity", tags=["integrity"])


@router.get("")
def frame_integrity(_: authlib.CurrentUser = Depends(authlib.can_view_clinical)):
    return integrity.snapshot()

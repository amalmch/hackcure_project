"""
HackCure — FastAPI Backend Server (point d'entrée conservé)
=============================================================
L'implémentation vit désormais dans le package `app/` (voir app/main.py).

Usage:
    cd dashboard
    uvicorn server:app --reload --host 0.0.0.0 --port 8000
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from app.main import app  # noqa: E402,F401

__all__ = ["app"]

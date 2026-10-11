"""
Rejeu de constantes réelles anonymisées (VitalDB, CC BY 4.0, https://vitaldb.net) avec repli synthétique.

- `load_case(caseid, tracks)` tente `vitaldb.load_case` (ou l'API HTTP publique) avec un délai court ;
- sans réseau / sans paquet : `synthetic_track(...)` produit une série plausible (même interface).

Les séries sont normalisées en dict `{"hr": [...], "spo2": [...], "sys": [...], "dia": [...]}` à 1 Hz.
"""

from __future__ import annotations

import logging
import math
import random
import threading
from typing import Any, Optional

logger = logging.getLogger("hackcure.vitaldb")

TRACKS = {
    "hr": "Solar8000/HR",
    "spo2": "Solar8000/PLETH_SPO2",
    "sys": "Solar8000/ART_SBP",
    "dia": "Solar8000/ART_DBP",
}


def _with_timeout(fn, timeout_s: float, *args, **kwargs):
    result: dict[str, Any] = {}

    def run():
        try:
            result["value"] = fn(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - dépend du réseau
            result["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise TimeoutError("VitalDB: délai dépassé")
    if "error" in result:
        raise result["error"]
    return result.get("value")


def load_case(caseid: int = 1, seconds: int = 600, timeout_s: float = 6.0) -> Optional[dict[str, list[float]]]:
    """Charge un cas VitalDB (1 Hz). Renvoie None si indisponible."""
    try:
        import numpy as np
        import vitaldb  # type: ignore
    except ImportError:
        logger.info("Paquet vitaldb absent → données synthétiques")
        return None
    try:
        arr = _with_timeout(vitaldb.load_case, timeout_s, caseid, list(TRACKS.values()), 1)
    except Exception as exc:
        logger.info("VitalDB indisponible (%s) → données synthétiques", exc.__class__.__name__)
        return None
    if arr is None or len(arr) == 0:
        return None
    arr = np.asarray(arr, dtype=float)[:seconds]
    out: dict[str, list[float]] = {}
    for i, key in enumerate(TRACKS):
        col = arr[:, i] if arr.ndim == 2 and arr.shape[1] > i else np.array([])
        vals = [float(v) for v in col if not math.isnan(v)]
        if len(vals) < 30:
            return None
        out[key] = vals
    logger.info("VitalDB cas %s chargé (%d s)", caseid, len(out["hr"]))
    return out


def synthetic_track(seconds: int = 600, hr: float = 76, spo2: float = 97, sys: float = 122, dia: float = 76, seed: int | None = None) -> dict[str, list[float]]:
    """Série synthétique plausible : respiration sinusoïdale + marche aléatoire bornée."""
    rnd = random.Random(seed)
    out = {"hr": [], "spo2": [], "sys": [], "dia": []}
    h, s, sy, di = hr, spo2, sys, dia
    for t in range(seconds):
        h += rnd.gauss(0, 0.6) + 0.02 * (hr - h) + 1.2 * math.sin(t / 7.0) * 0.1
        s += rnd.gauss(0, 0.15) + 0.05 * (spo2 - s)
        sy += rnd.gauss(0, 1.0) + 0.03 * (sys - sy)
        di += rnd.gauss(0, 0.7) + 0.03 * (dia - di)
        out["hr"].append(round(max(40, min(160, h)), 1))
        out["spo2"].append(round(max(85, min(100, s)), 1))
        out["sys"].append(round(max(80, min(190, sy)), 1))
        out["dia"].append(round(max(45, min(110, min(di, sy - 25))), 1))
    return out


class VitalReplayer:
    """Itère sur une série (réelle ou synthétique) en boucle, avec un décalage par patient."""

    def __init__(self, caseid: int = 1, seconds: int = 600, use_vitaldb: bool = True, **synthetic_kwargs: Any):
        data = load_case(caseid, seconds) if use_vitaldb else None
        self.source = "vitaldb" if data else "synthetic"
        self.data = data or synthetic_track(seconds, **synthetic_kwargs)
        self.i = 0
        self.n = len(self.data["hr"])

    def next(self) -> dict[str, float]:
        v = {k: self.data[k][self.i % len(self.data[k])] for k in self.data}
        self.i += 1
        return v

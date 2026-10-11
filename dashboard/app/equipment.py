"""
Pannes d'équipement (`machine_error` d'Amal 384ae87, relié à nos appareils médicaux).

Deux sources donnent la même chose, une panne rattachée à un appareil de la chambre :
- le flux de l'appareil lui-même (`hackcure/room/{room}/device/{id}` avec un champ `fault`) ;
- l'événement `machine_error` du pipeline d'Amal (`/api/demo/trigger`, `/api/yolo/event`), dont le libellé
  (« IV Pump », « ECG Monitor »…) est rapproché de nos types d'appareil.

L'état vit dans `room_state["deviceFaults"]` : {type d'appareil: {code, label, device, since, source}}.
Le VitalsAgent en fait UN risque « equipment_fault » par chambre. L'occlusion et la poche vide de la pompe à
perfusion restent les risques `iv_occlusion` / `iv_empty` : elles ne sont jamais comptées comme une panne.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from .ingest import handler

# libellés du pipeline d'Amal → nos types d'appareil
MACHINE_TYPES = {
    "iv pump": "iv_pump", "infusion pump": "nutrition_pump", "ecg monitor": "ecg", "blood pressure monitor": "bp", "blood pressure": "bp",
    "thermometer": "thermometer", "oxygen": "oxygen", "pulse oximeter": "spo2", "glucometer": "glucometer", "transfusion": "transfusion", "urine bag": "urine_bag",
}
LABELS = {
    "iv_pump": "Pompe à perfusion", "nutrition_pump": "Pompe de nutrition", "transfusion": "Transfusion", "bp": "Tensiomètre", "ecg": "Moniteur ECG",
    "oxygen": "Oxygène", "spo2": "Oxymètre de pouls", "thermometer": "Thermomètre", "glucometer": "Glucomètre", "urine_bag": "Poche à urine", "other": "Équipement",
}
FAULTS = {
    "power": "défaut d'alimentation", "motor": "défaut moteur", "sensor": "capteur déconnecté", "calibration": "erreur de calibration",
    "battery": "batterie faible", "comm": "perte de communication", "reported": "panne signalée",
}
VITAL = {"oxygen", "ecg", "spo2", "transfusion", "iv_pump"}  # appareil dont l'arrêt met le patient en danger : sévérité élevée
IV_MERGED = {"occlusion", "empty"}  # déjà couverts par iv_occlusion / iv_empty


def device_type(machine_type: str) -> str:
    key = (machine_type or "").strip().lower()
    if key in LABELS:
        return key
    return MACHINE_TYPES.get(key, "other")


def is_fault(dtype: str, fault: Any) -> bool:
    """Vrai si le champ `fault` d'un message d'appareil est une panne (et pas une alarme de perfusion déjà gérée)."""
    return isinstance(fault, dict) and bool(fault.get("code")) and not (dtype == "iv_pump" and fault.get("code") in IV_MERGED)


def faults(room: str) -> dict[str, dict[str, Any]]:
    return handler.room_state(room).setdefault("deviceFaults", {})


def register(room: str, dtype: str, code: str, label: str = "", source: str = "device") -> bool:
    """Enregistre une panne ; renvoie True si l'état de la chambre a changé."""
    f = faults(room)
    text = (label or "").strip() or FAULTS.get(code, FAULTS["reported"])
    cur = f.get(dtype)
    if cur and cur["code"] == code and cur["label"] == text:
        return False
    f[dtype] = {"code": code, "label": text, "device": f"{room}-{dtype}", "name": LABELS.get(dtype, LABELS["other"]), "since": (cur or {}).get("since") or time.time(), "source": (cur or {}).get("source") or source}
    handler._dirty_rooms.add(room)
    return True


def clear(room: str, dtype: Optional[str] = None, source: Optional[str] = None) -> bool:
    """Lève la panne d'un appareil (ou toutes celles d'une source) ; renvoie True si quelque chose a changé."""
    f = faults(room)
    gone = [k for k, v in f.items() if (dtype is None or k == dtype) and (source is None or v.get("source") == source)]
    for k in gone:
        del f[k]
    if gone:
        handler._dirty_rooms.add(room)
    return bool(gone)


def describe(f: dict[str, dict[str, Any]]) -> str:
    return " ; ".join(f"{v['name']} ({v['label']})" for v in f.values())


def severity(f: dict[str, dict[str, Any]]) -> str:
    return "high" if any(k in VITAL for k in f) else "medium"

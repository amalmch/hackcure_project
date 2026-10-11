"""
NEWS2 (National Early Warning Score 2) — calcul déterministe.

Échelle SpO2 1 (standard) ou 2 (`spo2_scale2=True` : patient BPCO, cible 88–92 %). `consciousness` : 'A' (alerte) ou 'CVPU' (confus / voix / douleur / aréactif).
Référence : Royal College of Physicians, NEWS2 (2017).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class News2Result:
    score: int
    band: str  # low | low_medium | medium | high
    components: dict[str, int] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    red_flag: bool = False  # un paramètre isolé à 3

    def to_dict(self) -> dict:
        return {"score": self.score, "band": self.band, "components": self.components, "missing": self.missing, "red_flag": self.red_flag}


def score_rr(rr: float) -> int:
    if rr <= 8:
        return 3
    if rr <= 11:
        return 1
    if rr <= 20:
        return 0
    if rr <= 24:
        return 2
    return 3


def score_spo2(spo2: float) -> int:
    if spo2 <= 91:
        return 3
    if spo2 <= 93:
        return 2
    if spo2 <= 95:
        return 1
    return 0


def score_spo2_scale2(spo2: float, on_oxygen: bool) -> int:
    """Échelle 2 du NEWS2 : la cible est 88–92 % ; une SpO2 haute SOUS oxygène est pénalisée."""
    if spo2 <= 83:
        return 3
    if spo2 <= 85:
        return 2
    if spo2 <= 87:
        return 1
    if spo2 <= 92 or not on_oxygen:
        return 0
    if spo2 <= 94:
        return 1
    if spo2 <= 96:
        return 2
    return 3


def score_sbp(sbp: float) -> int:
    if sbp <= 90:
        return 3
    if sbp <= 100:
        return 2
    if sbp <= 110:
        return 1
    if sbp <= 219:
        return 0
    return 3


def score_hr(hr: float) -> int:
    if hr <= 40:
        return 3
    if hr <= 50:
        return 1
    if hr <= 90:
        return 0
    if hr <= 110:
        return 1
    if hr <= 130:
        return 2
    return 3


def score_temp(temp: float) -> int:
    if temp <= 35.0:
        return 3
    if temp <= 36.0:
        return 1
    if temp <= 38.0:
        return 0
    if temp <= 39.0:
        return 1
    return 2


def news2(
    rr: Optional[float] = None,
    spo2: Optional[float] = None,
    on_oxygen: bool = False,
    sbp: Optional[float] = None,
    hr: Optional[float] = None,
    temp: Optional[float] = None,
    consciousness: str = "A",
    spo2_scale2: bool = False,
) -> News2Result:
    comps: dict[str, int] = {}
    missing: list[str] = []
    spo2_fn = (lambda v: score_spo2_scale2(v, on_oxygen)) if spo2_scale2 else score_spo2
    for key, val, fn in (("rr", rr, score_rr), ("spo2", spo2, spo2_fn), ("sbp", sbp, score_sbp), ("hr", hr, score_hr), ("temp", temp, score_temp)):
        if val is None:
            missing.append(key)
        else:
            comps[key] = fn(float(val))
    comps["oxygen"] = 2 if on_oxygen else 0
    comps["consciousness"] = 0 if str(consciousness).upper().startswith("A") else 3
    total = sum(comps.values())
    red_flag = any(v == 3 for k, v in comps.items() if k not in ("oxygen",))
    if total >= 7:
        band = "high"
    elif total >= 5:
        band = "medium"
    elif red_flag:
        band = "low_medium"
    else:
        band = "low"
    return News2Result(score=total, band=band, components=comps, missing=missing, red_flag=red_flag)


BAND_LABELS = {"low": "faible", "low_medium": "faible-moyen (paramètre isolé à 3)", "medium": "moyen", "high": "élevé"}

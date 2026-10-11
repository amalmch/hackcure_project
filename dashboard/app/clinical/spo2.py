"""
Saturation en oxygène (SpO2) — classification déterministe (V2, étape 6).

Patient standard : < 94 % attention · < 90 % risque élevé · < 88 % ou chute rapide critique.
Patient BPCO (cible 88–92 %) : < 88 % attention · < 85 % risque élevé · < 83 % ou chute rapide critique.
« Chute rapide » : perte d'au moins 4 points en une minute alors que la valeur est déjà sous la cible.
"""

from __future__ import annotations

from typing import Any, Optional

RAPID_DROP_POINTS = 4.0
SEVERITY = {"attention": "medium", "high": "high", "critical": "critical"}
LEVEL_LABELS = {"none": "dans la cible", "attention": "attention", "high": "risque élevé", "critical": "critique"}


def is_copd(patient: Optional[dict[str, Any]]) -> bool:
    hist = ((patient or {}).get("history") or "").lower()
    return "bpco" in hist or "copd" in hist or "bronchopneumopathie" in hist


def thresholds(copd: bool = False) -> dict[str, float]:
    return {"attention": 88.0, "high": 85.0, "critical": 83.0, "target_low": 88.0, "target_high": 92.0} if copd else \
           {"attention": 94.0, "high": 90.0, "critical": 88.0, "target_low": 94.0, "target_high": 100.0}


def classify(spo2: Optional[float], copd: bool = False, drop_per_min: Optional[float] = None) -> dict[str, Any]:
    """Renvoie {level, severity, reason, target, copd}. `drop_per_min` : points perdus sur la dernière minute (positif = baisse)."""
    th = thresholds(copd)
    target = f"{th['target_low']:.0f}–{th['target_high']:.0f} %" if copd else f"≥ {th['target_low']:.0f} %"
    out: dict[str, Any] = {"level": "none", "severity": None, "reason": "", "target": target, "copd": copd, "thresholds": th}
    if spo2 is None:
        return out
    s = float(spo2)
    rapid = drop_per_min is not None and drop_per_min >= RAPID_DROP_POINTS and s < th["attention"]
    if s < th["critical"] or rapid:
        level = "critical"
        reason = f"SpO2 {s:.0f} % < {th['critical']:.0f} %" if s < th["critical"] else f"chute rapide de {drop_per_min:.0f} points en 1 min (SpO2 {s:.0f} %)"
    elif s < th["high"]:
        level, reason = "high", f"SpO2 {s:.0f} % < {th['high']:.0f} %"
    elif s < th["attention"]:
        level, reason = "attention", f"SpO2 {s:.0f} % < {th['attention']:.0f} %"
    else:
        return out
    out.update(level=level, severity=SEVERITY[level], reason=reason + (f" (BPCO, cible {target})" if copd else f" (cible {target})"))
    return out

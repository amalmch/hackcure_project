"""
Fièvre vraie ≠ simple hausse thermique — distinction déterministe (V2, étape 3).

- **Fièvre** : température **centrale** (thermomètre) ≥ 38,0 °C (confirmée sur plusieurs lectures), ou ≥ 37,8 °C à
  deux reprises espacées dans l'heure. La température cutanée de la caméra thermique ne suffit JAMAIS seule.
- **Simple hausse thermique** : température cutanée ou ambiante élevée avec une température centrale normale,
  souvent corrélée à une chambre trop chaude.

Fonctions pures, testables sans serveur.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

FEVER_C = 38.0          # seuil franc
SUBFEVER_C = 37.8       # seuil « à deux reprises en 1 h »
CONFIRM_READINGS = 3    # lectures consécutives ≥ 38,0 °C (anti-bruit)
WINDOW_S = 3600.0
SKIN_RISE_C = 37.6      # température cutanée (caméra thermique) élevée
ROOM_HOT_C = 26.5       # ambiance trop chaude


def assess(core_history: Sequence[tuple[float, float]], now: float, skin_temp: Optional[float] = None, env_temp: Optional[float] = None, repeat_gap_s: float = 600.0) -> dict[str, Any]:
    """`core_history` : [(horodatage, °C)] du thermomètre, ordre chronologique.
    Renvoie {kind: 'fever' | 'thermal_rise' | 'none', criterion, core, skin, env}."""
    recent = [(t, v) for t, v in core_history if now - t <= WINDOW_S]
    core = recent[-1][1] if recent else None
    out: dict[str, Any] = {"kind": "none", "criterion": "", "core": core, "skin": skin_temp, "env": env_temp}
    if core is not None:
        last = [v for _, v in recent[-CONFIRM_READINGS:]]
        if len(last) >= CONFIRM_READINGS and all(v >= FEVER_C for v in last):
            out.update(kind="fever", criterion=f"température centrale ≥ {FEVER_C:.1f} °C ({core:.1f} °C, confirmée sur {CONFIRM_READINGS} lectures)")
            return out
        if core >= SUBFEVER_C:
            earlier = [t for t, v in recent if v >= SUBFEVER_C and recent[-1][0] - t >= repeat_gap_s]
            if earlier:
                minutes = (recent[-1][0] - earlier[0]) / 60.0
                out.update(kind="fever", criterion=f"température centrale ≥ {SUBFEVER_C:.1f} °C à deux reprises en 1 h ({core:.1f} °C, premier relevé il y a {minutes:.0f} min)")
                return out
    core_normal = core is None or core < SUBFEVER_C
    if core_normal and ((skin_temp is not None and skin_temp >= SKIN_RISE_C) or (env_temp is not None and env_temp >= ROOM_HOT_C)):
        why = []
        if skin_temp is not None and skin_temp >= SKIN_RISE_C:
            why.append(f"température cutanée {skin_temp:.1f} °C")
        if env_temp is not None and env_temp >= ROOM_HOT_C:
            why.append(f"chambre à {env_temp:.1f} °C")
        core_txt = f"température centrale normale ({core:.1f} °C)" if core is not None else "température centrale non mesurée"
        out.update(kind="thermal_rise", criterion=" et ".join(why) + f", {core_txt}")
    return out


def qsofa(rr: Optional[float], sbp: Optional[float], altered_mentation: bool = False) -> dict[str, Any]:
    """quick SOFA : FR ≥ 22/min, PAS ≤ 100 mmHg, altération de la conscience. ≥ 2 = risque de sepsis."""
    items = {"fr_ge_22": bool(rr is not None and rr >= 22), "pas_le_100": bool(sbp is not None and sbp <= 100), "conscience_alteree": bool(altered_mentation)}
    score = sum(items.values())
    return {"score": score, "items": items, "positive": score >= 2}


# Checklist d'examen clinique présentée au médecin de garde
CHECKLIST = [
    ("foyer", "Recherche d'un foyer infectieux (pulmonaire, urinaire, ORL, digestif, cutané)"),
    ("conscience", "État de conscience (orientation, Glasgow)"),
    ("hydratation", "Hydratation (muqueuses, pli cutané, diurèse)"),
    ("catheters", "Cathéters et voies veineuses (point de ponction, date de pose)"),
    ("plaie", "Plaie opératoire ou escarre (rougeur, écoulement)"),
    ("sepsis", "Signes de sepsis : qSOFA et NEWS2 recalculés"),
    ("allergies", "Allergies et traitements en cours vérifiés"),
]

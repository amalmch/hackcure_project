"""
Résolution des risques par un soignant (V2, étape 1).

Chaque type de risque a un scénario de résolution `simulator/scenarios/*_resolves.yaml` (champ `resolves`)
et un rôle intervenant (`role` : infirmier, médecin de garde…). En **simulation**, cliquer « Je prends en
charge » lance ce scénario dans la chambre : l'avatar du soignant entre, agit, reste visible au moins 45 s,
puis sort ; la sortie déclenche la revérification déterministe (FollowUpAgent ou n8n `risk-verify`).

En **vision réelle** (un edge parle pour la chambre), rien n'est simulé : c'est la deuxième personne
détectée par la caméra qui compte.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .config import settings

logger = logging.getLogger("hackcure.resolutions")

ROLE_LABELS = {"nurse": "infirmier(ère)", "duty_doctor": "médecin de garde", "general_doctor": "médecin", "psychiatrist": "psychiatre", "pharmacist": "pharmacien"}
DEFAULT_RESOLUTION = "visit_resolves"
_catalog: Optional[dict[str, dict[str, Any]]] = None


def catalog() -> dict[str, dict[str, Any]]:
    """type de risque → {scenario, role, description, duration} (lu dans les YAML, mis en cache)."""
    global _catalog
    if _catalog is None:
        from .sim import embedded

        _catalog = {}
        for sc in embedded.available_scenarios():
            for rtype in sc.get("resolves") or []:
                _catalog[rtype] = {"scenario": sc["name"], "role": sc.get("role") or "nurse", "description": sc.get("description", ""), "duration": sc.get("duration", 0)}
    return _catalog


def plan_for(risk_type: str) -> dict[str, Any]:
    cat = catalog()
    if risk_type in cat:
        return cat[risk_type]
    return {"scenario": DEFAULT_RESOLUTION, "role": "nurse", "description": "Visite et évaluation par un soignant.", "duration": 50}


def simulated(room: str) -> bool:
    """Vrai si la chambre est pilotée par le simulateur embarqué (pas par un edge réel)."""
    from .ingest import handler
    from .sim import embedded

    return embedded.engine is not None and room not in embedded._real_edge_rooms and not handler.edge_alive(room)


def start_for(room: str, risk_type: str, by_role: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Lance l'intervention simulée pour ce risque. Renvoie None en vision réelle ou sans simulateur."""
    if not settings.auto_resolution or not simulated(room):
        return None
    from .sim import embedded

    plan = plan_for(risk_type)
    # un médecin qui prend lui-même en charge se déplace lui-même ; sinon c'est le rôle prévu par le scénario
    role = by_role if by_role in ("duty_doctor", "general_doctor", "psychiatrist") else plan["role"]
    try:
        sc = embedded.engine.start_resolution(plan["scenario"], room, role)
    except FileNotFoundError:
        logger.warning("Scénario de résolution introuvable : %s", plan["scenario"])
        return None
    return {"scenario": sc.name, "role": sc.role, "role_label": ROLE_LABELS.get(sc.role, sc.role), "duration": sc.duration, "description": sc.description}

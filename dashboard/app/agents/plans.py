"""Libellés, règles de sévérité déterministes et plans d'action de secours (par type de risque)."""

from __future__ import annotations

from typing import Any

TYPE_LABELS: dict[str, str] = {
    "fall": "Chute",
    "call": "Appel du patient",
    "pain": "Douleur visible",
    "unaccompanied_bed_exit": "Lever non accompagné",
    "bed_exit": "Sortie du lit (patient à risque)",
    "toilet_too_long": "Toilettes trop longues",
    "patient_out_of_room": "Patient hors de la chambre",
    "fever": "Fièvre",
    "hypothermia": "Hypothermie",
    "tachycardia": "Tachycardie",
    "bradycardia": "Bradycardie",
    "hypoxemia": "Désaturation",
    "hypotension": "Hypotension",
    "hypertension": "Hypertension sévère",
    "tachypnea": "Polypnée",
    "news2_high": "Score NEWS2 élevé",
    "sepsis_trend": "Tendance évocatrice de sepsis",
    "iv_empty": "Perfusion presque vide",
    "iv_occlusion": "Occlusion de perfusion",
    "transfusion_reaction": "Réaction transfusionnelle",
    "thermal_discomfort": "Inconfort thermique",
    "local_alarm": "Alarme locale (edge)",
    "behavioral_risk": "Comportement à risque (vision)",
    "equipment_fault": "Panne d'équipement",
    "medication_late": "Prise de médicament en retard",
    "psych_alert": "Alerte psychiatrique (idées suicidaires déclarées)",
    "psych_low_wellbeing": "Bien-être psychologique bas",
    "predicted_seizure": "Prédiction — crise d'épilepsie",
    "predicted_sepsis": "Prédiction — sepsis / choc septique",
    "predicted_cardiac": "Prédiction — événement cardiaque",
    "predicted_deterioration": "Prédiction — détérioration générale",
    "predicted_glycemia": "Prédiction — complication du diabète",
}

# Sévérité déterministe : fonction(détails) -> low|medium|high|critical
def severity_for(rtype: str, details: dict[str, Any], patient: dict[str, Any] | None = None) -> str:
    patient = patient or {}
    high_fall_risk = patient.get("fall_risk") == "high"
    if rtype in ("fall", "transfusion_reaction", "psych_alert"):
        return "critical"
    if rtype.startswith("predicted_"):  # niveau fixé par clinical/prediction.py : critique à partir de 80/100
        return "critical" if int(details.get("risk") or 0) >= 80 else "high"
    if rtype == "behavioral_risk":
        return {"critical": "critical", "high": "high"}.get(str(details.get("risk_level")), "medium")
    if rtype == "equipment_fault":  # fixé par app/equipment.py : élevé si un appareil vital est en panne
        return "high" if details.get("severity") == "high" else "medium"
    if rtype == "news2_high":
        s = int(details.get("news2", 0))
        return "critical" if s >= 7 else ("high" if s >= 5 else "medium")
    if rtype == "hypoxemia":  # niveau fixé par clinical/spo2.py (seuils standard ou BPCO, chute rapide)
        return {"attention": "medium", "high": "high", "critical": "critical"}.get(str(details.get("level")), "high")
    if rtype in ("call", "pain", "iv_occlusion", "sepsis_trend", "hypotension", "hypertension", "hypothermia"):
        return "high"
    if rtype == "fever":  # fièvre vraie (température centrale) : élevée si ≥ 39 °C ou qSOFA ≥ 2
        t = float(details.get("tempC") or 38.0)
        return "high" if (t >= 39.0 or int(details.get("qsofa") or 0) >= 2) else "medium"
    if rtype in ("tachycardia", "bradycardia"):
        hr = float(details.get("hr", 100))
        return "high" if (hr > 130 or hr < 40) else "medium"
    if rtype == "unaccompanied_bed_exit":
        return "high" if high_fall_risk else "medium"
    if rtype == "bed_exit":
        return "medium" if high_fall_risk else "low"
    if rtype in ("toilet_too_long", "patient_out_of_room", "iv_empty", "tachypnea"):
        return "medium"
    if rtype == "thermal_discomfort":
        t = details.get("tempC")
        return "medium" if (t is not None and (t > 30 or t < 16)) else "low"
    if rtype == "local_alarm":
        return "critical" if details.get("reason") == "fall" else "high"
    return "medium"


FALLBACK_PLANS: dict[str, list[dict[str, Any]]] = {
    "fall": [
        {"text": "Se rendre immédiatement en chambre ; ne pas relever le patient seul avant évaluation."},
        {"text": "Évaluer conscience, douleur, déformation d'un membre, traumatisme crânien (anticoagulants ?)."},
        {"text": "Prendre les constantes : PA, FC, SpO2, glycémie si diabétique."},
        {"text": "Prévenir le médecin de garde ; demander une imagerie si suspicion de fracture ou de TC."},
        {"text": "Réinstaller en sécurité (barrières, sonnette à portée, veilleuse) et tracer la chute."},
    ],
    "call": [
        {"text": "Répondre à l'appel en chambre dans les 2 minutes."},
        {"text": "Identifier le besoin (douleur, toilettes, inconfort, perfusion)."},
        {"text": "Prendre les constantes si plainte somatique."},
        {"text": "Tracer l'intervention et réarmer l'appel."},
    ],
    "pain": [
        {"text": "Évaluer la douleur (EVA / Algoplus) et sa localisation."},
        {"text": "Vérifier la prescription antalgique en cours et les allergies."},
        {"text": "Administrer l'antalgique prescrit ou appeler le médecin si absence de prescription adaptée."},
        {"text": "Réévaluer la douleur à 30–60 min."},
    ],
    "unaccompanied_bed_exit": [
        {"text": "Se rendre en chambre pour accompagner le patient (risque de chute)."},
        {"text": "Vérifier l'orientation, la glycémie si diabétique, le besoin (toilettes)."},
        {"text": "Allumer la veilleuse, remettre les barrières et la sonnette à portée."},
        {"text": "Noter l'épisode dans le rapport de garde."},
    ],
    "bed_exit": [
        {"text": "Vérifier visuellement la stabilité du patient."},
        {"text": "Proposer une aide à la marche si besoin."},
        {"text": "Tracer l'épisode."},
    ],
    "toilet_too_long": [
        {"text": "Vérifier le patient aux toilettes (appel vocal puis entrée)."},
        {"text": "Rechercher malaise, chute, difficulté à se relever."},
        {"text": "Réinstaller et tracer."},
    ],
    "patient_out_of_room": [
        {"text": "Localiser le patient (couloir, accueil, extérieur)."},
        {"text": "Vérifier son état et le raccompagner."},
        {"text": "Prévenir l'équipe si patient désorienté."},
    ],
    "fever": [
        {"text": "Contrôler la température au thermomètre (confirmer la caméra thermique)."},
        {"text": "Prendre PA, FC, FR, SpO2 ; calculer NEWS2."},
        {"text": "Rechercher un foyer : perfusion, urines, respiratoire, cicatrice."},
        {"text": "Vérifier les allergies puis antipyrétique selon prescription ; hémocultures si T° ≥ 38,5 °C selon protocole."},
        {"text": "Prévenir le médecin de garde si T° ≥ 39 °C ou NEWS2 ≥ 5."},
    ],
    "sepsis_trend": [
        {"text": "Prendre un jeu complet de constantes et calculer NEWS2 maintenant."},
        {"text": "Prévenir le médecin de garde immédiatement (suspicion de sepsis)."},
        {"text": "Préparer un accès veineux, prélever hémocultures et lactates selon prescription."},
        {"text": "Surveillance rapprochée toutes les 15 min."},
    ],
    "news2_high": [
        {"text": "Prévenir le médecin de garde (NEWS2 élevé) sans délai."},
        {"text": "Surveillance continue : FC, SpO2, PA, FR, conscience."},
        {"text": "Oxygénothérapie selon prescription si SpO2 < cible."},
        {"text": "Préparer un éventuel transfert en unité de surveillance."},
    ],
    "equipment_fault": [
        {"text": "Aller voir le patient : vérifier son état sans se fier à l'appareil en panne (mesure manuelle si besoin)."},
        {"text": "Vérifier l'appareil : alimentation, câbles, capteurs, message d'erreur affiché."},
        {"text": "Remplacer par un appareil de la salle Équipements (étage 1) et contrôler son fonctionnement."},
        {"text": "Étiqueter l'appareil défectueux et prévenir le service biomédical."},
    ],
    "iv_empty": [
        {"text": "Vérifier la poche de perfusion et le débit."},
        {"text": "Préparer la poche suivante selon prescription (vérifier allergies et compatibilités)."},
        {"text": "Remplacer la poche avant la fin, purger si nécessaire."},
    ],
    "iv_occlusion": [
        {"text": "Vérifier la ligne : clamp, coudure, position du bras, site d'insertion."},
        {"text": "Rincer selon protocole ; reposer la voie si infiltration."},
        {"text": "Relancer la pompe et contrôler le débit."},
    ],
    "transfusion_reaction": [
        {"text": "ARRÊTER la transfusion immédiatement, garder la voie avec NaCl 0,9 %."},
        {"text": "Prendre les constantes, prévenir le médecin de garde en urgence."},
        {"text": "Conserver la poche et la tubulure ; prélever selon protocole hémovigilance."},
        {"text": "Déclarer l'incident."},
    ],
    "thermal_discomfort": [
        {"text": "Vérifier la température de la chambre et l'état de la fenêtre."},
        {"text": "Activer chauffage / climatisation (EnvironmentAgent) ou ajuster la couverture."},
        {"text": "Contrôler le confort du patient."},
    ],
    "hypoxemia": [
        {"text": "Vérifier le capteur SpO2 et la position du patient (demi-assis)."},
        {"text": "Oxygène selon prescription ; prévenir le médecin si SpO2 < 90 % persistante."},
        {"text": "Surveiller FR et conscience."},
    ],
    "hypotension": [
        {"text": "Contrôler la PA manuellement, allonger le patient, jambes surélevées."},
        {"text": "Prévenir le médecin de garde ; vérifier les traitements hypotenseurs."},
        {"text": "Surveillance rapprochée."},
    ],
    "default": [
        {"text": "Se rendre en chambre et évaluer le patient."},
        {"text": "Prendre les constantes et vérifier les équipements."},
        {"text": "Tracer l'intervention ; prévenir le médecin si anomalie."},
    ],
}
for _k, _v in list(FALLBACK_PLANS.items()):
    for _t in ("tachycardia", "bradycardia", "hypertension", "hypothermia", "tachypnea", "local_alarm"):
        FALLBACK_PLANS.setdefault(_t, FALLBACK_PLANS["default"])

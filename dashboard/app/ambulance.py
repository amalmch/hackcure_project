"""
Ambulances en temps réel (V2, étape 5) : géométrie, trajets simulés, réservation de chambre, préparation.

- Clinique : coordonnées FICTIVES à Tunis (quartier du Lac).
- **Mode simulé** : l'ambulance suit une polyligne réaliste à vitesse variable (repli quand aucun service de routage
  n'est accessible : les trajets sont embarqués).
- **Mode réel** : un téléphone de l'équipe ouvre `/ambulance/track/{jeton}` et envoie sa position GPS toutes les 2 s.
- Dès que l'ambulance démarre, une chambre adaptée est réservée et l'équipe est prévenue avec la préparation à faire.
"""

from __future__ import annotations

import math
from typing import Any, Optional

CLINIC = {"name": "Clinique HackCure", "lat": 36.8380, "lon": 10.2390}  # coordonnées fictives (Tunis, Les Berges du Lac)

EMERGENCY_TYPES = {
    "trauma": "Traumatologie", "cardio": "Cardiologie", "stroke": "AVC", "respiratory": "Détresse respiratoire", "obstetric": "Obstétrique", "infection": "Infection / sepsis", "other": "Autre urgence",
}
SEVERITY = {1: "P1 — urgence vitale", 2: "P2 — urgence", 3: "P3 — urgence relative"}

# Préparation standard par type d'urgence (règles) : matériel, équipe, examens
PREPARATION: dict[str, dict[str, list[str]]] = {
    "trauma": {"materiel": ["Brancard et plan dur", "Attelles, collier cervical", "Voie veineuse, antalgiques"], "equipe": ["Médecin de garde", "Infirmier(ère) de la chambre", "Orthopédiste d'astreinte prévenu"],
               "examens": ["Radiographies du membre et du bassin", "NFS, groupe, RAI", "Scanner si traumatisme crânien"]},
    "cardio": {"materiel": ["Scope, défibrillateur à portée", "ECG 12 dérivations", "Oxygène, voie veineuse"], "equipe": ["Médecin de garde", "Cardiologue d'astreinte prévenu", "Infirmier(ère) de la chambre"],
               "examens": ["ECG à l'arrivée", "Troponine, ionogramme, NFS", "Échocardiographie"]},
    "stroke": {"materiel": ["Scope, glycémie capillaire", "Voie veineuse", "Lit à 30°"], "equipe": ["Médecin de garde", "Neurologue d'astreinte prévenu", "Radiologie prévenue (imagerie cérébrale)"],
               "examens": ["Score NIHSS", "Imagerie cérébrale en urgence", "Glycémie, NFS, coagulation"]},
    "respiratory": {"materiel": ["Oxygène, masque haute concentration", "Aérosols", "Scope, oxymètre de pouls"], "equipe": ["Médecin de garde", "Infirmier(ère) de la chambre", "Kinésithérapeute respiratoire"],
                    "examens": ["Gaz du sang", "Radiographie thoracique", "NFS, CRP"]},
    "obstetric": {"materiel": ["Monitoring fœtal", "Voie veineuse", "Kit d'accouchement"], "equipe": ["Médecin de garde", "Sage-femme / obstétricien d'astreinte prévenu"], "examens": ["Monitoring", "NFS, groupe, RAI", "Échographie"]},
    "infection": {"materiel": ["Voie veineuse, remplissage", "Hémocultures prêtes", "Scope"], "equipe": ["Médecin de garde", "Infirmier(ère) de la chambre"], "examens": ["Hémocultures, lactates", "NFS, CRP, procalcitonine", "ECBU, radiographie thoracique"]},
    "other": {"materiel": ["Scope, voie veineuse", "Chariot d'urgence à portée"], "equipe": ["Médecin de garde", "Infirmier(ère) de la chambre"], "examens": ["Bilan selon l'examen clinique"]},
}
# Ordre de préférence des chambres par type (la 101 est la chambre instrumentée, 101/102 sont les plus proches du poste de soins)
ROOM_PREFERENCE = {"cardio": ["101", "102", "103", "104"], "stroke": ["101", "102", "103", "104"], "respiratory": ["101", "102", "103", "104"], "trauma": ["104", "103", "102", "101"],
                   "obstetric": ["103", "104", "102", "101"], "infection": ["102", "101", "104", "103"], "other": ["104", "103", "102", "101"]}

# Trajets simulés vers la clinique (lat, lon) : départs réalistes autour de Tunis, polylignes embarquées
ROUTES: dict[str, dict[str, Any]] = {
    "marsa": {"label": "La Marsa → clinique", "points": [(36.8782, 10.3247), (36.8731, 10.3155), (36.8669, 10.3052), (36.8605, 10.2948), (36.8548, 10.2843), (36.8502, 10.2731), (36.8466, 10.2622), (36.8431, 10.2523), (36.8402, 10.2448), (36.8380, 10.2390)]},
    "centre": {"label": "Tunis centre → clinique", "points": [(36.8008, 10.1802), (36.8052, 10.1876), (36.8101, 10.1961), (36.8156, 10.2043), (36.8209, 10.2119), (36.8261, 10.2198), (36.8312, 10.2270), (36.8349, 10.2332), (36.8380, 10.2390)]},
    "ariana": {"label": "Ariana → clinique", "points": [(36.8665, 10.1934), (36.8621, 10.1998), (36.8573, 10.2071), (36.8527, 10.2146), (36.8484, 10.2221), (36.8443, 10.2290), (36.8409, 10.2344), (36.8380, 10.2390)]},
    "proche": {"label": "Les Berges du Lac → clinique (trajet court)", "points": [(36.8452, 10.2551), (36.8431, 10.2502), (36.8411, 10.2455), (36.8395, 10.2420), (36.8380, 10.2390)]},
}


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def route_length_m(points: list[tuple[float, float]]) -> float:
    return sum(haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1))


def position_at(points: list[tuple[float, float]], distance_m: float) -> tuple[float, float, float, float]:
    """Position (lat, lon), cap (degrés) et distance restante (m) après `distance_m` parcourus le long de la polyligne."""
    total = route_length_m(points)
    d = max(0.0, min(distance_m, total))
    acc = 0.0
    for i in range(len(points) - 1):
        seg = haversine_m(points[i], points[i + 1])
        if acc + seg >= d or i == len(points) - 2:
            f = 0.0 if seg <= 0 else min(1.0, (d - acc) / seg)
            lat = points[i][0] + (points[i + 1][0] - points[i][0]) * f
            lon = points[i][1] + (points[i + 1][1] - points[i][1]) * f
            heading = (math.degrees(math.atan2(points[i + 1][1] - points[i][1], points[i + 1][0] - points[i][0])) + 360) % 360
            return lat, lon, heading, total - d
        acc += seg
    return points[-1][0], points[-1][1], 0.0, 0.0


def speed_kmh(progress: float, seed: int = 0) -> float:
    """Vitesse variable le long du trajet : départ, portion rapide, ralentissements, approche de la clinique."""
    base = 34 + 22 * math.sin(math.pi * min(1.0, max(0.0, progress)))        # 34 → 56 → 34 km/h
    wobble = 7 * math.sin(progress * 23 + seed) + 4 * math.sin(progress * 61 + seed * 1.7)  # feux, circulation
    return max(14.0, base + wobble)


def eta_seconds(remaining_m: float, current_kmh: Optional[float]) -> float:
    v = max(18.0, min(70.0, (current_kmh or 40.0) * 0.6 + 40.0 * 0.4))  # lissage vers une vitesse moyenne urbaine
    return remaining_m / (v / 3.6)


def choose_room(emergency_type: str, free_rooms: list[str]) -> Optional[str]:
    for r in ROOM_PREFERENCE.get(emergency_type, ROOM_PREFERENCE["other"]):
        if r in free_rooms:
            return r
    return free_rooms[0] if free_rooms else None

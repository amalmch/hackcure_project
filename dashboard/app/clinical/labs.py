"""
Catalogue d'examens biologiques (code, libellé, unité, normes) + proposition déterministe d'un bilan
et génération de résultats **simulés** cohérents avec le contexte (données fictives de prototype).
"""

from __future__ import annotations

import random
from typing import Any, Optional

# code → (libellé, unité, borne basse, borne haute, décimales)
CATALOG: dict[str, tuple[str, str, Optional[float], Optional[float], int]] = {
    "HB": ("Hémoglobine", "g/dL", 12.0, 16.5, 1),
    "LEUCO": ("Leucocytes", "G/L", 4.0, 10.0, 1),
    "PNN": ("Polynucléaires neutrophiles", "G/L", 1.8, 7.5, 1),
    "PLAQ": ("Plaquettes", "G/L", 150.0, 400.0, 0),
    "CRP": ("CRP", "mg/L", 0.0, 5.0, 0),
    "PCT": ("Procalcitonine", "ng/mL", 0.0, 0.5, 2),
    "LACT": ("Lactates", "mmol/L", 0.5, 2.0, 1),
    "NA": ("Sodium", "mmol/L", 135.0, 145.0, 0),
    "K": ("Potassium", "mmol/L", 3.5, 5.0, 1),
    "CREAT": ("Créatinine", "µmol/L", 45.0, 105.0, 0),
    "UREE": ("Urée", "mmol/L", 2.5, 7.5, 1),
    "GLY": ("Glycémie", "g/L", 0.70, 1.10, 2),
    "HBA1C": ("HbA1c", "%", 4.0, 6.0, 1),
    "TROPO": ("Troponine T hs", "ng/L", 0.0, 14.0, 0),
    "BNP": ("NT-proBNP", "pg/mL", 0.0, 300.0, 0),
    "ASAT": ("ASAT", "UI/L", 5.0, 40.0, 0),
    "ALAT": ("ALAT", "UI/L", 5.0, 40.0, 0),
    "TP": ("Taux de prothrombine", "%", 70.0, 100.0, 0),
    "INR": ("INR", "", 0.8, 1.2, 2),
    "ALB": ("Albumine", "g/L", 35.0, 50.0, 0),
    "TSH": ("TSH", "mUI/L", 0.4, 4.0, 2),
    "LDL": ("LDL-cholestérol", "g/L", 0.0, 1.6, 2),
    "PH": ("pH artériel", "", 7.35, 7.45, 2),
    "PCO2": ("PaCO2", "mmHg", 35.0, 45.0, 0),
    "CETO": ("Cétonémie", "mmol/L", 0.0, 0.6, 1),
    "HEMOC": ("Hémocultures (2 paires)", "", None, None, 0),
    "ECBU": ("ECBU", "", None, None, 0),
}
PANELS = {"NFS": ["HB", "LEUCO", "PNN", "PLAQ"], "IONO": ["NA", "K", "CREAT", "UREE"]}


def label(code: str) -> str:
    return CATALOG[code][0] if code in CATALOG else code


def norm_text(code: str) -> str:
    _, unit, lo, hi, _ = CATALOG[code]
    if lo is None and hi is None:
        return "qualitatif"
    return f"{lo:g}–{hi:g} {unit}".strip()


def is_abnormal(code: str, value: Optional[float]) -> bool:
    _, _, lo, hi, _ = CATALOG[code]
    return value is not None and ((lo is not None and value < lo) or (hi is not None and value > hi))


def propose_fever_workup(patient: dict[str, Any], treatments: str, vitals: dict[str, Any], qsofa_score: int, has_iv: bool) -> list[dict[str, Any]]:
    """Bilan biologique proposé devant une fièvre vraie. Règles explicites : chaque examen porte son motif."""
    hist = (patient.get("history") or "").lower()
    tr = (treatments or "").lower()
    out: list[dict[str, Any]] = []

    def add(code: str, motif: str) -> None:
        if all(x["code"] != code for x in out):
            out.append({"code": code, "label": label(code), "motif": motif, "selected": True, "source": "règle"})

    for c in PANELS["NFS"]:
        add(c, "Numération : recherche d'une hyperleucocytose / neutropénie devant la fièvre.")
    add("CRP", "Syndrome inflammatoire : valeur de départ pour le suivi.")
    add("PCT", "Procalcitonine : orientation vers une infection bactérienne.")
    add("HEMOC", "Hémocultures avant toute antibiothérapie" + (" (voie veineuse en place)." if has_iv else "."))
    add("ECBU", "Foyer urinaire à éliminer" + (" (patient âgé)." if (patient.get("age") or 0) >= 70 else "."))
    if qsofa_score >= 1 or (vitals.get("sys") or 120) <= 100 or (vitals.get("hr") or 80) >= 110:
        add("LACT", f"Lactates : recherche d'une hypoperfusion (qSOFA {qsofa_score}).")
    for c in PANELS["IONO"]:
        add(c, "Ionogramme et fonction rénale : hydratation, adaptation des posologies.")
    if "diab" in hist or "metformine" in tr or "insuline" in tr:
        add("GLY", "Patient diabétique : la fièvre déséquilibre la glycémie.")
    if "bpco" in hist or "respiratoire" in hist:
        add("PH", "Insuffisant respiratoire : gaz du sang si aggravation de la dyspnée.")
        add("PCO2", "Insuffisant respiratoire : recherche d'une hypercapnie.")
    if "énoxaparine" in tr or "enoxaparine" in tr or "warfarine" in tr or "anticoag" in tr:
        add("PLAQ", "Sous anticoagulant : surveillance des plaquettes.")
    return out


def simulate(codes: list[str], scenario: str = "normal", seed: int = 0) -> list[dict[str, Any]]:
    """Résultats simulés. `scenario` : 'normal' | 'infection' | 'sepsis' | 'cardiac' | 'diabetes'. Déterministe pour une graine donnée."""
    rnd = random.Random(seed)
    shifts = {
        "infection": {"LEUCO": 14.8, "PNN": 11.6, "CRP": 96, "PCT": 0.9, "LACT": 1.6},
        "sepsis": {"LEUCO": 19.5, "PNN": 16.8, "CRP": 228, "PCT": 6.4, "LACT": 3.9, "CREAT": 148, "PLAQ": 128},
        "cardiac": {"TROPO": 186, "BNP": 1450},
        "diabetes": {"GLY": 3.2, "CETO": 2.1, "PH": 7.28, "K": 5.4},
    }.get(scenario, {})
    out = []
    for code in codes:
        if code not in CATALOG:
            continue
        name, unit, lo, hi, dec = CATALOG[code]
        if lo is None and hi is None:
            text = "en cours (résultat sous 48 h)" if code == "HEMOC" else ("leucocyturie 10⁴/mL, culture en cours" if scenario in ("infection", "sepsis") else "stérile")
            out.append({"code": code, "label": name, "value": None, "text": text, "unit": "", "ref_low": None, "ref_high": None, "abnormal": False})
            continue
        if code in shifts:
            value = shifts[code] * rnd.uniform(0.93, 1.07)
        else:
            value = lo + (hi - lo) * rnd.uniform(0.3, 0.7)
        value = round(value, dec) if dec else float(round(value))
        out.append({"code": code, "label": name, "value": value, "text": "", "unit": unit, "ref_low": lo, "ref_high": hi, "abnormal": is_abnormal(code, value)})
    return out

"""
Correspondance modèle de la plateforme → ressources HL7 FHIR R4 (JSON).

Fonctions pures : elles reçoivent des objets du modèle (ou de simples dictionnaires) et renvoient des dictionnaires FHIR.
Règles :
- l'identifiant FHIR du patient est son PSEUDONYME (`Patient.code`, ex. « PAT-0001 ») ; l'identité réelle (nom, date de naissance
  complète) n'est ajoutée que si l'appelant a le droit de la voir ;
- constantes vitales : codes LOINC + unités UCUM ; biologie : code local + code LOINC quand il est connu ;
- antécédents et allergies : texte libre dans la source → `code.text` seulement (aucun code SNOMED / CIM inventé).
"""

from __future__ import annotations

import base64
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

FHIR_MEDIA_TYPE = "application/fhir+json"
FHIR_VERSION = "4.0.1"
PSEUDONYM_SYSTEM = "urn:hackcure:pseudonym"
LAB_SYSTEM = "urn:hackcure:lab"
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
PSEUDONYMISED_TAG = {"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue", "code": "PSEUDED", "display": "pseudonymized"}

# métrique de la plateforme -> (slug de l'id, code LOINC, libellé LOINC, unité affichée, code UCUM, codes LOINC supplémentaires)
VITALS: dict[str, dict[str, Any]] = {
    "hr": {"slug": "heart-rate", "loinc": "8867-4", "display": "Heart rate", "unit": "/min", "ucum": "/min", "label": "Fréquence cardiaque"},
    "spo2": {"slug": "spo2", "loinc": "59408-5", "display": "Oxygen saturation in Arterial blood by Pulse oximetry", "unit": "%", "ucum": "%", "label": "Saturation en oxygène (SpO2)",
             "extra": [("2708-6", "Oxygen saturation in Arterial blood")]},
    "tempC": {"slug": "body-temperature", "loinc": "8310-5", "display": "Body temperature", "unit": "°C", "ucum": "Cel", "label": "Température corporelle"},
    "rr": {"slug": "respiratory-rate", "loinc": "9279-1", "display": "Respiratory rate", "unit": "/min", "ucum": "/min", "label": "Fréquence respiratoire"},
    # glycémie capillaire au lecteur (g/L sur la plateforme) : 41653-7, et non 2339-0 (sang veineux, mg/dL)
    "glucose": {"slug": "glucose", "loinc": "41653-7", "display": "Glucose [Mass/volume] in Capillary blood by Glucometer", "unit": "g/L", "ucum": "g/L", "label": "Glycémie capillaire"},
}
BP_PANEL = {"slug": "blood-pressure", "loinc": "85354-9", "display": "Blood pressure panel with all children optional", "label": "Pression artérielle"}
BP_COMPONENTS = {"sys": ("8480-6", "Systolic blood pressure"), "dia": ("8462-4", "Diastolic blood pressure")}
BP_OPTIONAL = {"map": ("8478-0", "Mean blood pressure")}

# code local de biologie -> (code LOINC, libellé) ; les examens absents de cette table ne portent que le code local
LAB_LOINC: dict[str, tuple[str, str]] = {
    "HB": ("718-7", "Hemoglobin [Mass/volume] in Blood"),
    "LEUCO": ("6690-2", "Leukocytes [#/volume] in Blood by Automated count"),
    "PNN": ("751-8", "Neutrophils [#/volume] in Blood by Automated count"),
    "PLAQ": ("777-3", "Platelets [#/volume] in Blood by Automated count"),
    "CRP": ("1988-5", "C reactive protein [Mass/volume] in Serum or Plasma"),
    "PCT": ("33959-8", "Procalcitonin [Mass/volume] in Serum or Plasma"),
    "LACT": ("2524-7", "Lactate [Moles/volume] in Serum or Plasma"),
    "NA": ("2951-2", "Sodium [Moles/volume] in Serum or Plasma"),
    "K": ("2823-3", "Potassium [Moles/volume] in Serum or Plasma"),
    "CREAT": ("14682-9", "Creatinine [Moles/volume] in Serum or Plasma"),
    "UREE": ("22664-7", "Urea [Moles/volume] in Serum or Plasma"),
    "GLY": ("2345-7", "Glucose [Mass/volume] in Serum or Plasma"),
    "HBA1C": ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood"),
    "TROPO": ("67151-1", "Troponin T.cardiac [Mass/volume] in Serum or Plasma by High sensitivity method"),
    "BNP": ("33762-6", "Natriuretic peptide.B prohormone N-Terminal [Mass/volume] in Serum or Plasma"),
    "ASAT": ("1920-8", "Aspartate aminotransferase [Enzymatic activity/volume] in Serum or Plasma"),
    "ALAT": ("1742-6", "Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma"),
    "INR": ("6301-6", "INR in Platelet poor plasma by Coagulation assay"),
    "ALB": ("1751-7", "Albumin [Mass/volume] in Serum or Plasma"),
    "TSH": ("3016-3", "Thyrotropin [Units/volume] in Serum or Plasma"),
    "PH": ("2744-1", "pH of Arterial blood"),
    "PCO2": ("2019-8", "Carbon dioxide [Partial pressure] in Arterial blood"),
}

# unité affichée par la plateforme -> code UCUM (les unités inconnues sont exportées sans `system` / `code`)
UCUM_UNITS = {
    "%": "%", "g/L": "g/L", "mg/L": "mg/L", "g/dL": "g/dL", "mg/dL": "mg/dL", "mmol/L": "mmol/L", "µmol/L": "umol/L", "umol/L": "umol/L", "ng/L": "ng/L", "ng/mL": "ng/mL", "pg/mL": "pg/mL",
    "G/L": "10*9/L", "UI/L": "U/L", "mUI/L": "m[IU]/L", "mmHg": "mm[Hg]", "°C": "Cel", "/min": "/min", "bpm": "/min",
}
ROUTES = {"PO": "voie orale", "IV": "voie intraveineuse", "SC": "voie sous-cutanée", "IM": "voie intramusculaire", "INH": "voie inhalée"}
ORDER_STATUS = {"draft": "draft", "active": "active", "stopped": "stopped"}
SNOMED = "http://snomed.info/sct"
# voies dont le code SNOMED CT est sans ambiguïté ; la voie inhalée reste en texte seul
ROUTE_SNOMED = {"PO": ("26643006", "Oral route"), "IV": ("47625008", "Intravenous route"), "SC": ("34206005", "Subcutaneous route"), "IM": ("78421000", "Intramuscular route")}
MEDREQ_CATEGORY = "http://terminology.hl7.org/CodeSystem/medicationrequest-category"
DOSE_TEXT_EXT = "urn:hackcure:fhir:dose-text"            # dose en texte quand elle ne se lit pas « nombre + unité »
FREQUENCY_TEXT_EXT = "urn:hackcure:fhir:frequency-text"  # fréquence en texte quand elle n'est pas reconnue
# unité de dose (en minuscules) -> code UCUM ; les autres unités (« bouffées », « cp ») sont exportées sans `system` / `code`
DOSE_UNITS = {"mg": "mg", "g": "g", "µg": "ug", "μg": "ug", "mcg": "ug", "ug": "ug", "ml": "mL", "l": "L", "ui": "[iU]", "mmol": "mmol"}
# nature du document -> (code LOINC, libellé LOINC, libellé français)
DOCUMENT_TYPES = {"report": ("11488-4", "Consult note", "Compte rendu médical"), "discharge": ("18842-5", "Discharge summary", "Compte rendu de sortie d'hospitalisation")}


# ─── utilitaires ─────────────────────────────────────────────────────────────
def iso(value: Any) -> Optional[str]:
    """Date/heure FHIR (`instant` / `dateTime`) : ISO 8601 avec fuseau, à la seconde. SQLite rend des dates naïves : elles sont en UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


def now_iso() -> str:
    return iso(datetime.now(timezone.utc))  # type: ignore[return-value]


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    """FHIR interdit les propriétés vides : on retire None, "", [] et {}."""
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def _ref(code: str) -> dict[str, str]:
    return {"reference": f"Patient/{code}"}


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return int(f) if f == int(f) else round(f, 3)


def quantity(value: Any, unit: str = "", ucum: Optional[str] = None) -> Optional[dict[str, Any]]:
    n = _num(value)
    if n is None:
        return None
    code = ucum if ucum is not None else UCUM_UNITS.get(unit)
    q: dict[str, Any] = {"value": n}
    if unit:
        q["unit"] = unit
    if code:
        q.update(system=UCUM, code=code)
    return q


def _category(code: str, display: str) -> list[dict[str, Any]]:
    return [{"coding": [{"system": OBS_CATEGORY, "code": code, "display": display}]}]


def split_history(text: str) -> list[str]:
    """Découpe les antécédents en texte libre (« A (x, y), B ; C ») sur les virgules et points-virgules HORS parenthèses."""
    out, buf, depth = [], "", 0
    for ch in text or "":
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch in ",;\n" and depth == 0:
            out.append(buf)
            buf = ""
        else:
            buf += ch
    out.append(buf)
    return [s.strip(" .") for s in out if s.strip(" .")]


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:24] or "x"


# ─── Patient ─────────────────────────────────────────────────────────────────
def patient_resource(p: Any, identity: bool = False) -> dict[str, Any]:
    """`identity=False` : ressource pseudonymisée (pas de nom, année de naissance seulement, étiquette de sécurité PSEUDED)."""
    meta: dict[str, Any] = {"lastUpdated": iso(getattr(p, "created_at", None)) or now_iso()}
    res: dict[str, Any] = {
        "resourceType": "Patient",
        "id": p.code,
        "meta": meta,
        "identifier": [{"system": PSEUDONYM_SYSTEM, "value": p.code}],
        "active": True,
        "gender": {"M": "male", "F": "female"}.get((p.sex or "").upper(), "unknown"),
    }
    birth = getattr(p, "birth_date", None)
    if identity:
        res["name"] = [{"use": "official", "family": p.last_name, "given": [p.first_name], "text": f"{p.first_name} {p.last_name}"}]
        if birth:
            res["birthDate"] = birth.isoformat()
    else:
        meta["security"] = [PSEUDONYMISED_TAG]
        if birth:
            res["birthDate"] = f"{birth.year:04d}"
    return res


# ─── Observation : constantes vitales ────────────────────────────────────────
def _vital_base(code: str, slug: str, effective: Optional[str], codings: list[dict[str, str]], text: str, device: Optional[str]) -> dict[str, Any]:
    when = effective or now_iso()
    return _clean({
        "resourceType": "Observation",
        "id": f"vital-{code}-{slug}",
        "meta": {"lastUpdated": when},
        "status": "final",
        "category": _category("vital-signs", "Vital Signs"),
        "code": {"coding": codings, "text": text},
        "subject": _ref(code),
        "effectiveDateTime": when,
        "device": {"display": device} if device else None,
    })


def vital_observations(code: str, values: dict[str, Any], times: Optional[dict[str, Any]] = None, devices: Optional[dict[str, str]] = None,
                       encounter_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Dernières constantes d'un patient → Observations `vital-signs`.

    `values` : {hr, spo2, sys, dia, map, tempC, rr, glucose} ; `times` : horodatage par métrique ; `devices` : appareil par métrique."""
    times, devices = times or {}, devices or {}
    out: list[dict[str, Any]] = []
    for metric, spec in VITALS.items():
        q = quantity(values.get(metric), spec["unit"], spec["ucum"])
        if q is None:
            continue
        codings = [{"system": LOINC, "code": spec["loinc"], "display": spec["display"]}] + [{"system": LOINC, "code": c, "display": d} for c, d in spec.get("extra", [])]
        obs = _vital_base(code, spec["slug"], iso(times.get(metric)), codings, spec["label"], devices.get(metric))
        obs["valueQuantity"] = q
        out.append(obs)
    components = []
    for metric, (loinc, display) in {**BP_COMPONENTS, **BP_OPTIONAL}.items():
        q = quantity(values.get(metric), "mmHg", "mm[Hg]")
        if q is not None:
            components.append({"code": {"coding": [{"system": LOINC, "code": loinc, "display": display}]}, "valueQuantity": q})
    if any(c["code"]["coding"][0]["code"] in ("8480-6", "8462-4") for c in components):
        obs = _vital_base(code, BP_PANEL["slug"], iso(times.get("sys") or times.get("dia")), [{"system": LOINC, "code": BP_PANEL["loinc"], "display": BP_PANEL["display"]}], BP_PANEL["label"],
                          devices.get("sys") or devices.get("dia"))
        obs["component"] = components
        out.append(obs)
    if encounter_id:
        for obs in out:
            obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}
    return out


# ─── Observation : biologie ──────────────────────────────────────────────────
def lab_observation(r: Any, code: str) -> dict[str, Any]:
    """Un `LabResult` → Observation `laboratory` (code local, + LOINC quand la correspondance est connue)."""
    codings = [{"system": LAB_SYSTEM, "code": r.code, "display": r.label or r.code}]
    if r.code in LAB_LOINC:
        codings.insert(0, {"system": LOINC, "code": LAB_LOINC[r.code][0], "display": LAB_LOINC[r.code][1]})
    when = iso(r.date) or now_iso()
    obs: dict[str, Any] = {
        "resourceType": "Observation",
        "id": f"lab-{r.id}",
        "meta": {"lastUpdated": when},
        "status": "final",
        "category": _category("laboratory", "Laboratory"),
        "code": {"coding": codings, "text": r.label or r.code},
        "subject": _ref(code),
        "effectiveDateTime": when,
    }
    q = quantity(r.value, r.unit or "")
    if q is not None:
        obs["valueQuantity"] = q
    elif r.text:
        obs["valueString"] = r.text
    else:
        obs["dataAbsentReason"] = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/data-absent-reason", "code": "unknown", "display": "Unknown"}]}
    low, high = quantity(r.ref_low, r.unit or ""), quantity(r.ref_high, r.unit or "")
    if q is not None and (low is not None or high is not None):
        obs["referenceRange"] = [_clean({"low": low, "high": high})]
    if q is not None:
        abnormal = bool(r.abnormal)
        obs["interpretation"] = [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation", "code": "A" if abnormal else "N", "display": "Abnormal" if abnormal else "Normal"}]}]
    return obs


# ─── Condition ───────────────────────────────────────────────────────────────
def _condition(code: str, rid: str, text: str, onset: Optional[str] = None, recorded: Optional[str] = None, category: str = "problem-list-item", note: str = "") -> dict[str, Any]:
    return _clean({
        "resourceType": "Condition",
        "id": rid,
        "meta": {"lastUpdated": recorded or onset or now_iso()},
        "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active", "display": "Active"}]},
        "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "confirmed", "display": "Confirmed"}]},
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category", "code": category,
                                  "display": "Problem List Item" if category == "problem-list-item" else "Encounter Diagnosis"}]}],
        "code": {"text": text},  # texte libre dans la source : pas de code SNOMED / CIM inventé
        "subject": _ref(code),
        "onsetDateTime": onset,
        "recordedDate": recorded,
        "note": [{"text": note}] if note else None,
    })


def condition_resources(p: Any, chronic_entries: Iterable[Any] = (), admission: Any = None) -> list[dict[str, Any]]:
    """Maladies chroniques du dossier (`MedicalRecordEntry` de type « chronique »), antécédents en texte libre (`Patient.history`)
    non déjà couverts, et motif de l'hospitalisation en cours."""
    out: list[dict[str, Any]] = []
    seen: list[str] = []
    for e in chronic_entries:
        try:
            data = json.loads(getattr(e, "data_json", "") or "{}")
        except ValueError:
            data = {}
        label = str(data.get("condition") or (e.title or "").replace("Diagnostic : ", "")).strip()
        if not label:
            continue
        seen.append(label.lower())
        out.append(_condition(p.code, f"cond-record-{e.id}", label, onset=iso(e.date), recorded=iso(e.date), note=f"Service : {e.service}" if getattr(e, "service", "") else ""))
    for i, part in enumerate(split_history(getattr(p, "history", "") or ""), start=1):
        low = part.lower()
        if any(s in low or low in s for s in seen):
            continue
        seen.append(low)
        out.append(_condition(p.code, f"cond-{p.code}-history-{i}", part, recorded=iso(getattr(p, "created_at", None)), note="Antécédent déclaré (texte libre)"))
    if admission is not None and (admission.reason or "").strip():
        out.append(_condition(p.code, f"cond-admission-{admission.id}", admission.reason.strip(), onset=iso(admission.admitted_at), recorded=iso(admission.admitted_at), category="encounter-diagnosis",
                              note="Motif d'hospitalisation"))
    return out


# ─── AllergyIntolerance ──────────────────────────────────────────────────────
def allergy_resources(p: Any, allergy_entries: Iterable[Any] = ()) -> list[dict[str, Any]]:
    """Allergies du patient (`Patient.allergies`, texte séparé par des virgules) complétées par les documents « allergie » du dossier."""
    found: dict[str, Optional[Any]] = {a: None for a in p.allergy_list}
    for e in allergy_entries:
        try:
            data = json.loads(getattr(e, "data_json", "") or "{}")
        except ValueError:
            data = {}
        name = str(data.get("allergen") or e.title or "").strip().lower()
        if name:
            found[name] = e.date
    out = []
    for i, (name, since) in enumerate(found.items(), start=1):
        out.append(_clean({
            "resourceType": "AllergyIntolerance",
            "id": f"allergy-{p.code}-{i}-{_slug(name)}",
            "meta": {"lastUpdated": iso(since) or iso(getattr(p, "created_at", None)) or now_iso()},
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active", "display": "Active"}]},
            "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification", "code": "confirmed", "display": "Confirmed"}]},
            "type": "allergy",
            "code": {"text": name},  # texte libre : pas de code inventé
            "patient": _ref(p.code),
            "onsetDateTime": iso(since),
            "recordedDate": iso(since) or iso(getattr(p, "created_at", None)),
        }))
    return out


# ─── MedicationRequest ───────────────────────────────────────────────────────
def _med_text(dci: str, med: Any) -> str:
    parts = [dci or (getattr(med, "dci", "") if med else "")]
    if med is not None:
        if getattr(med, "dosage", ""):
            parts.append(med.dosage)
        if getattr(med, "brand", ""):
            parts.append(f"({med.brand})")
    return " ".join(x for x in parts if x).strip() or "Médicament"


def _route(route: str) -> Optional[dict[str, Any]]:
    """Voie d'administration : texte français, + code SNOMED CT pour les voies sans ambiguïté (PO, IV, SC, IM)."""
    if not route:
        return None
    out: dict[str, Any] = {"text": ROUTES.get(route.upper(), route)}
    if route.upper() in ROUTE_SNOMED:
        code, display = ROUTE_SNOMED[route.upper()]
        out["coding"] = [{"system": SNOMED, "code": code, "display": display}]
    return out


# ─── posologie structurée (dosageInstruction) ────────────────────────────────
_NUMBER = r"(\d+(?:[.,]\d+)?)"
_UNIT = r"([A-Za-zµμ%][^\s/\d]*)"
_PER_DAY = re.compile(r"(?<![\d.,])(?:x\s*)?(\d{1,2})\s*(?:x|fois)?\s*(?:/|par)\s*(jours?|j|24\s*h|semaines?|sem)(?![A-Za-zÀ-ÿ])", re.IGNORECASE)
_EVERY_H = re.compile(r"toutes?\s+les\s+(\d{1,2})\s*(?:h|heures?)(?![A-Za-zÀ-ÿ])", re.IGNORECASE)
_WHEN = (("matin", "MORN"), ("midi", "NOON"), ("soir", "EVE"), ("coucher", "HS"))


def _dose_quantity(value: str, unit: str) -> Optional[dict[str, Any]]:
    try:
        n = _num(float(value.replace(",", ".")))
    except ValueError:
        return None
    if n is None:
        return None
    q: dict[str, Any] = {"value": n, "unit": unit}
    if unit.lower() in DOSE_UNITS:
        q.update(system=UCUM, code=DOSE_UNITS[unit.lower()])
    return q


def parse_dose(text: str) -> Optional[dict[str, Any]]:
    """« 500 mg », « 0,5 mg », « 12 UI », « 4 bouffées » → Quantity ; tout autre texte (« 1 à 2 cp », « 500 mg le matin ») → None."""
    m = re.fullmatch(r"\s*" + _NUMBER + r"\s*" + _UNIT + r"\s*", text or "")
    return _dose_quantity(m.group(1), m.group(2)) if m else None


def parse_frequency(text: str) -> Optional[dict[str, Any]]:
    """Fréquence en texte libre → champs de `timing.repeat`, seulement pour les formes sans ambiguïté :
    « 3/j », « x3/j », « 2 fois/j », « 3 fois par jour », « 1 fois par semaine », « toutes les 8 h », « matin et soir ».
    Renvoie None quand le texte n'est pas reconnu (la fréquence reste alors en texte : rien n'est inventé)."""
    t = text or ""
    low = t.lower()
    when = [code for word, code in _WHEN if re.search(r"(?<![a-zà-ÿ])" + word + r"(?![a-zà-ÿ])", low)]
    out: dict[str, Any] = {}
    m = _PER_DAY.search(t)
    if m:
        unit = m.group(2).lower()
        out = {"frequency": int(m.group(1)), "period": 1, "periodUnit": "wk" if unit.startswith("sem") else "d"}
    else:
        m = _EVERY_H.search(t)
        if m and int(m.group(1)) > 0:
            out = {"frequency": 1, "period": int(m.group(1)), "periodUnit": "h"}
        elif when:
            out = {"frequency": len(when), "period": 1, "periodUnit": "d"}
    if not out or out["frequency"] <= 0:
        return None
    if when and out["periodUnit"] == "d" and len(when) <= out["frequency"]:
        out["when"] = when
    return out


def parse_posology(text: str) -> dict[str, Any]:
    """Posologie d'un seul tenant (« 1 g x3/j », « 5 mg/j », « 500 ml/24 h ») → {dose, rate, repeat} (chaque clé seulement si reconnue)."""
    out: dict[str, Any] = {}
    m = re.match(r"^\s*" + _NUMBER + r"\s*" + _UNIT + r"\s*(.*)$", text or "")
    if not m:
        rep = parse_frequency(text)
        return {"repeat": rep} if rep else out
    dose, rest = _dose_quantity(m.group(1), m.group(2)), m.group(3).strip()
    over = re.fullmatch(r"/\s*(\d{1,3})\s*h", rest)
    if over and dose is not None:                                    # débit : « 500 ml/24 h »
        out["rate"] = {"numerator": dose, "denominator": {"value": int(over.group(1)), "unit": "h", "system": UCUM, "code": "h"}}
        return out
    if dose is not None:
        out["dose"] = dose
    rep = {"frequency": 1, "period": 1, "periodUnit": "d"} if re.fullmatch(r"/\s*(?:j|jour)", rest, re.IGNORECASE) else parse_frequency(rest)
    if rep:
        out["repeat"] = rep
    return out


def _bounds(days: Any) -> Optional[dict[str, Any]]:
    try:
        n = int(days or 0)
    except (TypeError, ValueError):
        return None
    return {"value": n, "unit": "jour", "system": UCUM, "code": "d"} if n > 0 else None


def _med_category(code: str, display: str) -> list[dict[str, Any]]:
    return [{"coding": [{"system": MEDREQ_CATEGORY, "code": code, "display": display}]}]


def medication_request_from_line(line: Any, order: Any, med: Any, code: str) -> dict[str, Any]:
    """Une ligne d'ordonnance de traitement hospitalière (`TreatmentOrderLine`) → MedicationRequest."""
    times = [t.strip() for t in (line.times or "").split(",") if re.fullmatch(r"\d{1,2}:\d{2}", t.strip())]
    text = " · ".join(x for x in [line.dose, ROUTES.get((line.route or "").upper(), line.route), ("à " + ", ".join(times)) if times else "", "si besoin" if line.prn else "",
                                 f"pendant {line.duration_days} j" if line.duration_days else ""] if x)
    dosage: dict[str, Any] = {"text": text, "route": _route(line.route), "asNeededBoolean": bool(line.prn)}
    dose = parse_dose(line.dose)
    if dose is not None:
        dosage["doseAndRate"] = [{"doseQuantity": dose}]
    elif (line.dose or "").strip():
        dosage["extension"] = [{"url": DOSE_TEXT_EXT, "valueString": line.dose.strip()}]
    repeat: dict[str, Any] = {}
    if times:
        repeat.update(frequency=len(times), period=1, periodUnit="d")   # une prise par horaire programmé, chaque jour
        repeat["timeOfDay"] = [f"{int(t.split(':')[0]):02d}:{t.split(':')[1]}:00" for t in times]
    if line.duration_days:
        repeat.update(boundsDuration={"value": int(line.duration_days), "unit": "jour", "system": UCUM, "code": "d"})
    if repeat:
        dosage["timing"] = {"repeat": repeat}
    notes = [{"text": t} for t in (line.allergy_alert, line.interaction_alert) if t]
    if line.prn and line.condition_metric and line.condition_value is not None:
        notes.append({"text": f"Condition de prise : {line.condition_metric} {line.condition_op} {line.condition_value} (intervalle minimal {line.min_interval_h} h)"})
    when = iso(order.signed_at) or iso(order.created_at) or now_iso()
    return _clean({
        "resourceType": "MedicationRequest",
        "id": f"medreq-order-{order.id}-line-{line.id}",
        "meta": {"lastUpdated": iso(order.stopped_at) or when},
        "status": ORDER_STATUS.get(order.status, "unknown"),
        "intent": "order",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/medicationrequest-category", "code": "inpatient", "display": "Inpatient"}]}],
        "medicationCodeableConcept": {"text": _med_text(line.dci, med)},
        "subject": _ref(code),
        "encounter": {"reference": f"Encounter/enc-{order.admission_id}"} if order.admission_id else None,
        "authoredOn": when,
        "requester": {"display": order.prescriber_name or order.prescriber} if (order.prescriber_name or order.prescriber) else None,
        "reasonCode": [{"text": order.indication}] if order.indication else None,
        "groupIdentifier": {"system": "urn:hackcure:treatment-order", "value": str(order.id)},
        "dosageInstruction": [_clean(dosage)],
        "note": notes,
    })


def medication_request_from_treatment(t: Any, med: Any, code: str) -> dict[str, Any]:
    """Un traitement hospitalier en cours ou passé (`Treatment`, saisi à l'admission) → MedicationRequest."""
    when = iso(t.start) or now_iso()
    dosage: dict[str, Any] = {"text": " · ".join(x for x in [t.posology, ROUTES.get((t.route or "").upper(), t.route)] if x), "route": _route(t.route)}
    parsed = parse_posology(t.posology)
    if parsed.get("dose") is not None:
        dosage["doseAndRate"] = [{"doseQuantity": parsed["dose"]}]
    elif parsed.get("rate") is not None:
        dosage["doseAndRate"] = [{"rateRatio": parsed["rate"]}]
    elif (t.posology or "").strip():
        dosage["extension"] = [{"url": DOSE_TEXT_EXT, "valueString": t.posology.strip()}]
    if parsed.get("repeat"):
        dosage["timing"] = {"repeat": parsed["repeat"]}
    return _clean({
        "resourceType": "MedicationRequest",
        "id": f"medreq-treatment-{t.id}",
        "meta": {"lastUpdated": iso(t.end) or when},
        "status": "completed" if t.end else "active",
        "intent": "order",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/medicationrequest-category", "code": "inpatient", "display": "Inpatient"}]}],
        "medicationCodeableConcept": {"text": _med_text("", med)},
        "subject": _ref(code),
        "encounter": {"reference": f"Encounter/enc-{t.admission_id}"} if t.admission_id else None,
        "authoredOn": when,
        "requester": {"display": t.prescriber} if t.prescriber else None,
        "dosageInstruction": [_clean(dosage)],
    })


def medication_request_from_prescription_line(line: Any, prescription: Any, med: Any, code: str, notes: str = "") -> dict[str, Any]:
    """Une ligne de l'ORDONNANCE DE SORTIE signée (`Prescription` + `PrescriptionLine`) → MedicationRequest de catégorie `discharge`.

    `notes` : note libre de l'ordonnance, déjà pseudonymisée par l'appelant. Dose, fréquence, durée et voie sont celles de la ligne :
    rien n'est déduit ; une fréquence en texte non reconnue reste en texte (pas de `timing.repeat.frequency`)."""
    route_text = ROUTES.get((line.route or "").upper(), line.route)
    bounds = _bounds(line.duration_days)
    text = " · ".join(x for x in [(line.dosage or "").strip(), (line.frequency or "").strip(), route_text, f"pendant {bounds['value']} j" if bounds else ""] if x) or "Posologie non précisée"
    dosage: dict[str, Any] = {"text": text, "route": _route(line.route)}
    extensions: list[dict[str, Any]] = []
    dose = parse_dose(line.dosage)
    if dose is not None:
        dosage["doseAndRate"] = [{"doseQuantity": dose}]
    elif (line.dosage or "").strip():
        extensions.append({"url": DOSE_TEXT_EXT, "valueString": line.dosage.strip()})
    repeat: dict[str, Any] = dict(parse_frequency(line.frequency) or {})
    if not repeat and (line.frequency or "").strip():
        extensions.append({"url": FREQUENCY_TEXT_EXT, "valueString": line.frequency.strip()})
    if bounds:
        repeat["boundsDuration"] = bounds
    timing: dict[str, Any] = {"repeat": repeat} if repeat else {}
    if (line.frequency or "").strip():
        timing["code"] = {"text": line.frequency.strip()}
    dosage["timing"] = timing
    dosage["extension"] = extensions
    when = iso(prescription.signed_at) or iso(prescription.created_at) or now_iso()
    note = [{"text": notes}] if notes else []
    if getattr(line, "allergy_warning", False):
        note.append({"text": "Alerte allergie signalée à la prescription"})
    return _clean({
        "resourceType": "MedicationRequest",
        "id": f"medreq-prescription-{prescription.id}-line-{line.id}",
        "meta": {"lastUpdated": when},
        "status": "active" if prescription.status == "signed" else "draft",
        "intent": "order",
        "category": _med_category("discharge", "Discharge"),
        "medicationCodeableConcept": {"text": _med_text("", med)},
        "subject": _ref(code),
        "encounter": {"reference": f"Encounter/enc-{prescription.admission_id}"} if prescription.admission_id else None,
        "authoredOn": when,
        "requester": {"display": prescription.prescriber} if prescription.prescriber else None,
        "groupIdentifier": {"system": "urn:hackcure:discharge-prescription", "value": str(prescription.id)},
        "dosageInstruction": [_clean(dosage)],
        "note": note,
    })


# ─── DocumentReference ───────────────────────────────────────────────────────
def document_reference(rid: str, code: str, kind: str, title: str, text: str, when: Any = None, author: str = "", description: str = "", encounter_id: Optional[str] = None) -> dict[str, Any]:
    """Un document signé → DocumentReference. `kind` : « report » (rapport médecin, LOINC 11488-4) ou « discharge »
    (compte rendu de sortie, LOINC 18842-5). `title`, `description` et `text` doivent être DÉJÀ pseudonymisés par l'appelant
    (le routeur, qui connaît les noms des patients) : cette fonction se contente d'encoder le texte en base64 (UTF-8)."""
    loinc, display, label = DOCUMENT_TYPES.get(kind, DOCUMENT_TYPES["report"])
    date_ = iso(when) or now_iso()
    return _clean({
        "resourceType": "DocumentReference",
        "id": rid,
        "meta": {"lastUpdated": date_, "security": [PSEUDONYMISED_TAG]},
        "status": "current",
        "docStatus": "final",
        "type": {"coding": [{"system": LOINC, "code": loinc, "display": display}], "text": label},
        "subject": _ref(code),
        "date": date_,
        "author": [{"display": author}] if author else None,
        "description": description or title,
        "content": [{"attachment": _clean({
            "contentType": "text/plain; charset=utf-8",
            "language": "fr",
            "data": base64.b64encode((text or "").encode("utf-8")).decode("ascii"),
            "title": title,
            "creation": date_,
        })}],
        "context": {"encounter": [{"reference": f"Encounter/{encounter_id}"}]} if encounter_id else None,
    })


# ─── Encounter ───────────────────────────────────────────────────────────────
def encounter_resource(a: Any, code: str, clinical: bool = True) -> dict[str, Any]:
    """Une admission → Encounter. `clinical=False` (réceptionniste) : dates et lieu seulement, sans motif."""
    start, end = iso(a.admitted_at), iso(a.discharged_at)
    return _clean({
        "resourceType": "Encounter",
        "id": f"enc-{a.id}",
        "meta": {"lastUpdated": end or start or now_iso()},
        "status": "finished" if a.discharged_at else "in-progress",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "IMP", "display": "inpatient encounter"},
        "subject": _ref(code),
        "period": _clean({"start": start, "end": end}),
        "reasonCode": [{"text": a.reason}] if clinical and a.reason else None,
        "participant": [{"individual": {"display": a.referring_doctor}}] if clinical and a.referring_doctor else None,
        "location": [{"location": {"display": f"Chambre {a.room_code}"}}] if a.room_code else None,
        "serviceProvider": {"display": "Clinique HackCure"},
    })


# ─── Bundle, OperationOutcome, CapabilityStatement ───────────────────────────
def bundle(resources: list[dict[str, Any]], base_url: str, self_url: str = "", bundle_type: str = "searchset") -> dict[str, Any]:
    base = base_url.rstrip("/")
    b: dict[str, Any] = {"resourceType": "Bundle", "type": bundle_type, "meta": {"lastUpdated": now_iso()}, "timestamp": now_iso(), "total": len(resources)}
    if self_url:
        b["link"] = [{"relation": "self", "url": self_url}]
    b["entry"] = [{"fullUrl": f"{base}/{r['resourceType']}/{r['id']}", "resource": r, "search": {"mode": "match"}} for r in resources]
    return b


def operation_outcome(code: str, diagnostics: str, severity: str = "error") -> dict[str, Any]:
    return {"resourceType": "OperationOutcome", "issue": [{"severity": severity, "code": code, "diagnostics": diagnostics}]}


def capability_statement(base_url: str) -> dict[str, Any]:
    def res(rtype: str, interactions: list[str], params: list[tuple[str, str]] = (), ops: list[dict[str, str]] = ()) -> dict[str, Any]:  # type: ignore[assignment]
        return _clean({"type": rtype, "interaction": [{"code": c} for c in interactions], "searchParam": [{"name": n, "type": t} for n, t in params], "operation": list(ops)})

    patient_param = [("patient", "reference")]
    return {
        "resourceType": "CapabilityStatement",
        "status": "active",
        "date": now_iso(),
        "publisher": "Hospital Copilot — Clinique HackCure",
        "kind": "instance",
        "software": {"name": "Hospital Copilot", "version": "3.0"},
        "implementation": {"description": "API FHIR R4 en lecture seule (identifiants pseudonymisés)", "url": base_url.rstrip("/")},
        "fhirVersion": FHIR_VERSION,
        "format": [FHIR_MEDIA_TYPE, "json"],
        "rest": [{
            "mode": "server",
            "documentation": "Lecture seule. Authentification par cookie de session ou jeton « Bearer » de la plateforme ; droits par rôle ; chaque lecture est tracée.",
            "security": {"description": "Jeton JWT de la plateforme (cookie HttpOnly ou en-tête Authorization: Bearer). Pas de SMART-on-FHIR."},
            "resource": [
                res("Patient", ["read"], ops=[{"name": "everything", "definition": "http://hl7.org/fhir/OperationDefinition/Patient-everything"}]),
                res("Observation", ["search-type"], patient_param + [("category", "token")]),
                res("Condition", ["search-type"], patient_param),
                res("AllergyIntolerance", ["search-type"], patient_param),
                res("MedicationRequest", ["search-type"], patient_param),
                res("Encounter", ["search-type"], patient_param),
                res("DocumentReference", ["search-type"], patient_param),
            ],
        }],
    }

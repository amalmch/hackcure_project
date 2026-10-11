"""V3 étape 4 — interopérabilité HL7 FHIR R4 (lecture seule) : structure des ressources, codes LOINC / UCUM, Bundle, pseudonymisation,
droits par rôle, erreurs en OperationOutcome, traçabilité, interrupteur FHIR_ENABLED."""
import re
from datetime import date, datetime, timezone
from types import SimpleNamespace

from .test_agents import msg

FHIR_JSON = "application/fhir+json"
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\+00:00|Z)$")
FHIR_ID = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")


def _codes(resource):
    return {c["code"] for c in resource["code"].get("coding", []) if c.get("system") == LOINC}


def _check_bundle(r, rtype=None):
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith(FHIR_JSON)
    b = r.json()
    assert b["resourceType"] == "Bundle" and b["type"] == "searchset" and b["total"] == len(b["entry"])
    assert b["link"][0]["relation"] == "self"
    for e in b["entry"]:
        res = e["resource"]
        assert e["fullUrl"].endswith(f"/fhir/{res['resourceType']}/{res['id']}")
        assert FHIR_ID.match(res["id"]), res["id"]
        assert INSTANT.match(res["meta"]["lastUpdated"]), res["meta"]
        if rtype:
            assert res["resourceType"] == rtype
    return b


def _resources(bundle, rtype=None):
    return [e["resource"] for e in bundle["entry"] if rtype is None or e["resource"]["resourceType"] == rtype]


def _audit_count(action="fhir_read", entity_id="PAT-0001", user=None):
    from sqlmodel import select

    from app.db import session_scope
    from app.models import AuditLog

    with session_scope() as s:
        q = select(AuditLog).where(AuditLog.action == action, AuditLog.entity_id == entity_id)
        if user:
            q = q.where(AuditLog.user == user)
        return len(s.exec(q).all())


def _ingest_vitals(client, room="101"):
    for dev, metrics in (("ecg", {"hr": 82, "rhythm": "sinus", "rr": 17}), ("spo2", {"spo2": 97}), ("bp", {"sys": 128, "dia": 79, "map": 95}), ("thermometer", {"tempC": 37.2}), ("glucometer", {"glucose": 1.12})):
        r = client.post("/api/ingest", json=msg(f"hackcure/room/{room}/device/{room}-{dev}", type=dev, metrics=metrics))
        assert r.status_code < 300, r.text


# ─── Patient ─────────────────────────────────────────────────────────────────
def test_patient_identifier_is_the_pseudonym_and_identity_follows_the_role(client, login):
    r = client.get("/fhir/Patient/PAT-0001")
    assert r.status_code == 200 and r.headers["content-type"].startswith(FHIR_JSON)
    p = r.json()
    assert p["resourceType"] == "Patient" and p["id"] == "PAT-0001"
    assert p["identifier"] == [{"system": "urn:hackcure:pseudonym", "value": "PAT-0001"}]
    assert p["gender"] in ("male", "female") and INSTANT.match(p["meta"]["lastUpdated"])
    assert p["name"][0]["family"] and p["name"][0]["given"] and re.match(r"^\d{4}-\d{2}-\d{2}$", p["birthDate"])     # owner : identité visible
    assert "security" not in p["meta"]
    assert client.get("/fhir/Patient/patient_01").json()["id"] == "PAT-0001"                                        # identifiant interne accepté
    assert client.get("/fhir/Patient/pat-0001").json()["id"] == "PAT-0001"
    assert "patient_01" not in r.text                                                                              # jamais l'identifiant interne en sortie

    ph = login("pharmacist").get("/fhir/Patient/PAT-0001").json()                                                   # pas de `view_identity`
    assert ph["id"] == "PAT-0001" and "name" not in ph and re.match(r"^\d{4}$", ph["birthDate"]) and ph["birthDate"] == p["birthDate"][:4]
    assert ph["meta"]["security"][0]["code"] == "PSEUDED" and ph["gender"] == p["gender"]
    assert p["name"][0]["family"] not in str(ph)
    assert "name" in login("receptionist").get("/fhir/Patient/PAT-0001").json()
    assert "name" in login("nurse").get("/fhir/Patient/PAT-0001").json()


# ─── Observation ─────────────────────────────────────────────────────────────
def test_vital_signs_use_loinc_and_ucum(client):
    _ingest_vitals(client, "101")
    b = _check_bundle(client.get("/fhir/Observation?patient=PAT-0001&category=vital-signs"), "Observation")
    by_code = {}
    for o in _resources(b):
        assert o["status"] == "final" and o["subject"] == {"reference": "Patient/PAT-0001"} and INSTANT.match(o["effectiveDateTime"])
        assert o["category"][0]["coding"][0] == {"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs", "display": "Vital Signs"}
        assert all(c["system"] == LOINC and c["code"] and c["display"] for c in o["code"]["coding"])
        for c in _codes(o):
            by_code[c] = o
    assert {"8867-4", "59408-5", "2708-6", "85354-9", "8310-5", "9279-1", "41653-7"} <= set(by_code)
    assert by_code["8867-4"]["valueQuantity"] == {"value": 82, "unit": "/min", "system": UCUM, "code": "/min"}
    assert by_code["59408-5"]["valueQuantity"] == {"value": 97, "unit": "%", "system": UCUM, "code": "%"}
    assert by_code["8310-5"]["valueQuantity"] == {"value": 37.2, "unit": "°C", "system": UCUM, "code": "Cel"}
    assert by_code["9279-1"]["valueQuantity"]["value"] == 17 and by_code["9279-1"]["valueQuantity"]["code"] == "/min"
    assert by_code["41653-7"]["valueQuantity"] == {"value": 1.12, "unit": "g/L", "system": UCUM, "code": "g/L"}
    bp = by_code["85354-9"]
    assert "valueQuantity" not in bp
    comp = {c["code"]["coding"][0]["code"]: c["valueQuantity"] for c in bp["component"]}
    assert comp["8480-6"] == {"value": 128, "unit": "mmHg", "system": UCUM, "code": "mm[Hg]"} and comp["8462-4"]["value"] == 79
    assert bp["encounter"]["reference"].startswith("Encounter/enc-")
    # `patient=` accepte aussi la référence FHIR et l'identifiant interne
    assert _check_bundle(client.get("/fhir/Observation?patient=Patient/PAT-0001&category=vital-signs"))["total"] == b["total"]
    assert _check_bundle(client.get("/fhir/Observation?patient=patient_01&category=vital-signs"))["total"] == b["total"]


def test_laboratory_observations(client):
    b = _check_bundle(client.get("/fhir/Observation?patient=PAT-0001&category=laboratory"), "Observation")
    labs = _resources(b)
    assert len(labs) >= 50 and all(o["category"][0]["coding"][0]["code"] == "laboratory" and o["status"] == "final" for o in labs)
    assert all(any(c["system"] == "urn:hackcure:lab" for c in o["code"]["coding"]) for o in labs)
    assert all(("valueQuantity" in o) or ("valueString" in o) or ("dataAbsentReason" in o) for o in labs)
    hba1c = [o for o in labs if "4548-4" in _codes(o)]
    assert hba1c and hba1c[0]["valueQuantity"]["unit"] == "%" and hba1c[0]["valueQuantity"]["system"] == UCUM and hba1c[0]["referenceRange"][0]["high"]["value"] == 6
    both = _check_bundle(client.get("/fhir/Observation?patient=PAT-0001"))
    assert {o["category"][0]["coding"][0]["code"] for o in _resources(both)} == {"vital-signs", "laboratory"}


# ─── Condition, AllergyIntolerance, MedicationRequest, Encounter ─────────────
def test_condition_allergy_medication_encounter(client):
    conds = _resources(_check_bundle(client.get("/fhir/Condition?patient=PAT-0002"), "Condition"))
    assert conds and all(c["subject"] == {"reference": "Patient/PAT-0002"} and c["code"]["text"] and "coding" not in c["code"] for c in conds)   # texte libre : aucun code inventé
    assert all(c["clinicalStatus"]["coding"][0]["code"] == "active" and c["verificationStatus"]["coding"][0]["code"] == "confirmed" for c in conds)
    assert any("insuffisance cardiaque" in c["code"]["text"].lower() for c in conds)
    assert any(c["category"][0]["coding"][0]["code"] == "encounter-diagnosis" for c in conds)                       # motif d'hospitalisation

    alls = _resources(_check_bundle(client.get("/fhir/AllergyIntolerance?patient=PAT-0002"), "AllergyIntolerance"))
    assert any(a["code"]["text"] == "pénicilline" for a in alls)
    assert all(a["patient"] == {"reference": "Patient/PAT-0002"} and a["clinicalStatus"]["coding"][0]["code"] == "active" and "coding" not in a["code"] for a in alls)

    meds = _resources(_check_bundle(client.get("/fhir/MedicationRequest?patient=PAT-0002"), "MedicationRequest"))
    assert len(meds) >= 4
    for m in meds:
        assert m["status"] in ("active", "completed", "draft", "stopped") and m["intent"] == "order" and m["subject"] == {"reference": "Patient/PAT-0002"}
        assert m["medicationCodeableConcept"]["text"] and m["dosageInstruction"][0]["text"] and INSTANT.match(m["authoredOn"])
    assert any("5 mg x2/j" in m["dosageInstruction"][0]["text"] for m in meds)

    encs = _resources(_check_bundle(client.get("/fhir/Encounter?patient=PAT-0001"), "Encounter"))
    assert len(encs) >= 2 and {e["status"] for e in encs} == {"in-progress", "finished"}
    for e in encs:
        assert e["class"]["code"] == "IMP" and e["subject"] == {"reference": "Patient/PAT-0001"} and INSTANT.match(e["period"]["start"])
        assert ("end" in e["period"]) == (e["status"] == "finished")
    assert any(e.get("reasonCode") for e in encs)


def test_everything_bundle(client):
    _ingest_vitals(client, "102")
    b = _check_bundle(client.get("/fhir/Patient/PAT-0002/$everything"))
    res = _resources(b)
    assert res[0]["resourceType"] == "Patient" and res[0]["id"] == "PAT-0002"
    assert {r["resourceType"] for r in res} == {"Patient", "Encounter", "Condition", "AllergyIntolerance", "MedicationRequest", "Observation", "DocumentReference"}
    ids = [(r["resourceType"], r["id"]) for r in res]
    assert len(ids) == len(set(ids))
    for r in res[1:]:
        assert (r.get("subject") or r.get("patient")) == {"reference": "Patient/PAT-0002"}
    assert client.get("/fhir/Patient/patient_02/$everything").json()["total"] == b["total"]


def test_metadata(client):
    r = client.get("/fhir/metadata")
    assert r.status_code == 200 and r.headers["content-type"].startswith(FHIR_JSON)
    cs = r.json()
    assert cs["resourceType"] == "CapabilityStatement" and cs["fhirVersion"] == "4.0.1" and cs["kind"] == "instance" and FHIR_JSON in cs["format"]
    types = {x["type"]: x for x in cs["rest"][0]["resource"]}
    assert set(types) == {"Patient", "Observation", "Condition", "AllergyIntolerance", "MedicationRequest", "Encounter", "DocumentReference"}
    assert all(i["code"] in ("read", "search-type") for x in types.values() for i in x["interaction"])              # lecture seule


# ─── droits, erreurs, traçabilité, interrupteur ──────────────────────────────
def _is_outcome(r, status, code=None):
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith(FHIR_JSON)
    o = r.json()
    assert o["resourceType"] == "OperationOutcome" and o["issue"][0]["severity"] == "error" and o["issue"][0]["diagnostics"]
    if code:
        assert o["issue"][0]["code"] == code
    return o


def test_role_scoping(login):
    ph = login("pharmacist")
    _is_outcome(ph.get("/fhir/Observation?patient=PAT-0001"), 403, "forbidden")
    _is_outcome(ph.get("/fhir/Condition?patient=PAT-0001"), 403, "forbidden")
    _is_outcome(ph.get("/fhir/Encounter?patient=PAT-0001"), 403, "forbidden")
    assert _check_bundle(ph.get("/fhir/AllergyIntolerance?patient=PAT-0002"), "AllergyIntolerance")["total"] >= 1
    assert _check_bundle(ph.get("/fhir/MedicationRequest?patient=PAT-0002"), "MedicationRequest")["total"] >= 4
    ev = _check_bundle(ph.get("/fhir/Patient/PAT-0002/$everything"))
    assert {r["resourceType"] for r in _resources(ev)} == {"Patient", "AllergyIntolerance", "MedicationRequest"}
    pat = _resources(ev, "Patient")[0]
    assert "name" not in pat and len(pat["birthDate"]) == 4 and pat["meta"]["security"][0]["code"] == "PSEUDED"

    rc = login("receptionist")
    _is_outcome(rc.get("/fhir/Observation?patient=PAT-0001"), 403)
    _is_outcome(rc.get("/fhir/MedicationRequest?patient=PAT-0001"), 403)
    encs = _resources(_check_bundle(rc.get("/fhir/Encounter?patient=PAT-0001"), "Encounter"))
    assert encs and all("reasonCode" not in e and "participant" not in e for e in encs)                             # dates et lieu, pas de contenu clinique
    assert {r["resourceType"] for r in _resources(_check_bundle(rc.get("/fhir/Patient/PAT-0001/$everything")))} == {"Patient", "Encounter"}

    nurse = login("nurse")
    assert _check_bundle(nurse.get("/fhir/Condition?patient=PAT-0001"))["total"] >= 1
    assert len({r["resourceType"] for r in _resources(_check_bundle(nurse.get("/fhir/Patient/PAT-0001/$everything")))}) >= 5


def test_anonymous_gets_401(anon_client):
    for url in ("/fhir/Patient/PAT-0001", "/fhir/Observation?patient=PAT-0001", "/fhir/Condition?patient=PAT-0001", "/fhir/AllergyIntolerance?patient=PAT-0001",
                "/fhir/MedicationRequest?patient=PAT-0001", "/fhir/Encounter?patient=PAT-0001", "/fhir/Patient/PAT-0001/$everything", "/fhir/metadata"):
        _is_outcome(anon_client.get(url), 401, "login")


def test_unknown_patient_and_missing_parameter(client):
    _is_outcome(client.get("/fhir/Patient/PAT-9999"), 404, "not-found")
    _is_outcome(client.get("/fhir/Patient/PAT-9999/$everything"), 404, "not-found")
    for rtype in ("Observation", "Condition", "AllergyIntolerance", "MedicationRequest", "Encounter"):
        _is_outcome(client.get(f"/fhir/{rtype}?patient=PAT-9999"), 404, "not-found")
        _is_outcome(client.get(f"/fhir/{rtype}"), 400, "required")


def test_reads_are_audited(client, login):
    before = _audit_count(user="owner")
    client.get("/fhir/Patient/PAT-0001")
    client.get("/fhir/Observation?patient=patient_01")
    client.get("/fhir/Patient/PAT-0001/$everything")
    assert _audit_count(user="owner") == before + 3
    from sqlmodel import select

    from app.db import session_scope
    from app.models import AuditLog

    with session_scope() as s:
        row = s.exec(select(AuditLog).where(AuditLog.action == "fhir_read", AuditLog.user == "owner").order_by(AuditLog.id.desc())).first()
        assert row.entity == "fhir:Patient/$everything" and row.entity_id == "PAT-0001" and row.role == "owner" and '"returned"' in row.details
    denied = _audit_count(action="fhir_denied", entity_id="PAT-0001", user="pharmacien")
    login("pharmacist").get("/fhir/Observation?patient=PAT-0001")
    assert _audit_count(action="fhir_denied", entity_id="PAT-0001", user="pharmacien") == denied + 1


def test_fhir_can_be_disabled(client, monkeypatch):
    monkeypatch.setenv("FHIR_ENABLED", "0")
    for url in ("/fhir/metadata", "/fhir/Patient/PAT-0001", "/fhir/Observation?patient=PAT-0001", "/fhir/Patient/PAT-0001/$everything"):
        _is_outcome(client.get(url), 404, "not-supported")
    monkeypatch.setenv("FHIR_ENABLED", "1")
    assert client.get("/fhir/Patient/PAT-0001").status_code == 200
    monkeypatch.delenv("FHIR_ENABLED")
    assert client.get("/fhir/Patient/PAT-0001").status_code == 200                                                  # activé par défaut


# ─── fonctions de correspondance pures ───────────────────────────────────────
def test_pure_mapping_functions():
    from app import fhir as fmap

    assert fmap.split_history("Insuffisance cardiaque (FEVG 40 %, stade II), fibrillation atriale ; BPCO.") == ["Insuffisance cardiaque (FEVG 40 %, stade II)", "fibrillation atriale", "BPCO"]
    assert fmap.iso(datetime(2026, 10, 10, 8, 30, 15, 999)) == "2026-10-10T08:30:15+00:00" and fmap.iso(None) is None            # date naïve = UTC
    assert fmap.vital_observations("PAT-0009", {"hr": None, "map": 90}) == []                                                     # ni valeur absente ni PAM seule ne produisent d'Observation
    obs = fmap.vital_observations("PAT-0009", {"hr": True, "sys": 120, "dia": 80})
    assert len(obs) == 1 and obs[0]["code"]["coding"][0]["code"] == "85354-9" and len(obs[0]["component"]) == 2

    p = SimpleNamespace(code="PAT-0009", first_name="Test", last_name="Patient", birth_date=date(1960, 5, 4), sex="F", created_at=None, allergies="Iode, aspirine", history="Diabète de type 2, HTA")
    p.allergy_list = ["iode", "aspirine"]
    hidden = fmap.patient_resource(p, identity=False)
    assert "name" not in hidden and hidden["birthDate"] == "1960" and hidden["gender"] == "female" and hidden["meta"]["security"]
    assert fmap.patient_resource(p, identity=True)["birthDate"] == "1960-05-04"
    assert [a["code"]["text"] for a in fmap.allergy_resources(p)] == ["iode", "aspirine"]
    chronic = SimpleNamespace(id=7, title="Diagnostic : Diabète de type 2", data_json='{"condition": "Diabète de type 2"}', date=datetime(2015, 3, 1, tzinfo=timezone.utc), service="Endocrinologie")
    conds = fmap.condition_resources(p, [chronic])
    assert [c["code"]["text"] for c in conds] == ["Diabète de type 2", "HTA"] and conds[0]["onsetDateTime"].startswith("2015-03-01")   # pas de doublon dossier / texte libre

    order = SimpleNamespace(id=3, admission_id=5, status="active", prescriber="medecin", prescriber_name="Dr Test", indication="Fièvre", created_at=datetime(2026, 10, 10, 8, 0), signed_at=datetime(2026, 10, 10, 8, 5), stopped_at=None)
    line = SimpleNamespace(id=11, dci="paracétamol", dose="1 g", route="IV", times="08:00,14:00,20:00", duration_days=3, prn=True, condition_metric="tempC", condition_op=">", condition_value=38.5,
                           min_interval_h=6.0, allergy_alert="", interaction_alert="")
    med = SimpleNamespace(dci="paracétamol", brand="Perfalgan", dosage="1 g", form="solution injectable")
    mr = fmap.medication_request_from_line(line, order, med, "PAT-0009")
    assert mr["id"] == "medreq-order-3-line-11" and mr["status"] == "active" and mr["intent"] == "order" and mr["subject"] == {"reference": "Patient/PAT-0009"}
    assert "paracétamol" in mr["medicationCodeableConcept"]["text"] and mr["encounter"] == {"reference": "Encounter/enc-5"} and mr["reasonCode"] == [{"text": "Fièvre"}]
    d = mr["dosageInstruction"][0]
    assert d["asNeededBoolean"] is True and d["timing"]["repeat"]["timeOfDay"] == ["08:00:00", "14:00:00", "20:00:00"] and d["timing"]["repeat"]["boundsDuration"]["code"] == "d"
    assert any("38.5" in n["text"] for n in mr["note"])

    lab = SimpleNamespace(id=42, code="CRP", label="CRP", value=48.0, text="", unit="mg/L", ref_low=0.0, ref_high=5.0, abnormal=True, date=datetime(2026, 10, 9, 7, 0))
    lo = fmap.lab_observation(lab, "PAT-0009")
    assert lo["code"]["coding"][0] == {"system": LOINC, "code": "1988-5", "display": "C reactive protein [Mass/volume] in Serum or Plasma"}
    assert lo["valueQuantity"] == {"value": 48, "unit": "mg/L", "system": UCUM, "code": "mg/L"} and lo["interpretation"][0]["coding"][0]["code"] == "A"
    qual = fmap.lab_observation(SimpleNamespace(id=43, code="HEMOC", label="Hémocultures", value=None, text="Négatives", unit="", ref_low=None, ref_high=None, abnormal=False, date=datetime(2026, 10, 9)), "PAT-0009")
    assert qual["valueString"] == "Négatives" and "valueQuantity" not in qual and [c["system"] for c in qual["code"]["coding"]] == ["urn:hackcure:lab"]

    out = fmap.operation_outcome("not-found", "x")
    assert out == {"resourceType": "OperationOutcome", "issue": [{"severity": "error", "code": "not-found", "diagnostics": "x"}]}

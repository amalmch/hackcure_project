"""V3 — FHIR pour l'application mobile du patient : DocumentReference (rapports médecin signés, comptes rendus de sortie, texte
pseudonymisé) et MedicationRequest de l'ordonnance de sortie avec une posologie structurée (`dosageInstruction`)."""
import base64
from datetime import datetime
from types import SimpleNamespace

from .test_v3_fhir import INSTANT, LOINC, UCUM, _check_bundle, _is_outcome, _resources

SERVICE = {"Authorization": "Bearer test-service-token"}
MEDREQ_CATEGORY = "http://terminology.hl7.org/CodeSystem/medicationrequest-category"


def _category(m):
    return m["category"][0]["coding"][0]["code"]


def _text(doc):
    return base64.b64decode(doc["content"][0]["attachment"]["data"]).decode("utf-8")


def _identity(client, patient_id):
    """Nom et prénom réels du patient (lus avec le rôle propriétaire)."""
    name = client.get(f"/fhir/Patient/{patient_id}").json()["name"][0]
    return name["given"][0], name["family"]


def _signed_report(client, login, patient_id, title="Compte rendu médical"):
    first, last = _identity(client, patient_id)
    doc = login("duty_doctor")
    adm = client.get(f"/api/records/{patient_id}").json()["admission"]["id"]
    content = f"Patient {first} {last}, vu ce jour.\n\nÉvolution : favorable pour M. {last.upper()}.\nConclusion : poursuite du traitement, {first} sera revu demain."
    r = doc.post("/api/reports", json={"admission_id": adm, "title": title, "content": content})
    assert r.status_code == 201, r.text
    signed = doc.post(f"/api/reports/{r.json()['id']}/sign")
    assert signed.status_code == 200 and signed.json()["status"] == "signed"
    return signed.json(), first, last


def _signed_prescription(client, login, patient_id, lines):
    doc = login("general_doctor")
    adm = client.get(f"/api/records/{patient_id}").json()["admission"]["id"]
    meds = {m["brand"]: m for m in client.get("/api/pharmacy/medications").json()}
    body = {"admission_id": adm, "notes": "Ordonnance de sortie (test FHIR)", "lines": [{**ln, "medication_id": meds[ln.pop("brand")]["id"]} for ln in [dict(x) for x in lines]]}
    r = doc.post("/api/prescriptions", json=body)
    assert r.status_code == 201, r.text
    signed = doc.post(f"/api/prescriptions/{r.json()['id']}/sign")
    assert signed.status_code == 200 and signed.json()["status"] == "signed", signed.text
    return signed.json()


# ─── DocumentReference ───────────────────────────────────────────────────────
def test_document_reference_du_rapport_signe_est_pseudonymise(client, login):
    rep, first, last = _signed_report(client, login, "patient_01")
    draft = login("duty_doctor").post("/api/reports", json={"admission_id": rep["admission_id"], "title": "Brouillon non signé", "content": "à ne pas exporter"}).json()
    b = _check_bundle(client.get("/fhir/DocumentReference?patient=PAT-0001"), "DocumentReference")
    docs = {d["id"]: d for d in _resources(b)}
    assert f"docref-report-{draft['id']}" not in docs                                                               # seulement les rapports signés
    d = docs[f"docref-report-{rep['id']}"]
    assert d["status"] == "current" and d["docStatus"] == "final" and d["subject"] == {"reference": "Patient/PAT-0001"}
    assert d["type"]["coding"][0] == {"system": LOINC, "code": "11488-4", "display": "Consult note"} and d["type"]["text"] == "Compte rendu médical"
    assert INSTANT.match(d["date"]) and INSTANT.match(d["meta"]["lastUpdated"]) and d["author"][0]["display"] == rep["author"] and d["description"]
    assert d["context"]["encounter"] == [{"reference": f"Encounter/enc-{rep['admission_id']}"}]
    att = d["content"][0]["attachment"]
    assert att["contentType"] == "text/plain; charset=utf-8" and att["language"] == "fr" and att["title"] == "Compte rendu médical"
    text = _text(d)
    assert "PAT-0001" in text and "Évolution : favorable" in text
    assert first not in text and last not in text and last.upper() not in text and last.lower() not in text.lower()   # aucun nom, quelle que soit la casse
    # le rapport signé de l'ancien séjour (terminé) est un compte rendu de sortie, comme les hospitalisations du dossier médical
    discharge = [x for x in docs.values() if x["type"]["coding"][0]["code"] == "18842-5"]
    assert discharge and all(x["type"]["coding"][0]["display"] == "Discharge summary" and x["type"]["text"] == "Compte rendu de sortie d'hospitalisation" for x in discharge)
    assert any(x["id"].startswith("docref-report-") and "retour à domicile" in _text(x) for x in discharge)
    for x in docs.values():                                                                                          # aucun document ne porte le nom du patient
        assert first not in _text(x) and last not in _text(x) and last not in str(x)
    assert _check_bundle(client.get("/fhir/DocumentReference?subject=Patient/PAT-0001"))["total"] == b["total"]


def test_rapport_intitule_sortie_est_un_compte_rendu_de_sortie(client, login):
    rep, _first, _last = _signed_report(client, login, "patient_03", title="Compte rendu de sortie")
    docs = {d["id"]: d for d in _resources(_check_bundle(client.get("/fhir/DocumentReference?patient=PAT-0003")))}
    assert docs[f"docref-report-{rep['id']}"]["type"]["coding"][0]["code"] == "18842-5"


# ─── MedicationRequest : ordonnance de sortie ────────────────────────────────
def test_ordonnance_de_sortie_avec_posologie_structuree(client, login):
    pr = _signed_prescription(client, login, "patient_01", [
        {"brand": "Doliprane", "dosage": "1 g", "frequency": "3/j", "duration_days": 5, "route": "PO"},
        {"brand": "Glucophage", "dosage": "1 cp le matin", "frequency": "selon glycémie", "duration_days": 30, "route": "PO"}])
    doc = login("general_doctor")
    adm = pr["admission_id"]
    meds = {m["brand"]: m for m in client.get("/api/pharmacy/medications").json()}
    draft = doc.post("/api/prescriptions", json={"admission_id": adm, "lines": [{"medication_id": meds["Doliprane"]["id"], "dosage": "500 mg", "frequency": "2/j"}]}).json()
    meds_fhir = _resources(_check_bundle(client.get("/fhir/MedicationRequest?patient=PAT-0001"), "MedicationRequest"))
    by_id = {m["id"]: m for m in meds_fhir}
    assert not [i for i in by_id if i.startswith(f"medreq-prescription-{draft['id']}-")]                             # brouillon : non exporté
    assert {_category(m) for m in meds_fhir} == {"inpatient", "discharge"}
    assert all(m["category"][0]["coding"][0]["system"] == MEDREQ_CATEGORY and m["intent"] == "order" for m in meds_fhir)

    m = by_id[f"medreq-prescription-{pr['id']}-line-{pr['lines'][0]['id']}"]
    assert m["status"] == "active" and _category(m) == "discharge" and m["subject"] == {"reference": "Patient/PAT-0001"}
    assert "Paracétamol" in m["medicationCodeableConcept"]["text"] and "Doliprane" in m["medicationCodeableConcept"]["text"]
    assert INSTANT.match(m["authoredOn"]) and m["requester"]["display"] == pr["prescriber"] and m["encounter"] == {"reference": f"Encounter/enc-{adm}"}
    assert m["groupIdentifier"] == {"system": "urn:hackcure:discharge-prescription", "value": str(pr["id"])}
    d = m["dosageInstruction"][0]
    assert d["text"] == "1 g · 3/j · voie orale · pendant 5 j"
    assert d["route"] == {"text": "voie orale", "coding": [{"system": "http://snomed.info/sct", "code": "26643006", "display": "Oral route"}]}
    assert d["doseAndRate"][0]["doseQuantity"] == {"value": 1, "unit": "g", "system": UCUM, "code": "g"}
    assert d["timing"]["repeat"] == {"frequency": 3, "period": 1, "periodUnit": "d", "boundsDuration": {"value": 5, "unit": "jour", "system": UCUM, "code": "d"}}
    assert d["timing"]["code"] == {"text": "3/j"} and "timeOfDay" not in d["timing"]["repeat"]                       # aucun horaire inventé

    # dose et fréquence en texte libre non reconnu : rien n'est inventé, le texte est conservé
    free = by_id[f"medreq-prescription-{pr['id']}-line-{pr['lines'][1]['id']}"]["dosageInstruction"][0]
    assert "doseAndRate" not in free and "frequency" not in free["timing"]["repeat"] and free["timing"]["repeat"]["boundsDuration"]["value"] == 30
    assert "1 cp le matin" in free["text"] and "selon glycémie" in free["text"]
    assert {e["url"]: e["valueString"] for e in free["extension"]} == {"urn:hackcure:fhir:dose-text": "1 cp le matin", "urn:hackcure:fhir:frequency-text": "selon glycémie"}

    # ordonnance de sortie de l'ancien séjour (données de départ) : « 2 fois/j », « 1 fois/j le soir »
    seeded = [x for x in meds_fhir if _category(x) == "discharge" and x["id"] not in (m["id"],) and not x["id"].startswith(f"medreq-prescription-{pr['id']}-")]
    reps = [x["dosageInstruction"][0]["timing"]["repeat"] for x in seeded]
    assert any(r.get("frequency") == 2 and r["periodUnit"] == "d" and r["boundsDuration"]["value"] == 30 for r in reps)
    assert any(r.get("frequency") == 1 and r.get("when") == ["EVE"] for r in reps)


def test_ordonnance_de_traitement_avec_horaires(client, login):
    doctor = login("general_doctor")
    para = next(m for m in client.get("/api/pharmacy/medications").json() if m["brand"] == "Doliprane")
    o = doctor.post("/api/treatment-orders", json={"patient_id": "patient_04", "indication": "Douleur", "lines": [
        {"medication_id": para["id"], "dose": "1 g", "route": "PO", "times": ["08:00", "14:00", "20:00"], "duration_days": 2}]}).json()
    assert doctor.post(f"/api/treatment-orders/{o['id']}/sign", json={"first_dose_in_s": 3600}).json()["status"] == "active"
    meds = _resources(_check_bundle(client.get("/fhir/MedicationRequest?patient=PAT-0004"), "MedicationRequest"))
    m = next(x for x in meds if x["id"] == f"medreq-order-{o['id']}-line-{o['lines'][0]['id']}")
    assert _category(m) == "inpatient" and m["status"] == "active" and m["intent"] == "order" and m["requester"]["display"]
    d = m["dosageInstruction"][0]
    assert d["timing"]["repeat"] == {"frequency": 3, "period": 1, "periodUnit": "d", "timeOfDay": ["08:00:00", "14:00:00", "20:00:00"],
                                     "boundsDuration": {"value": 2, "unit": "jour", "system": UCUM, "code": "d"}}
    assert d["doseAndRate"][0]["doseQuantity"] == {"value": 1, "unit": "g", "system": UCUM, "code": "g"} and d["route"]["coding"][0]["code"] == "26643006"
    assert d["asNeededBoolean"] is False and "1 g" in d["text"]
    doctor.post(f"/api/treatment-orders/{o['id']}/stop")
    # traitements saisis à l'admission : posologie d'un seul tenant (« 1 g x3/j »)
    t = next(x["dosageInstruction"][0] for x in meds if x["id"].startswith("medreq-treatment-") and "1 g x3/j" in x["dosageInstruction"][0]["text"])
    assert t["doseAndRate"][0]["doseQuantity"]["value"] == 1 and t["timing"]["repeat"] == {"frequency": 3, "period": 1, "periodUnit": "d"}


# ─── $everything, droits, métadonnées ────────────────────────────────────────
def test_everything_pour_le_jeton_de_service_et_droits_par_role(client, login, anon_client):
    rep, first, last = _signed_report(client, login, "patient_02")
    pr = _signed_prescription(client, login, "patient_02", [{"brand": "Doliprane", "dosage": "1 g", "frequency": "3 fois par jour", "duration_days": 7, "route": "PO"}])
    line_id = f"medreq-prescription-{pr['id']}-line-{pr['lines'][0]['id']}"

    for caller, headers in ((anon_client, SERVICE), (client, {})):                                                   # application mobile (jeton de service = owner), puis owner
        b = _check_bundle(caller.get("/fhir/Patient/PAT-0002/$everything", headers=headers))
        res = _resources(b)
        assert {"Patient", "MedicationRequest", "DocumentReference", "Encounter", "Observation"} <= {r["resourceType"] for r in res}
        ids = [(r["resourceType"], r["id"]) for r in res]
        assert len(ids) == len(set(ids))
        med = next(r for r in res if r["id"] == line_id)
        assert _category(med) == "discharge" and med["dosageInstruction"][0]["timing"]["repeat"]["frequency"] == 3
        assert any(_category(r) == "inpatient" for r in _resources(b, "MedicationRequest"))
        doc = next(r for r in res if r["id"] == f"docref-report-{rep['id']}")
        text = base64.b64decode(doc["content"][0]["attachment"]["data"]).decode("utf-8")
        assert "PAT-0002" in text and first not in text and last not in text                                         # pseudonymisé même pour le rôle owner
    assert _check_bundle(anon_client.get("/fhir/DocumentReference?patient=PAT-0002", headers=SERVICE), "DocumentReference")["total"] >= 1

    ph = login("pharmacist")                                                                                         # pharmacien : ordonnances oui, documents non
    _is_outcome(ph.get("/fhir/DocumentReference?patient=PAT-0002"), 403, "forbidden")
    assert line_id in {r["id"] for r in _resources(_check_bundle(ph.get("/fhir/MedicationRequest?patient=PAT-0002"), "MedicationRequest"))}
    ev = _resources(_check_bundle(ph.get("/fhir/Patient/PAT-0002/$everything")))
    assert {r["resourceType"] for r in ev} == {"Patient", "AllergyIntolerance", "MedicationRequest"} and line_id in {r["id"] for r in ev}
    rc = login("receptionist")
    _is_outcome(rc.get("/fhir/DocumentReference?patient=PAT-0002"), 403, "forbidden")
    assert "DocumentReference" not in {r["resourceType"] for r in _resources(_check_bundle(rc.get("/fhir/Patient/PAT-0002/$everything")))}
    assert _check_bundle(login("nurse").get("/fhir/DocumentReference?patient=PAT-0002"), "DocumentReference")["total"] >= 1

    _is_outcome(anon_client.get("/fhir/DocumentReference?patient=PAT-0002"), 401, "login")
    _is_outcome(anon_client.get("/fhir/DocumentReference?patient=PAT-0002", headers={"Authorization": "Bearer mauvais-jeton"}), 401, "login")
    _is_outcome(client.get("/fhir/DocumentReference"), 400, "required")
    _is_outcome(client.get("/fhir/DocumentReference?patient=PAT-9999"), 404, "not-found")


def test_metadata_declare_document_reference(client):
    types = {x["type"]: x for x in client.get("/fhir/metadata").json()["rest"][0]["resource"]}
    assert types["DocumentReference"]["interaction"] == [{"code": "search-type"}] and types["DocumentReference"]["searchParam"] == [{"name": "patient", "type": "reference"}]


# ─── fonctions de correspondance pures ───────────────────────────────────────
def test_analyse_de_la_posologie():
    from app import fhir as fmap

    assert fmap.parse_dose("500 mg") == {"value": 500, "unit": "mg", "system": UCUM, "code": "mg"}
    assert fmap.parse_dose("0,5 mg")["value"] == 0.5 and fmap.parse_dose("12 UI")["code"] == "[iU]" and fmap.parse_dose("100 µg")["code"] == "ug"
    assert fmap.parse_dose("4 bouffées") == {"value": 4, "unit": "bouffées"}                                         # unité inconnue : pas de code UCUM inventé
    assert fmap.parse_dose("1 à 2 cp") is None and fmap.parse_dose("") is None and fmap.parse_dose("500 mg le matin") is None
    for text, expected in (("3/j", (3, 1, "d")), ("x2/j", (2, 1, "d")), ("2 fois/j", (2, 1, "d")), ("3 fois par jour", (3, 1, "d")), ("4 bouffées x4/j", (4, 1, "d")),
                           ("1 fois par semaine", (1, 1, "wk")), ("toutes les 8 h", (1, 8, "h")), ("matin et soir", (2, 1, "d"))):
        r = fmap.parse_frequency(text)
        assert (r["frequency"], r["period"], r["periodUnit"]) == expected, text
    assert fmap.parse_frequency("matin et soir")["when"] == ["MORN", "EVE"] and fmap.parse_frequency("1 fois/j le soir")["when"] == ["EVE"]
    assert fmap.parse_frequency("selon glycémie") is None and fmap.parse_frequency("") is None and fmap.parse_frequency("si besoin") is None
    assert fmap.parse_posology("5 mg x2/j") == {"dose": {"value": 5, "unit": "mg", "system": UCUM, "code": "mg"}, "repeat": {"frequency": 2, "period": 1, "periodUnit": "d"}}
    assert fmap.parse_posology("4000 UI/j")["repeat"] == {"frequency": 1, "period": 1, "periodUnit": "d"}
    rate = fmap.parse_posology("500 ml/24 h")
    assert "dose" not in rate and "repeat" not in rate and rate["rate"]["numerator"]["value"] == 500 and rate["rate"]["denominator"] == {"value": 24, "unit": "h", "system": UCUM, "code": "h"}

    pr = SimpleNamespace(id=4, admission_id=9, status="signed", prescriber="Dr Test", notes="", created_at=datetime(2026, 10, 10, 8, 0), signed_at=datetime(2026, 10, 10, 9, 0))
    line = SimpleNamespace(id=21, dosage="40 mg", frequency="1 fois/j", duration_days=5, route="INH", allergy_warning=True)
    med = SimpleNamespace(dci="prednisolone", brand="Solupred", dosage="20 mg", form="comprimé")
    mr = fmap.medication_request_from_prescription_line(line, pr, med, "PAT-0009", notes="Ordonnance de sortie")
    assert mr["id"] == "medreq-prescription-4-line-21" and mr["status"] == "active" and mr["authoredOn"] == "2026-10-10T09:00:00+00:00"
    assert mr["dosageInstruction"][0]["route"] == {"text": "voie inhalée"}                                           # pas de code SNOMED incertain
    assert [n["text"] for n in mr["note"]] == ["Ordonnance de sortie", "Alerte allergie signalée à la prescription"]

    doc = fmap.document_reference("docref-report-1", "PAT-0009", "discharge", "Compte rendu de sortie", "Texte accentué : é à ç", when=datetime(2026, 10, 10, 9, 0), author="Dr Test")
    assert base64.b64decode(doc["content"][0]["attachment"]["data"]).decode("utf-8") == "Texte accentué : é à ç" and doc["type"]["coding"][0]["code"] == "18842-5"
    assert doc["meta"]["security"][0]["code"] == "PSEUDED" and doc["author"] == [{"display": "Dr Test"}] and "context" not in doc

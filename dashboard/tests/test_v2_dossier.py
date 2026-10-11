"""V2 étape 2 — dossier médical : des années d'historique cohérent, frise filtrable, biologie, synthèse IA, accès par rôle, traçabilité."""
import time
from datetime import date

from .test_agents import wait_for


def test_history_is_deterministic_rich_and_coherent():
    from app.medical_history import generate
    from app.models import Patient

    p = Patient(patient_id="patient_02", code="PAT-0002", display_name="Patient B", first_name="Fatma", last_name="Gharbi", birth_date=date(1958, 4, 11), sex="F", allergies="pénicilline",
                history="Insuffisance cardiaque (FEVG 40 %), fibrillation atriale sous anticoagulant")
    docs, labs = generate(p, today=date(2026, 10, 10))
    docs2, labs2 = generate(p, today=date(2026, 10, 10))
    assert [(d["date"], d["title"]) for d in docs] == [(d["date"], d["title"]) for d in docs2] and labs == labs2      # graine fixe
    assert len(docs) >= 60 and len(labs) >= 100
    years = {d["date"].year for d in docs}
    assert 5 <= max(years) - min(years) <= 15 and max(d["date"].date() for d in docs) < date(2026, 10, 10)
    types = {d["type"] for d in docs}
    assert {"consultation", "hospitalisation", "operation", "biologie", "imagerie", "vaccination", "allergie", "chronique", "familial", "traitement", "ordonnance", "psychologie"} <= types
    assert all(d["author"] and d["service"] and d["facility"] for d in docs)
    assert any(d["type"] == "allergie" and "pénicilline" in d["title"] for d in docs)                               # cohérent avec le profil
    assert any(d["type"] == "chronique" and "Insuffisance cardiaque" in d["title"] for d in docs)
    assert any(r["code"] == "BNP" for r in labs) and not any(r["code"] == "HBA1C" for r in labs)                      # suivi adapté à la maladie
    assert docs == sorted(docs, key=lambda d: d["date"])


def test_timeline_filters_search_and_pagination(client):
    info = client.get("/api/dossier/patients").json()
    assert info["scope"] == "full" and len(info["patients"]) >= 4 and all(p["documents"] >= 50 for p in info["patients"][:4])
    page = client.get("/api/dossier/patient_01/entries?limit=20").json()
    assert page["total"] >= 50 and len(page["items"]) == 20 and page["first_date"] < page["last_date"]
    dates = [i["date"] for i in page["items"]]
    assert dates == sorted(dates, reverse=True) and "content" not in page["items"][0]
    page2 = client.get("/api/dossier/patient_01/entries?limit=20&offset=20").json()
    assert not {i["id"] for i in page["items"]} & {i["id"] for i in page2["items"]}
    bio = client.get("/api/dossier/patient_01/entries?type=biologie&limit=200").json()
    assert bio["total"] == page["facets"]["types"]["biologie"] and all(i["type"] == "biologie" for i in bio["items"])
    assert client.get("/api/dossier/patient_01/entries?q=HbA1c").json()["total"] >= 1                                 # recherche plein texte
    assert client.get("/api/dossier/patient_01/entries?q=zzzintrouvable").json()["total"] == 0
    old = client.get("/api/dossier/patient_01/entries?date_to=2019-12-31&limit=200").json()
    assert old["total"] >= 1 and all(i["date"] < "2020" for i in old["items"])
    assert client.get("/api/dossier/patient_01/entries?service=Endocrinologie").json()["total"] >= 1
    doc = client.get(f"/api/dossier/entries/{bio['items'][0]['id']}").json()
    assert doc["content"] and doc["labs"] and {"code", "value", "ref_low", "abnormal"} <= set(doc["labs"][0])


def test_lab_series_and_clinical_profile(client):
    codes = client.get("/api/dossier/patient_01/labs").json()
    assert any(c["code"] == "HBA1C" and c["count"] >= 3 for c in codes)
    s = client.get("/api/dossier/patient_01/labs?code=HBA1C").json()
    pts = [p["date"] for p in s["points"]]
    assert s["unit"] == "%" and len(pts) >= 3 and pts == sorted(pts)
    prof = client.get("/api/dossier/patient_02/profile").json()
    assert any(a["allergen"] == "pénicilline" for a in prof["allergies"])
    assert any("Insuffisance cardiaque" in c["label"] for c in prof["chronic"]) and prof["long_term_treatments"] and prof["hospital_treatments"]


def test_ai_summary_is_cached_and_regenerable(client):
    assert client.post("/api/dossier/patient_03/summary").status_code == 202
    s = wait_for(lambda: (lambda d: d if d["status"] == "ready" else None)(client.get("/api/dossier/patient_03/summary").json()))
    assert s and s["summary"] and any("iode" in a for a in s["allergies"]) and any("BPCO" in c for c in s["chronic"]) and "validation médicale requise" in s["disclaimer"]
    first = s["generated_at"]
    assert client.get("/api/dossier/patient_03/summary").json()["generated_at"] == first                              # en cache
    time.sleep(0.05)
    client.post("/api/dossier/patient_03/summary")
    assert wait_for(lambda: client.get("/api/dossier/patient_03/summary").json().get("generated_at", first) != first)
    assert client.get("/print/dossier/summary/patient_03").status_code == 200
    doc = client.get("/api/dossier/patient_03/entries?limit=1").json()["items"][0]
    assert client.get(f"/print/dossier/entry/{doc['id']}").status_code == 200


def test_access_rules_by_role(login):
    doctor, nurse, psy, recep, pharma = login("general_doctor"), login("nurse"), login("psychiatrist"), login("receptionist"), login("pharmacist")
    body = {"type": "consultation", "title": "Visite du matin", "content": "Patient apyrétique, bon état général."}
    # médecins et psychiatre : lecture et écriture ; infirmier : lecture seule
    created = doctor.post("/api/dossier/patient_04/entries", json=body)
    assert created.status_code == 201 and created.json()["source"] == "plateforme"
    assert psy.post("/api/dossier/patient_04/entries", json={**body, "type": "psychologie", "title": "Entretien"}).status_code == 201
    assert nurse.get("/api/dossier/patient_04/entries").json()["scope"] == "full"
    assert nurse.post("/api/dossier/patient_04/entries", json=body).status_code == 403
    assert doctor.patch(f"/api/dossier/entries/{created.json()['id']}", json={"content": "Complété."}).status_code == 200
    archive = doctor.get("/api/dossier/patient_04/entries?type=imagerie").json()["items"][0]
    assert doctor.patch(f"/api/dossier/entries/{archive['id']}", json={"content": "x"}).status_code == 409                # archive non modifiable
    # réceptionniste : identité et admissions seulement
    r = recep.get("/api/dossier/patient_04/entries?limit=200").json()
    assert r["scope"] == "identity" and r["items"] and all(i["type"] == "hospitalisation" and i["summary"] == "" and i["title"] == "Hospitalisation" for i in r["items"])
    assert set(recep.get("/api/dossier/patient_04/profile").json()) <= {"scope", "patient_id", "code", "name", "age", "sex", "room"}
    assert recep.get(f"/api/dossier/entries/{archive['id']}").status_code == 403 and recep.get("/api/dossier/patient_04/labs").status_code == 403
    assert recep.get("/api/dossier/patient_04/summary").status_code == 403
    # pharmacien : allergies et traitements seulement
    ph = pharma.get("/api/dossier/patient_04/entries?limit=200").json()
    assert ph["scope"] == "pharmacy" and ph["items"] and {i["type"] for i in ph["items"]} <= {"allergie", "traitement", "ordonnance"}
    prof = pharma.get("/api/dossier/patient_04/profile").json()
    assert prof["allergies"] and "chronic" not in prof and "history" not in prof
    assert pharma.get(f"/api/dossier/entries/{archive['id']}").status_code == 403


def test_every_access_is_audited(client, login):
    from sqlmodel import select

    from app.db import session_scope
    from app.models import AuditLog

    nurse = login("nurse")
    nurse.get("/api/dossier/patient_02/entries?q=cardio")
    doc = nurse.get("/api/dossier/patient_02/entries?limit=1").json()["items"][0]
    nurse.get(f"/api/dossier/entries/{doc['id']}")
    with session_scope() as s:
        rows = s.exec(select(AuditLog).where(AuditLog.user == "infirmier", AuditLog.entity.like("medical_record%")).order_by(AuditLog.id.desc()).limit(10)).all()
        kinds = {(r.entity, r.action) for r in rows}
    assert ("medical_record", "read") in kinds and ("medical_record_entry", "read") in kinds

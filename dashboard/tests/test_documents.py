"""Phase F : patients, historique, pharmacie, ordonnance (alerte allergie), rapport médecin, rapport de garde, impression."""


def test_patients_list_and_card(client, login):
    rows = client.get("/api/records").json()
    assert len(rows) >= 4 and {r["patient_id"] for r in rows} >= {"patient_01", "patient_02", "patient_03", "patient_04"}
    p = client.get("/api/records/patient_02").json()
    assert p["room"] == "102" and "pénicilline" in p["allergies"] and p["treatments"] and "room_state" in p
    assert login("pharmacist").get("/api/records").status_code == 403
    assert login("receptionist").get("/api/records").status_code == 200


def test_patient_crud_admit_discharge(client, login):
    rec = login("receptionist")
    r = rec.post("/api/records", json={"first_name": "Test", "last_name": "Dupont", "birth_date": "1950-02-03", "sex": "F", "allergies": "iode", "fall_risk": "low"})
    assert r.status_code == 201
    pid = r.json()["patient_id"]
    assert r.json()["room"] is None
    # admission impossible dans une chambre occupée
    assert rec.post(f"/api/records/{pid}/admit", json={"room": "101", "reason": "test"}).status_code == 409
    # l'infirmier modifie, le pharmacien non
    assert login("nurse").patch(f"/api/records/{pid}", json={"history": "RAS"}).status_code == 200
    assert login("pharmacist").patch(f"/api/records/{pid}", json={"history": "x"}).status_code == 403
    assert login("nurse").post("/api/records", json={"first_name": "A", "last_name": "B", "birth_date": "1950-01-01"}).status_code == 403
    # sortie du patient 104 puis admission du nouveau en 104, puis retour
    assert client.post("/api/records/patient_04/discharge").status_code == 200
    assert client.get("/api/records").json() and client.get("/api/records/patient_04").json()["room"] is None
    assert "patient_04" not in client.get("/api/records?active_only=1").text
    r = rec.post(f"/api/records/{pid}/admit", json={"room": "104", "reason": "observation"})
    assert r.status_code == 200 and r.json()["room"] == "104"
    assert client.get("/api/records").json()[0]["code"].startswith("PAT-")
    legacy = client.get("/api/records").json()
    assert client.get("/api/rooms/104").json()["patient"]["patient_id"] == pid
    # retour à la situation initiale
    assert client.post(f"/api/records/{pid}/discharge").status_code == 200
    assert rec.post("/api/records/patient_04/admit", json={"room": "104", "reason": "Suites de prothèse de hanche"}).status_code == 200
    assert rec.delete(f"/api/records/{pid}").status_code == 400  # historique → archivage seulement
    hist = client.get("/api/records/patient_01/history").json()
    assert len(hist["admissions"]) >= 2 and any(a["reports"] for a in hist["admissions"]) and any(a["prescriptions"] for a in hist["admissions"])


def test_pharmacy_crud_and_alerts(client, login):
    meds = client.get("/api/pharmacy/medications").json()
    assert len(meds) >= 25
    alerts = client.get("/api/pharmacy/alerts").json()
    assert alerts["low_stock"] and alerts["expiring"]
    ph = login("pharmacist")
    r = ph.post("/api/pharmacy/medications", json={"dci": "Test-DCI", "brand": "TestBrand", "stock": 3, "threshold": 5, "allergen_tags": "iode"})
    assert r.status_code == 201 and r.json()["low_stock"]
    mid = r.json()["id"]
    assert ph.patch(f"/api/pharmacy/medications/{mid}", json={"stock": 50}).json()["low_stock"] is False
    assert login("nurse").patch(f"/api/pharmacy/medications/{mid}", json={"stock": 1}).status_code == 403
    assert login("nurse").get("/api/pharmacy/medications").status_code == 200
    # traitement avec conflit d'allergie (patient_03 allergique à l'iode)
    adm = client.get("/api/records/patient_03").json()["admission"]["id"]
    t = ph.post("/api/pharmacy/treatments", json={"admission_id": adm, "medication_id": mid, "posology": "1/j"})
    assert t.status_code == 201 and t.json()["allergy_conflicts"] == ["iode"]
    tr = client.get(f"/api/pharmacy/treatments?admission_id={adm}").json()
    assert any(x["allergy_conflicts"] for x in tr)
    assert ph.delete(f"/api/pharmacy/treatments/{t.json()['id']}").status_code == 204
    assert ph.delete(f"/api/pharmacy/medications/{mid}").status_code == 400  # utilisé par un traitement (clos)


def test_prescription_allergy_alert_and_sign(client, login):
    doc = login("general_doctor")
    adm = client.get("/api/records/patient_02").json()["admission"]["id"]  # allergique à la pénicilline
    meds = {m["brand"]: m for m in client.get("/api/pharmacy/medications").json()}
    chk = doc.post("/api/prescriptions/check", json={"admission_id": adm, "medication_id": meds["Clamoxyl"]["id"]}).json()
    assert chk["conflicts"] == ["pénicilline"] and "ALLERGIE" in chk["warning"]
    r = doc.post("/api/prescriptions", json={"admission_id": adm, "notes": "test", "lines": [
        {"medication_id": meds["Clamoxyl"]["id"], "dosage": "500 mg", "frequency": "3/j", "duration_days": 7},
        {"medication_id": meds["Doliprane"]["id"], "dosage": "1 g", "frequency": "3/j", "duration_days": 5},
    ]})
    assert r.status_code == 201
    pr = r.json()
    assert pr["has_allergy_warning"] and pr["warnings"][0]["allergies"] == ["pénicilline"]
    assert pr["lines"][0]["allergy_warning"] and not pr["lines"][1]["allergy_warning"]
    assert doc.post(f"/api/prescriptions/{pr['id']}/sign").status_code == 409
    # correction : on retire la ligne contre-indiquée puis signature
    r = doc.patch(f"/api/prescriptions/{pr['id']}", json={"lines": [{"medication_id": meds["Doliprane"]["id"], "dosage": "1 g", "frequency": "3/j", "duration_days": 5}]})
    assert r.json()["has_allergy_warning"] is False
    signed = doc.post(f"/api/prescriptions/{pr['id']}/sign").json()
    assert signed["status"] == "signed" and signed["signed_at"]
    assert doc.patch(f"/api/prescriptions/{pr['id']}", json={"notes": "x"}).status_code == 400
    # l'infirmier voit mais n'écrit pas ; le pharmacien ne voit pas
    assert login("nurse").get(f"/api/prescriptions/{pr['id']}").status_code == 200
    assert login("nurse").post("/api/prescriptions", json={"admission_id": adm, "lines": []}).status_code == 403
    assert login("pharmacist").get("/api/prescriptions").status_code == 403
    # impression
    html = login("nurse").get(f"/print/prescription/{pr['id']}").text
    assert "Ordonnance" in html and "Paracétamol" in html and "Signée" in html


def test_medical_report_draft_edit_sign_print(client, login):
    doc = login("duty_doctor")
    adm = client.get("/api/records/patient_01").json()["admission"]["id"]
    r = doc.post("/api/reports/draft", json={"admission_id": adm})
    assert r.status_code == 201
    rep = r.json()
    assert rep["ai_draft"] and rep["status"] == "draft" and "PAT-0001" in rep["content"] and "Mohamed Ben Salah" not in rep["content"] and "à compléter" in rep["content"].lower()
    r = doc.patch(f"/api/reports/{rep['id']}", json={"content": rep["content"] + "\n\nÉvolution : favorable."})
    assert "favorable" in r.json()["content"]
    assert login("nurse").patch(f"/api/reports/{rep['id']}", json={"content": "x"}).status_code == 403
    signed = doc.post(f"/api/reports/{rep['id']}/sign").json()
    assert signed["status"] == "signed"
    assert doc.patch(f"/api/reports/{rep['id']}", json={"content": "x"}).status_code == 400
    html = doc.get(f"/print/report/{rep['id']}").text
    assert "Signé" in html and "Ben Salah" in html
    assert login("pharmacist").get(f"/print/report/{rep['id']}").status_code == 403
    assert len(client.get("/api/reports?patient_id=patient_01").json()) >= 2  # ancien rapport seedé + nouveau
    logs = client.get("/api/agents/logs?agent=ReportAgent").json()
    assert logs and "MedicalReport" in logs[0]["output"]


def test_shift_report_generate_validate_print(client, login):
    nurse = login("nurse")
    r = nurse.post("/api/shift-reports/generate", json={"hours": 12})
    assert r.status_code == 201
    rep = r.json()
    assert rep["status"] == "draft" and "Rapport de garde" in rep["content"] and "Chambre 101" in rep["content"] and "Points d'attention" in rep["content"]
    assert "humeur" in rep["content"].lower() or "Humeur" in rep["content"]
    r = nurse.patch(f"/api/shift-reports/{rep['id']}", json={"content": rep["content"] + "\n- Note de l'infirmier."})
    assert r.status_code == 200
    v = nurse.post(f"/api/shift-reports/{rep['id']}/validate").json()
    assert v["status"] == "validated" and v["validated_by"]
    assert nurse.patch(f"/api/shift-reports/{rep['id']}", json={"content": "x"}).status_code == 400
    assert login("receptionist").post("/api/shift-reports/generate", json={"hours": 8}).status_code == 403
    assert login("receptionist").get("/api/shift-reports").status_code == 200
    html = nurse.get(f"/print/shift/{rep['id']}").text
    assert "Validé" in html and "Chambre 101" in html


def test_camera_status_without_edge(client):
    s = client.get("/api/camera/status").json()
    assert s["101"]["configured"] is False and s["101"]["blurred"] is True
    assert client.get("/api/camera/101/stream").status_code == 404

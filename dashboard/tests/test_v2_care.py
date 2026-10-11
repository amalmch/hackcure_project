"""
V2 étape 4 — diagnostics live et fil médecin ↔ infirmier, ordonnance de traitement hospitalière, plan
d'administration horodaté, rappels et relances, comptes rendus d'intervention.
"""
import time

import pytest

from app.clinical.diagnostics import hypotheses, interactions

from .test_agents import msg, open_risks, vision, wait_for


def med(client, brand):
    return next(m for m in client.get("/api/pharmacy/medications").json() if m["brand"] == brand)


# ── règles déterministes ─────────────────────────────────────────────────────
def test_hypotheses_are_transparent_and_qualitative():
    hs = hypotheses({"vitals": {"tempC": 39.2, "hr": 124, "rr": 26, "sys": 92, "spo2": 91}, "news2": 9, "qsofa": 2, "history": "HTA, diabète de type 2", "treatments": "Metformine",
                     "labs": {"CRP": {"value": 180}, "PCT": {"value": 4.2}, "LACT": {"value": 3.1}}, "open_risks": ["fever"]})
    top = hs[0]
    assert top["code"] == "sepsis" and top["probability"] == "élevée" and any("qSOFA 2/3" in p for p in top["pros"]) and any("lactates" in p for p in top["pros"]) and top["exams"]
    assert all(h["probability"] in ("faible", "modérée", "élevée") for h in hs)
    calm = hypotheses({"vitals": {"tempC": 36.8, "hr": 74, "rr": 16, "sys": 124, "spo2": 98}, "news2": 0, "qsofa": 0, "history": "", "treatments": "", "labs": {}, "open_risks": []})
    assert calm == []
    hf = hypotheses({"vitals": {"hr": 112, "rr": 24, "spo2": 92, "sys": 118, "tempC": 36.9}, "news2": 5, "qsofa": 1, "history": "Insuffisance cardiaque (FEVG 40 %), fibrillation atriale", "treatments": "", "labs": {"BNP": {"value": 1800}}})
    assert hf[0]["code"] == "heart_failure"


def test_simple_interactions():
    assert interactions("Kétoprofène", ["Énoxaparine", "Paracétamol"]) and "hémorragique" in interactions("Kétoprofène", ["Énoxaparine"])[0]
    assert interactions("Énoxaparine", ["Ibuprofène"])                                  # dans les deux sens
    assert interactions("Paracétamol", ["Énoxaparine", "Metformine"]) == []


# ── ordonnance de traitement → plan d'administration ─────────────────────────
def test_treatment_order_allergy_interaction_and_plan(client, login):
    doctor, nurse = login("general_doctor"), login("nurse")
    para, keto = med(client, "Doliprane"), med(client, "Profénid")
    # patient_04 : allergique aux AINS, sous énoxaparine ⇒ alerte d'allergie ET d'interaction
    lovenox = med(client, "Lovenox")
    chk = doctor.post("/api/treatment-orders/check", json={"patient_id": "patient_04", "lines": [{"medication_id": lovenox["id"]}, {"medication_id": keto["id"]}]}).json()[1]
    assert "ALLERGIE" in chk["allergy_alert"] and "hémorragique" in chk["interaction_alert"]
    body = {"patient_id": "patient_04", "indication": "Douleur post-opératoire", "lines": [
        {"medication_id": keto["id"], "dose": "100 mg", "route": "IV", "times": ["08:00", "20:00"], "duration_days": 2}]}
    assert nurse.post("/api/treatment-orders", json=body).status_code == 403
    bad = doctor.post("/api/treatment-orders", json=body).json()
    assert bad["has_alert"] and doctor.post(f"/api/treatment-orders/{bad['id']}/sign", json={}).status_code == 409      # signature refusée
    assert doctor.post("/api/treatment-orders", json={**body, "lines": [{"medication_id": para["id"], "dose": "1 g"}]}).status_code == 400  # horaires requis
    # ordonnance correcte : prises programmées + prise conditionnelle
    body["lines"] = [{"medication_id": para["id"], "dose": "1 g", "route": "PO", "times": ["08:00", "14:00", "20:00"], "duration_days": 2},
                     {"medication_id": para["id"], "dose": "1 g", "route": "PO", "prn": True, "condition_metric": "tempC", "condition_op": ">", "condition_value": 38.5, "min_interval_h": 6}]
    o = doctor.post("/api/treatment-orders", json=body).json()
    assert o["status"] == "draft" and o["lines"][1]["condition"] == "si température > 38.5 °C" and not o["has_alert"]
    signed = doctor.post(f"/api/treatment-orders/{o['id']}/sign", json={"first_dose_in_s": 3600}).json()
    assert signed["status"] == "active" and signed["doses"]["total"] >= 5                                                 # 3 prises/j sur 2 jours
    plan = nurse.get("/api/care-plan?room=104&hours=72").json()
    mine = [d for d in plan["upcoming"] if d["order_id"] == o["id"]]
    assert mine and mine == sorted(mine, key=lambda d: d["due_at"]) and all(d["label"] == "Paracétamol 1 g PO" for d in mine)
    assert login("pharmacist").get("/api/treatment-orders?patient_id=patient_04").status_code == 200
    assert login("receptionist").get("/api/care-plan").status_code == 403
    doctor.post(f"/api/treatment-orders/{o['id']}/stop")
    assert not [d for d in nurse.get("/api/care-plan?room=104&hours=72").json()["upcoming"] if d["order_id"] == o["id"]]


def test_reminder_administration_stock_and_relaunch(client, login):
    client.post("/api/demo/reset")
    doctor, nurse = login("duty_doctor"), login("nurse")
    para = med(client, "Doliprane")
    stock = para["stock"]
    o = doctor.post("/api/treatment-orders", json={"patient_id": "patient_02", "indication": "Antalgie", "lines": [
        {"medication_id": para["id"], "dose": "1 g", "route": "PO", "times": ["08:00", "20:00"], "duration_days": 1}]}).json()
    doctor.post(f"/api/treatment-orders/{o['id']}/sign", json={"first_dose_in_s": 0})
    due = wait_for(lambda: [d for d in nurse.get("/api/care-plan?room=102").json()["due"] if d["order_id"] == o["id"]])
    assert due, "la première prise doit être « à faire maintenant »"
    did = due[0]["id"]
    # rappel à l'heure de la prise
    assert wait_for(lambda: [n for n in client.get("/api/notifications").json()["items"] if "Prise à administrer — chambre 102" in n["title"]], timeout=10)
    # retard (délais de test : relance 1 s, médecin 2,5 s)
    assert wait_for(lambda: [n for n in client.get("/api/notifications").json()["items"] if "Prise en retard — chambre 102" in n["title"]], timeout=12)
    assert wait_for(lambda: open_risks(client, "102", "medication_late"), timeout=8)
    esc = wait_for(lambda: [n for n in client.get("/api/notifications").json()["items"] if "Prise non administrée — chambre 102" in n["title"]], timeout=12)
    assert esc and esc[0]["target_role"] == "duty_doctor"
    assert [d for d in nurse.get("/api/care-plan?room=102").json()["late"] if d["id"] == did]
    # administration : heure, auteur, remarque ; stock de la pharmacie décrémenté
    assert login("pharmacist").post(f"/api/care-plan/doses/{did}/give", json={}).status_code == 403
    g = nurse.post(f"/api/care-plan/doses/{did}/give", json={"note": "prise avec un verre d'eau"}).json()
    assert g["status"] == "given" and g["given_by"] == "infirmier" and g["given_at"] and g["note"] and g["stock_after"] == stock - 1
    assert med(client, "Doliprane")["stock"] == stock - 1
    assert nurse.post(f"/api/care-plan/doses/{did}/give", json={}).status_code == 409
    # le risque « prise en retard » se vérifie sur le plan : plus aucune prise en retard dans la chambre
    from app.agents.followup import verify_risk

    ok, why = verify_risk("medication_late", {"room": "102"})
    assert ok and "enregistrées" in why
    from app import resolutions

    resolutions._catalog = None
    assert resolutions.plan_for("medication_late")["scenario"] == "medication_resolves"
    # « Non administré » exige un motif
    other = [d for d in nurse.get("/api/care-plan?room=102&hours=72").json()["upcoming"] if d["order_id"] == o["id"]]
    if other:
        assert nurse.post(f"/api/care-plan/doses/{other[0]['id']}/skip", json={"reason": " "}).status_code == 400
        s = nurse.post(f"/api/care-plan/doses/{other[0]['id']}/skip", json={"reason": "patient à jeun pour examen"}).json()
        assert s["status"] == "not_given" and s["reason"] == "patient à jeun pour examen"
    doctor.post(f"/api/treatment-orders/{o['id']}/stop")


def test_conditional_dose_is_triggered_by_the_condition(client, login):
    doctor, nurse = login("duty_doctor"), login("nurse")
    para = med(client, "Perfalgan")
    o = doctor.post("/api/treatment-orders", json={"patient_id": "patient_03", "indication": "Antipyrétique", "lines": [
        {"medication_id": para["id"], "dose": "1 g", "route": "IV", "prn": True, "condition_metric": "tempC", "condition_op": ">", "condition_value": 38.5, "min_interval_h": 6}]}).json()
    assert doctor.post(f"/api/treatment-orders/{o['id']}/sign", json={}).json()["doses"]["total"] == 0                     # rien de programmé tant que la condition n'est pas remplie
    for _ in range(3):
        client.post("/api/ingest", json=msg("hackcure/room/103/device/103-thermometer", type="thermometer", metrics={"tempC": 39.0}))
    cond = wait_for(lambda: [d for d in nurse.get("/api/care-plan?room=103").json()["due"] if d["order_id"] == o["id"]], timeout=10)
    assert cond and cond[0]["conditional"] and "38.5" in cond[0]["condition"] and "mesuré : 39" in cond[0]["note"]
    nurse.post(f"/api/care-plan/doses/{cond[0]['id']}/give", json={})
    time.sleep(4)                                                                                                         # intervalle minimal de 6 h : pas de nouvelle prise
    assert len([d for d in nurse.get("/api/care-plan?room=103").json()["due"] if d["order_id"] == o["id"]]) == 0
    doctor.post(f"/api/treatment-orders/{o['id']}/stop")
    client.post("/api/ingest", json=msg("hackcure/room/103/device/103-thermometer", type="thermometer", metrics={"tempC": 36.9}))


# ── diagnostics live et fil de communication ─────────────────────────────────
def test_live_hypotheses_decision_and_care_thread(client, login):
    for _ in range(3):
        client.post("/api/ingest", json=msg("hackcure/room/104/device/104-ecg", type="ecg", metrics={"hr": 128, "rhythm": "tachy", "rr": 27}))
        client.post("/api/ingest", json=msg("hackcure/room/104/device/104-bp", type="bp", metrics={"sys": 88, "dia": 54, "map": 65}))
    d = wait_for(lambda: (lambda x: x if any(h["code"] == "sepsis" for h in x["hypotheses"]) else None)(client.get("/api/diagnostics/patient_04").json()), timeout=12)
    assert d, "hypothèse sepsis attendue"
    h = next(x for x in d["hypotheses"] if x["code"] == "sepsis")
    assert h["probability"] in ("modérée", "élevée") and h["pros"] and h["exams"] and d["scores"]["qsofa"] >= 2 and "validation médicale requise" in d["disclaimer"]
    # synthèse IA dans le fil (repli local, réponse simulée en test)
    assert wait_for(lambda: [m for m in client.get("/api/diagnostics/patient_04").json()["messages"] if m["kind"] == "ai"], timeout=10)
    doctor, nurse = login("duty_doctor"), login("nurse")
    assert nurse.post(f"/api/diagnostics/hypotheses/{h['id']}/decision", json={"status": "confirmed"}).status_code == 403
    c = doctor.post(f"/api/diagnostics/hypotheses/{h['id']}/decision", json={"status": "confirmed", "note": "hémocultures prélevées"}).json()
    assert c["status"] == "confirmed" and c["decided_by"] == "medecin_garde"
    # zone de communication : mention @rôle ⇒ notification
    m = nurse.post("/api/diagnostics/patient_04/messages", json={"body": "@medecin_garde TA remontée à 104/62 après remplissage, je recontrôle dans 15 min."}).json()
    assert m["mentions"] == ["duty_doctor"] and m["role"] == "nurse"
    thread = client.get("/api/diagnostics/patient_04").json()["messages"]
    assert [x["kind"] for x in thread[-2:]] == ["decision", "message"] and "confirme l'hypothèse" in thread[-2]["body"]
    assert any("Message de" in n["title"] and n["target_role"] == "duty_doctor" for n in client.get("/api/notifications").json()["items"])
    assert login("receptionist").get("/api/diagnostics/patient_04").status_code == 403
    # une hypothèse confirmée reste affichée même si les éléments disparaissent
    for _ in range(3):
        client.post("/api/ingest", json=msg("hackcure/room/104/device/104-ecg", type="ecg", metrics={"hr": 78, "rhythm": "sinus", "rr": 16}))
        client.post("/api/ingest", json=msg("hackcure/room/104/device/104-bp", type="bp", metrics={"sys": 122, "dia": 74, "map": 90}))
    time.sleep(2.5)
    assert any(x["code"] == "sepsis" and x["status"] == "confirmed" for x in client.get("/api/diagnostics/patient_04").json()["hypotheses"])


# ── compte rendu d'intervention ──────────────────────────────────────────────
def test_resolved_risk_produces_an_intervention_report_to_sign(client, login):
    client.post("/api/demo/reset")
    client.post("/api/ingest", json=msg("hackcure/room/103/call", pressed=True))
    risk = wait_for(lambda: open_risks(client, "103", "call"))[0]
    nurse = login("nurse")
    nurse.post(f"/api/risks/{risk['id']}/ack")
    client.post("/api/ingest", json=vision("103", "lying_bed", "awake_bed", persons=2))
    time.sleep(0.6)
    client.post("/api/ingest", json=vision("103", "lying_bed", "awake_bed", persons=1))
    assert wait_for(lambda: client.get(f"/api/risks/{risk['id']}").json()["status"] == "resolved", timeout=10)
    draft = wait_for(lambda: [r for r in nurse.get("/api/interventions?status=draft&patient_id=patient_03").json() if r["risk_id"] == risk["id"] and r["content"]], timeout=10)
    assert draft, "brouillon de compte rendu attendu"
    r = draft[0]
    assert "Appel du patient" in r["title"] and "## Intervention" in r["content"] and "brouillon IA" in r["author"]
    assert login("receptionist").get("/api/interventions").status_code == 403
    signed = nurse.post(f"/api/interventions/{r['id']}/sign", json={"content": r["content"] + "\n\nPatient rassuré, sonnette à portée de main."}).json()
    assert signed["status"] == "signed" and "Sami Trabelsi" in signed["author"] and "sonnette à portée" in signed["content"]
    # rangé dans le dossier médical
    docs = client.get("/api/dossier/patient_03/entries?type=intervention").json()["items"]
    assert any(x["id"] == r["id"] and x["status"] == "signed" for x in docs)

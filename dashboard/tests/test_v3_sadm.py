"""
V3, étape 6 — SADM : indice de confiance mesurable, paramètres déclencheurs, validation / rejet tracés,
bandeau consultatif, parcours en 3 actions maximum.
"""
import json

from .test_agents import msg, open_risks, vision, wait_for


def test_confidence_formulas_are_deterministic_and_published():
    from app.api import sadm

    a = sadm.risk_confidence("fall", "", 0.9, 0)
    assert a["pct"] == 90 and a["level"] == "élevée" and "détecteur de vision" in a["method"] and "90 %" in a["method"]
    b = sadm.risk_confidence("fall", "12:00 signal répété par VisionAgent\n12:01 signal répété par VisionAgent", 0.9, 1)
    assert b["pct"] == 97                                                   # persistance et concordance augmentent l'indice (borné)
    c = sadm.risk_confidence("hypotension", "12:05 signal revenu dans les limites (PAS 110) — à confirmer", None, 0)
    assert c["pct"] == 57 and c["level"] == "faible" and "-15" in c["method"]
    assert sadm.risk_confidence("predicted_sepsis", "", None, 0, "faible")["pct"] == 45
    h = sadm.hypothesis_confidence("modérée", ["a", "b"], ["c"])
    assert h["pct"] == 61 and "éléments contre (1)" in h["method"]
    p = sadm.psych_confidence({"questionnaire": True, "expressions": {"total": 30}, "sleep_hours": 6})
    assert p["pct"] == 95 and sadm.psych_confidence({})["pct"] == 25
    assert sadm.prediction_confidence("élevée", ["x"] * 3)["pct"] == 91 and "pas la probabilité" in sadm.prediction_confidence("élevée", [])["method"]


def test_risk_recommendation_shows_confidence_triggers_and_is_validated_with_audit(client, login):
    client.post("/api/demo/reset")
    client.post("/api/ingest", json=vision("104", "lying_bed", "awake_bed"))
    client.post("/api/ingest", json=vision("104", "on_floor", "fall", zone="floor"))
    risk = wait_for(lambda: open_risks(client, "104", "fall"))[0]
    cfg = client.get("/api/sadm/config").json()
    assert cfg["enabled"] and cfg["banner"] == "Recommandation consultative — la décision et la signature restent celles du médecin" and cfg["max_actions"] == 3
    d = client.get(f"/api/sadm/explain?kind=risk&ref={risk['id']}").json()
    assert 30 <= d["confidence"]["pct"] <= 97 and d["confidence"]["level"] in ("faible", "modérée", "élevée") and d["confidence"]["method"].startswith("Indice =")
    assert any("posture on_floor" in t for t in d["triggers"]) and any("sévérité critical" in t for t in d["triggers"])
    assert d["decision"] is None and d["can_decide"] is True and "pas une probabilité clinique validée" in d["disclaimer"]
    # l'infirmier valide, avec un motif : tracé dans AuditLog (qui, quand, quoi, IP) et dans l'historique du risque
    nurse = login("nurse")
    r = nurse.post("/api/sadm/decisions", json={"kind": "risk", "ref": str(risk["id"]), "decision": "validated", "reason": "patient vu au sol"})
    assert r.status_code == 201 and r.json()["decision"]["decision"] == "validated" and r.json()["decision"]["by"] == "infirmier"
    d = client.get(f"/api/sadm/explain?kind=risk&ref={risk['id']}").json()
    assert d["decision"]["reason"] == "patient vu au sol" and d["decision"]["role"] == "nurse"
    log = client.get("/api/sadm/decisions").json()[0]
    assert log["user"] == "infirmier" and log["kind"] == "risk" and log["ref"] == str(risk["id"]) and log["details"]["ip"] and log["details"]["confidence_pct"] == d["confidence"]["pct"]
    assert "recommandation validée par infirmier — patient vu au sol" in client.get(f"/api/risks/{risk['id']}").json()["notes"]
    # un médecin rejette ensuite : la dernière décision fait foi, les deux restent au journal
    assert login("duty_doctor").post("/api/sadm/decisions", json={"kind": "risk", "ref": str(risk["id"]), "decision": "rejected"}).status_code == 201
    assert client.get(f"/api/sadm/explain?kind=risk&ref={risk['id']}").json()["decision"]["decision"] == "rejected"
    assert len([x for x in client.get("/api/sadm/decisions").json() if x["ref"] == str(risk["id"])]) == 2
    # garde-fous : rôle non soignant, décision inconnue, recommandation inconnue
    assert login("receptionist").post("/api/sadm/decisions", json={"kind": "risk", "ref": str(risk["id"]), "decision": "validated"}).status_code == 403
    assert nurse.post("/api/sadm/decisions", json={"kind": "risk", "ref": str(risk["id"]), "decision": "maybe"}).status_code == 400
    assert nurse.post("/api/sadm/decisions", json={"kind": "risk", "ref": "999999", "decision": "validated"}).status_code == 404
    assert login("pharmacist").get(f"/api/sadm/explain?kind=risk&ref={risk['id']}").status_code == 403


def test_every_kind_of_recommendation_is_explained(client):
    client.post("/api/demo/reset")
    # fièvre vraie en 102 → parcours fièvre + bilan biologique proposé, hypothèses diagnostiques, prédiction
    for _ in range(4):
        client.post("/api/ingest", json=msg("hackcure/room/102/device/102-thermometer", type="thermometer", metrics={"tempC": 39.3}))
        client.post("/api/ingest", json=msg("hackcure/room/102/device/102-ecg", type="ecg", metrics={"hr": 124, "rhythm": "tachy", "rr": 26}))
        client.post("/api/ingest", json=msg("hackcure/room/102/device/102-bp", type="bp", metrics={"sys": 88, "dia": 54, "map": 65}))
    fever = wait_for(lambda: open_risks(client, "102", "fever"), timeout=10)[0]
    f = wait_for(lambda: (lambda r: r.json() if r.status_code == 200 and len(r.json()["triggers"]) >= 2 else None)(client.get(f"/api/sadm/explain?kind=fever&ref={fever['id']}")), timeout=10)
    assert f and f["triggers"][0].startswith("Critère :") and "qSOFA" in f["triggers"][1] and f["confidence"]["pct"] >= 70
    hyps = wait_for(lambda: client.get("/api/diagnostics/patient_02").json()["hypotheses"], timeout=15)
    assert hyps
    h = client.get(f"/api/sadm/explain?kind=hypothesis&ref={hyps[0]['id']}").json()
    assert h["title"] == hyps[0]["label"] and any(t.startswith("Pour :") for t in h["triggers"]) and "probabilité des règles" in h["confidence"]["method"]
    assert client.get("/api/sadm/explain", params={"kind": "hypothesis", "patient": "patient_02", "label": hyps[0]["label"]}).json()["ref"] == str(hyps[0]["id"])
    preds = wait_for(lambda: [p for p in client.get("/api/predictions/patient_02").json()["predictions"] if p["risk"] > 0], timeout=15)
    assert preds
    p = client.get("/api/sadm/explain", params={"kind": "prediction", "patient": "patient_02", "label": preds[0]["label"]}).json()
    assert p["triggers"][0].startswith("Risque ") and "pas la probabilité" in p["confidence"]["method"]
    ps = wait_for(lambda: (lambda r: r.json() if r.status_code == 200 else None)(client.get("/api/sadm/explain?kind=psych&ref=patient_02")), timeout=15)
    assert ps and ps["triggers"][0].startswith("Bien-être") and "complétude" in ps["confidence"]["method"]
    assert client.get("/api/sadm/explain?kind=unknown&ref=1").status_code == 400


def test_switch_banner_and_three_action_paths(client, login, monkeypatch):
    html = client.get("/").text
    assert "/static/js/v3/sadm.js" in html and "/static/css/v3.css" in html
    js = client.get("/static/js/v3/sadm.js").text
    assert "Recommandation consultative — la décision et la signature restent celles du médecin" in js
    for needle in ("Indice de confiance", "Paramètres cliniques déclencheurs", "/api/sadm/decisions", "✔ Valider", "✖ Rejeter", "/api/sadm/to-sign", "Motif (facultatif)"):
        assert needle in js, needle
    assert "#sadm-banner" in client.get("/static/css/v3.css").text
    # ordonnances en attente de signature : accessibles depuis la cloche pour un médecin seulement
    doc = login("general_doctor")
    med = doc.get("/api/pharmacy/medications").json()[0]
    from sqlmodel import select

    from app.db import session_scope
    from app.models import Admission

    with session_scope() as s:
        adm_id = s.exec(select(Admission.id).where(Admission.room_code == "103", Admission.discharged_at.is_(None))).first()
    pr = doc.post("/api/prescriptions", json={"admission_id": adm_id, "lines": [{"medication_id": med["id"], "dosage": "1 cp", "frequency": "x3/j", "duration_days": 3}]})
    assert pr.status_code == 201, pr.text
    rows = doc.get("/api/sadm/to-sign").json()
    mine = next(r for r in rows if r["type"] == "prescription" and r["id"] == pr.json()["id"])
    assert mine["sign_url"] == f"/api/prescriptions/{mine['id']}/sign"
    signed = doc.post(mine["sign_url"] + "?force=true", json={})
    assert signed.status_code == 200 and all(r["id"] != mine["id"] or r["type"] != "prescription" for r in doc.get("/api/sadm/to-sign").json())
    assert login("nurse").get("/api/sadm/to-sign").json() == []
    monkeypatch.setenv("SADM_ENABLED", "0")
    assert client.get("/api/sadm/config").json()["enabled"] is False and client.get("/api/sadm/explain?kind=psych&ref=patient_02").status_code == 404

"""Étape 0 V2 — changements d'Amal (a4fa849) portés dans app/ : champs de risque comportemental et événement `behavioral_risk`."""
from .test_agents import open_risks, wait_for


def trigger(client, **body):
    r = client.post("/api/demo/trigger", json={"patient_id": "patient_03", **body})
    assert r.status_code == 200, r.text


def test_behavioral_risk_updates_risk_without_forcing_fall(client):
    client.post("/api/demo/reset")
    trigger(client, event_type="behavioral_risk", risk_level="high", risk_score=0.82, behavior_indicators=["agitation", "tentative de lever"], recommendations=["Passage infirmier"])
    p = client.get("/api/patients").json()["patient_03"]
    assert p["state"] == "normal" and not p["fall_detected"] and not p["pain_detected"]
    assert p["risk_level"] == "high" and p["risk_score"] == 0.82 and p["behavior_indicators"] == ["agitation", "tentative de lever"]
    ev = client.get("/api/events").json()[0]
    assert ev["event_type"] == "behavioral_risk" and ev["risk_level"] == "high" and ev["recommendations"] == ["Passage infirmier"]
    # propagation : room_state + VisionAgent → RiskAgent (sévérité déterministe)
    assert client.get("/api/rooms/states").json()["103"]["behavior"]["risk_level"] == "high"
    risks = wait_for(lambda: open_risks(client, "103", "behavioral_risk"))
    assert risks and risks[0]["severity"] == "high" and risks[0]["source_agent"] == "VisionAgent"
    # recover réinitialise les champs ; le risque, lui, attend un soignant (V2 : pas de levée automatique d'un risque clinique)
    trigger(client, event_type="recover")
    p = client.get("/api/patients").json()["patient_03"]
    assert p["risk_level"] == "none" and p["risk_score"] == 0.0 and p["behavior_indicators"] == [] and p["recommendations"] == []
    assert wait_for(lambda: [r for r in open_risks(client, "103", "behavioral_risk") if "à confirmer par un soignant" in r["notes"]])


def test_fall_and_pain_set_risk_fields(client):
    client.post("/api/demo/reset")
    trigger(client, event_type="pain")
    assert client.get("/api/patients").json()["patient_03"]["risk_level"] == "high"
    trigger(client, event_type="fall")
    p = client.get("/api/patients").json()["patient_03"]
    assert p["risk_level"] == "critical" and p["risk_score"] >= 0.95
    r = client.post("/api/yolo/event", json={"patient_id": "patient_03", "event_type": "recover"})
    assert r.status_code == 200 and client.get("/api/patients").json()["patient_03"]["risk_level"] == "none"


def test_floors_module_is_served_and_loaded(client):
    html = client.get("/").text
    assert "/static/js/floors.js" in html and 'id="sensor-rows"' in html and "Temperature unavailable" not in html
    js = client.get("/static/js/floors.js").text
    assert "HospitalFloors" in js and "INPUT|TEXTAREA|SELECT" in js

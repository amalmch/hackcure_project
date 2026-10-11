"""V2 étape 8 — prédiction des crises : scores déterministes, fenêtre de temps, glucomètre, alertes graduées, scénarios et résolutions."""
import time

from app.clinical.prediction import LABELS, RISK_TYPES, fmt_window, level, predict, slope_per_min, window_to

from .test_agents import msg, open_risks, wait_for


def by_key(preds):
    return {p["key"]: p for p in preds}


# ── règles ───────────────────────────────────────────────────────────────────
def test_trend_extrapolation_gives_a_window_with_uncertainty():
    t0 = 1000.0
    falling = [(t0 + i * 10, 130 - i * 1.0) for i in range(30)]           # −6 mmHg par minute
    assert abs(slope_per_min(falling) + 6.0) < 0.2
    w = window_to(101.0, 90.0, -6.0)                                        # ~1,8 min, ± 40 %
    assert w and w["min_minutes"] < 1.9 < w["max_minutes"] and "min" in w["text"]
    assert window_to(120.0, 90.0, 0.5) is None                              # la valeur s'éloigne du seuil
    assert slope_per_min([(t0, 1.0), (t0 + 5, 1.0)]) is None                # trop peu de points
    assert "h" in fmt_window(150, 400)["text"] and level(85) == "critique" and level(65) == "élevé" and level(10) == "faible"


def test_five_conditions_are_scored_with_factors():
    calm = by_key(predict({"vitals": {"hr": 74, "sys": 124, "rr": 16, "spo2": 98, "tempC": 36.8, "glucose": 0.95, "st": 0.0}, "news2": 0, "qsofa": 0, "history": "", "treatments": "", "labs": {}, "series": {}}))
    assert set(calm) == set(LABELS) == set(RISK_TYPES) and all(p["risk"] < 30 and p["window"] is None for p in calm.values())
    t0 = time.time()
    sys_series = [(t0 - 300 + i * 10, 118 - i * 0.8) for i in range(30)]
    sepsis = by_key(predict({"vitals": {"hr": 124, "sys": 95, "rr": 26, "tempC": 39.1}, "news2": 9, "qsofa": 2, "history": "", "treatments": "", "labs": {"LACT": {"value": 3.4}, "PCT": {"value": 5.0}},
                             "series": {"sys": sys_series, "hr": [(t, 100 + i) for i, (t, _) in enumerate(sys_series)]}}))["sepsis"]
    assert sepsis["level"] in ("élevé", "critique") and sepsis["window"] and any("qSOFA 2/3" in f for f in sepsis["factors"]) and any("lactates" in f for f in sepsis["factors"])
    cardiac = by_key(predict({"vitals": {"hr": 118, "sys": 92, "st": 2.6}, "history": "HTA, insuffisance cardiaque", "expression": "pain", "labs": {"TROPO": {"value": 180}}, "series": {}}))["cardiac"]
    assert cardiac["level"] == "critique" and "0–20 min" in cardiac["window"]["text"] and any("sus-décalage ST" in f for f in cardiac["factors"])
    hypo = by_key(predict({"vitals": {"glucose": 0.52}, "history": "diabète de type 2", "treatments": "Insuline", "labs": {}, "series": {}}))["diabetes"]
    assert hypo["level"] in ("élevé", "critique") and any("hypoglycémie" in f for f in hypo["factors"])
    seizure = by_key(predict({"vitals": {"tempC": 38.2}, "history": "épilepsie vasculaire sous lévétiracétam", "missed_antiepileptic": 2, "sleep_hours": 3.5, "series": {}}))["seizure"]
    assert seizure["level"] in ("élevé", "critique") and any("2 dose(s)" in f for f in seizure["factors"]) and seizure["window"]
    imminent = by_key(predict({"vitals": {}, "history": "épilepsie", "kp_variance": 0.6, "rhythmic_hz": 4.0, "series": {}}))["seizure"]
    assert imminent["risk"] >= 70 and "0–5 min" in imminent["window"]["text"]
    news = [(t0 - 300 + i * 10, 3 + i * 0.1) for i in range(30)]
    det = by_key(predict({"vitals": {}, "news2": 6, "history": "", "series": {"news2": news}}))["deterioration"]
    assert det["risk"] >= 60 and det["window"] and any("NEWS2 en hausse" in f for f in det["factors"])


# ── glucomètre et chaîne complète ────────────────────────────────────────────
def test_glucometer_in_every_room_and_in_vitals(client):
    devices = client.get("/api/devices").json()
    rows = devices if isinstance(devices, list) else devices.get("devices", [])
    assert {d.get("room") or d.get("room_code") for d in rows if d.get("type") == "glucometer"} >= {"101", "102", "103", "104"}
    client.post("/api/ingest", json=msg("hackcure/room/101/device/101-glucometer", type="glucometer", metrics={"glucose": 1.42}))
    assert wait_for(lambda: client.get("/api/rooms/states").json()["101"]["vitals"].get("glucose") == 1.42)
    client.post("/api/ingest", json=msg("hackcure/room/101/device/101-ecg", type="ecg", metrics={"hr": 80, "rhythm": "sinus", "rr": 16, "stMm": 0.3}))
    assert wait_for(lambda: client.get("/api/rooms/states").json()["101"]["vitals"].get("st") == 0.3)


def test_hypoglycemia_prediction_alerts_and_enters_the_caregiver_loop(client, login):
    client.post("/api/demo/reset")
    for value in (0.82, 0.74, 0.66, 0.58, 0.52, 0.5):
        client.post("/api/ingest", json=msg("hackcure/room/104/device/104-glucometer", type="glucometer", metrics={"glucose": value}))
    d = wait_for(lambda: (lambda x: x if next(p for p in x["predictions"] if p["key"] == "diabetes")["risk"] >= 60 else None)(client.get("/api/predictions/patient_04").json()), timeout=12)
    assert d, "prédiction « complication du diabète » élevée attendue"
    p = next(x for x in d["predictions"] if x["key"] == "diabetes")
    assert p["level"] in ("élevé", "critique") and p["window"] and p["confidence"] and any("hypoglycémie" in f for f in p["factors"]) and "non validée cliniquement" in d["disclaimer"]
    # alertes graduées + explication IA + risque dans la boucle soignant
    notifs = [n for n in client.get("/api/notifications").json()["items"] if "Prédiction — Complication du diabète" in n["title"] and n["room"] == "104"]
    assert notifs and "crise estimée dans" in notifs[0]["body"] and any(n["target_role"] == "nurse" for n in notifs)
    risks = wait_for(lambda: open_risks(client, "104", "predicted_glycemia"), timeout=8)
    assert risks and risks[0]["severity"] in ("high", "critical") and risks[0]["source_agent"] == "PredictionAgent"
    ai = wait_for(lambda: next((x for x in client.get("/api/predictions/patient_04").json()["history"]["diabetes"] if x), None) and
                  next((x for x in client.get("/api/predictions").json()["patients"] if x["patient_id"] == "patient_04"), None), timeout=8)
    assert ai and ai["max_risk"] >= 60
    assert login("receptionist").get("/api/predictions").status_code == 403 and login("nurse").get("/api/predictions").status_code == 200
    # résolution : resucrage ⇒ la revérification s'appuie sur la prédiction recalculée
    from app import resolutions
    from app.agents.followup import verify_risk

    resolutions._catalog = None
    assert resolutions.plan_for("predicted_glycemia")["scenario"] == "hypoglycemia_resolves" and resolutions.plan_for("predicted_cardiac")["role"] == "duty_doctor"
    assert verify_risk("predicted_glycemia", {"room": "104"})[0] is False
    for _ in range(3):
        client.post("/api/ingest", json=msg("hackcure/room/104/device/104-glucometer", type="glucometer", metrics={"glucose": 1.05}))
    assert wait_for(lambda: verify_risk("predicted_glycemia", {"room": "104"})[0], timeout=8)


def test_prediction_scenarios_and_resolutions_exist():
    from simulator.engine import Scenario

    names = {s["name"]: s for s in Scenario.available()}
    for sc in ("cardiac_event_102", "hypoglycemia_104", "seizure_103", "deterioration_101", "sepsis_trend"):
        assert sc in names
    covered = {t for s in names.values() for t in s.get("resolves") or []}
    assert set(RISK_TYPES.values()) <= covered

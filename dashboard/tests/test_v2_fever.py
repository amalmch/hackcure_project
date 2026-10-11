"""
V2 étape 3 — fièvre vraie ≠ simple hausse thermique.

Fièvre vraie (température centrale) ⇒ médecin de garde + bilan clinique + bilan biologique validé, PUIS confort.
Simple hausse thermique (peau / chambre chaude, température centrale normale) ⇒ EnvironmentAgent seul, sans risque.
"""
import time

from app.clinical.fever import assess, qsofa
from app.clinical.labs import propose_fever_workup, simulate

from .test_agents import msg, open_risks, wait_for


# ── règles déterministes ─────────────────────────────────────────────────────
def test_core_temperature_defines_fever():
    n = time.time()
    assert assess([(n - 3, 38.2), (n - 2, 38.3), (n - 1, 38.4)], n)["kind"] == "fever"          # ≥ 38,0 °C confirmée
    assert assess([(n - 1, 38.4)], n)["kind"] == "none"                                           # une seule lecture : pas encore
    assert assess([(n - 700, 37.9), (n - 1, 37.85)], n)["kind"] == "fever"                        # ≥ 37,8 °C à deux reprises en 1 h
    assert assess([(n - 30, 37.9), (n - 1, 37.9)], n)["kind"] == "none"                           # deux relevés trop rapprochés
    assert assess([(n - 4000, 37.9), (n - 1, 37.9)], n)["kind"] == "none"                         # premier relevé hors de l'heure


def test_skin_or_room_temperature_alone_is_never_a_fever():
    n = time.time()
    a = assess([(n - 2, 36.8), (n - 1, 36.9)], n, skin_temp=38.9, env_temp=29.0)
    assert a["kind"] == "thermal_rise" and "température centrale normale" in a["criterion"]
    assert assess([], n, skin_temp=39.5)["kind"] == "thermal_rise"                                # pas de thermomètre : jamais « fièvre »
    assert assess([(n - 1, 36.9)], n, skin_temp=36.5, env_temp=22.0)["kind"] == "none"


def test_qsofa_and_workup_rules():
    assert qsofa(24, 96)["score"] == 2 and qsofa(24, 96)["positive"]
    assert qsofa(18, 120)["score"] == 0
    labs = propose_fever_workup({"age": 72, "history": "Diabète de type 2, HTA"}, "Metformine 850 mg", {"sys": 96, "hr": 112}, 1, has_iv=True)
    codes = [x["code"] for x in labs]
    assert {"LEUCO", "CRP", "PCT", "HEMOC", "ECBU", "LACT", "GLY", "CREAT"} <= set(codes) and len(codes) == len(set(codes))
    assert all(x["motif"] for x in labs)
    res = {r["code"]: r for r in simulate(codes, "infection", seed=3)}
    assert res["CRP"]["abnormal"] and res["LEUCO"]["abnormal"] and res["HEMOC"]["value"] is None
    assert simulate(codes, "infection", seed=3) == simulate(codes, "infection", seed=3)          # déterministe


# ── parcours fièvre ──────────────────────────────────────────────────────────
def thermo(room, value):
    return msg(f"hackcure/room/{room}/device/{room}-thermometer", type="thermometer", metrics={"tempC": value})


def env(room, temp, outdoor=18.0):
    return msg(f"hackcure/room/{room}/env", tempC=temp, humidity=45, motion=False, doorOpen=False, outdoorC=outdoor)


def test_true_fever_pathway_clinical_then_labs_then_comfort(client, login):
    client.post("/api/demo/reset")
    for eq, action in (("window", "close"), ("ac", "off")):
        client.post("/api/commands", json={"room": "101", "equipment": eq, "action": action, "reason": "préparation du test"})
    client.post("/api/demo/reset")  # efface la « main » manuelle sur la chambre
    for _ in range(3):
        client.post("/api/ingest", json=thermo("101", 39.2))
    risks = wait_for(lambda: open_risks(client, "101", "fever"))
    assert risks and risks[0]["source_agent"] == "FeverAgent" and risks[0]["severity"] == "high"
    rid = risks[0]["id"]

    # 1) parcours ouvert : médecin de garde demandé, checklist, bilan proposé et justifié
    p = wait_for(lambda: (lambda rows: rows[0] if rows and rows[0]["ai"].get("bilan") else None)(client.get(f"/api/fever?risk_id={rid}").json()))
    assert p and p["stage"] == "clinical_exam" and "38.0" in p["criterion"]
    assert len(p["checklist"]) == 7 and "qSOFA" in next(c for c in p["checklist"] if c["key"] == "sepsis")["note"]
    codes = {x["code"] for x in p["labs"] if x["selected"]}
    assert {"CRP", "PCT", "HEMOC", "LEUCO"} <= codes and all(x.get("justification") for x in p["labs"] if x["selected"])
    assert "validation médicale requise" in p["disclaimer"]
    notifs = [n for n in client.get("/api/notifications").json()["items"] if n["risk_id"] == rid and n["target_role"] == "duty_doctor"]
    assert any("Médecin de garde demandé" in n["title"] for n in notifs)

    # la chambre est chaude, mais le confort attend le bilan : l'EnvironmentAgent ne touche à rien
    for _ in range(2):
        client.post("/api/ingest", json=env("101", 28.6))
    time.sleep(1.0)
    eq = client.get("/api/rooms/states").json()["101"]["equipment"]
    assert eq["ac"] == "off" and eq["window"] == "closed"

    # le bilan biologique ne peut pas être validé avant le bilan clinique ; l'infirmier coche, le médecin conclut
    doctor, nurse = login("duty_doctor"), login("nurse")
    assert doctor.post(f"/api/fever/{p['id']}/labs/validate", json={}).status_code == 409
    assert nurse.post(f"/api/fever/{p['id']}/checklist", json={"key": "hydratation", "done": True, "note": "muqueuses sèches"}).status_code == 200
    assert nurse.post(f"/api/fever/{p['id']}/exam-done").status_code == 403
    assert nurse.post(f"/api/fever/{p['id']}/labs/validate", json={}).status_code == 403
    d = doctor.post(f"/api/fever/{p['id']}/exam-done").json()
    assert d["stage"] == "lab_proposed" and d["exam_done_by"] == "medecin_garde"

    # 2) le médecin valide (en retirant un examen) ; 3) ensuite seulement : confort
    keep = sorted(codes - {"ECBU"})
    d = doctor.post(f"/api/fever/{p['id']}/labs/validate", json={"codes": keep}).json()
    assert d["stage"] == "lab_ordered" and {x["code"] for x in d["labs"] if x["selected"]} == set(keep)
    assert "confort" in d["comfort_note"].lower() and "pas un traitement" in d["comfort_note"]
    eq = client.get("/api/rooms/states").json()["101"]["equipment"]
    assert eq["ac"] == "on" or eq["window"] == "open"

    # résultats simulés : versés au dossier médical, interprétés
    d = wait_for(lambda: (lambda x: x if x["stage"] == "lab_results" and x["ai"].get("resultats") else None)(client.get(f"/api/fever/{p['id']}").json()), timeout=10)
    assert d and d["record_entry_id"] and {r["code"] for r in d["results"]} == set(keep)
    assert any(r["code"] == "CRP" and r["abnormal"] for r in d["results"])

    # le réglage de la chambre n'a résolu aucun risque clinique
    assert client.get(f"/api/risks/{rid}").json()["status"] in ("open", "escalated")  # jamais « resolved » sans soignant
    logs = client.get("/api/agents/logs?room=101&limit=80").json()
    assert any(l["agent"] == "FeverAgent" and "FIÈVRE VRAIE" in l["reasoning"] for l in logs)
    assert any(l["agent"] == "EnvironmentAgent" and "ne traite pas la fièvre" in l["reasoning"] for l in logs)


def test_skin_temperature_alone_creates_no_fever_risk(client):
    client.post("/api/demo/reset")
    before = len(open_risks(client, "104", "fever"))
    client.post("/api/ingest", json=msg("hackcure/room/104/thermal", skinTempC=38.9, maxTempC=39.2, calibrated=True))
    for _ in range(4):
        client.post("/api/ingest", json=thermo("104", 36.9))
    logs = wait_for(lambda: [l for l in client.get("/api/agents/logs?room=104&limit=30").json() if l["agent"] == "FeverAgent" and "SIMPLE HAUSSE THERMIQUE" in l["reasoning"]])
    assert logs and "Ni médecin ni bilan" in logs[0]["reasoning"]
    time.sleep(0.6)
    assert len(open_risks(client, "104", "fever")) == before
    assert not client.get("/api/fever?room=104&open_only=1").json()


def test_room_overheat_is_handled_by_environment_agent_alone(client):
    client.post("/api/demo/reset")
    for eq, action in (("window", "close"), ("ac", "off"), ("heater", "off")):
        client.post("/api/commands", json={"room": "102", "equipment": eq, "action": action, "reason": "préparation du test"})
    client.post("/api/demo/reset")
    before = len(open_risks(client, "102", "fever"))
    for _ in range(2):
        client.post("/api/ingest", json=env("102", 29.4, outdoor=17.0))
    for _ in range(3):
        client.post("/api/ingest", json=thermo("102", 36.8))
    # l'EnvironmentAgent agit directement : air extérieur nettement plus frais, patient non fragile ⇒ fenêtre
    eq = wait_for(lambda: (lambda e: e if e["window"] == "open" or e["ac"] == "on" else None)(client.get("/api/rooms/states").json()["102"]["equipment"]))
    assert eq and eq["window"] == "open"
    logs = client.get("/api/agents/logs?room=102&limit=40").json()
    assert any(l["agent"] == "EnvironmentAgent" and "simple hausse thermique" in l["input"] and "sans médecin ni bilan" in l["reasoning"] for l in logs)
    # revérification quelques minutes plus tard (délai raccourci en test)
    client.post("/api/ingest", json=env("102", 24.6, outdoor=17.0))
    assert wait_for(lambda: [l for l in client.get("/api/agents/logs?room=102&limit=40").json() if l["agent"] == "EnvironmentAgent" and "revérification après hausse thermique" in l["input"]], timeout=10)
    assert len(open_risks(client, "102", "fever")) == before and not client.get("/api/fever?room=102&open_only=1").json()
    client.post("/api/commands", json={"room": "102", "equipment": "window", "action": "close", "reason": "fin du test"})


def test_scenarios_fever_and_overheat_exist():
    from simulator.engine import Scenario

    names = {s["name"]: s for s in Scenario.available()}
    assert "FIEVRE VRAIE" in names["fever_101"]["description"] and "SIMPLE HAUSSE THERMIQUE" in names["room_overheat_102"]["description"]

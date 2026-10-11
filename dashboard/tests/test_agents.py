"""
Agents : VisionAgent → RiskAgent (critical + plan + notification) → FollowUpAgent (visite, re-vérification,
résolution vérifiée / escalade), VitalsAgent (seuils, levée auto), EnvironmentAgent (commandes), permissions.
"""
import time

TS = "2026-10-10T22:00:00+00:00"


def msg(topic, **payload):
    return {"topic": topic, "payload": {"ts": TS, "source": "sim", **payload}}


def vision(room, posture, activity, zone="bed", persons=1):
    return msg(f"hackcure/room/{room}/vision/state", persons=persons, patientTrackId=1, posture=posture, activity=activity, zone=zone, confidence=0.9)


def wait_for(fn, timeout=6.0, interval=0.15):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    return last


def open_risks(client, room, rtype=None):
    rows = client.get(f"/api/risks?room={room}&open_only=1").json()
    return [r for r in rows if rtype is None or r["type"] == rtype]


def test_fall_creates_critical_risk_with_plan_and_notification(client):
    client.post("/api/demo/reset")
    client.post("/api/ingest", json=vision("102", "lying_bed", "awake_bed"))
    client.post("/api/ingest", json=vision("102", "on_floor", "fall", "floor"))
    risks = wait_for(lambda: open_risks(client, "102", "fall"))
    assert risks, "le RiskAgent doit créer un risque chute"
    r = risks[0]
    assert r["severity"] == "critical" and r["status"] == "open" and r["source_agent"] == "VisionAgent"
    assert r["patient_id"] == "patient_02"
    # plan enrichi (mock) : 3 à 6 étapes
    full = wait_for(lambda: (lambda d: d if d.get("plan") and d["plan"]["steps"] else None)(client.get(f"/api/risks/{r['id']}").json()))
    assert full and 3 <= len(full["plan"]["steps"]) <= 6
    assert "allergies" in full["explanation"].lower() or "pénicilline" in full["explanation"].lower()
    # notifications : infirmier + médecin de garde (critical)
    notifs = client.get("/api/notifications").json()["items"]
    mine = [n for n in notifs if n["risk_id"] == r["id"]]
    assert {n["target_role"] for n in mine} >= {"nurse", "duty_doctor"}
    assert client.get("/api/notifications").json()["unread"] >= 2
    # déduplication : second signal de chute → toujours un seul risque ouvert
    client.post("/api/ingest", json=vision("102", "on_floor", "fall", "floor"))
    time.sleep(0.6)
    assert len(open_risks(client, "102", "fall")) == 1
    # journal des agents
    logs = client.get("/api/agents/logs?room=102&limit=50").json()
    assert {l["agent"] for l in logs} >= {"VisionAgent", "RiskAgent"}
    assert any(l["risk_id"] == r["id"] for l in logs)
    # niveau de risque de la chambre dans room_state
    assert client.get("/api/rooms/states").json()["102"]["riskLevel"] == "critical"


def test_nurse_visit_then_followup_resolves(client):
    risks = open_risks(client, "102", "fall")
    assert risks
    rid = risks[0]["id"]
    # l'infirmier entre : in_progress + StaffVisit
    client.post("/api/ingest", json=msg("hackcure/room/102/vision/staff", event="staff_enter", persons=2))
    r = wait_for(lambda: (lambda d: d if d["status"] == "in_progress" else None)(client.get(f"/api/risks/{rid}").json()))
    assert r and r["acknowledged_at"]
    visits = client.get("/api/staff/visits?room=102").json()
    assert visits and visits[0]["risk_id"] == rid and visits[0]["ended_at"] is None
    # il coche une étape du plan
    step = r["plan"]["steps"][0]
    d = client.patch(f"/api/risks/{rid}/steps/{step['id']}", json={"done": True}).json()
    assert d["plan"]["steps"][0]["done"] and d["plan"]["steps"][0]["done_by"] == "owner"
    # le patient est réinstallé, l'infirmier sort
    client.post("/api/ingest", json=vision("102", "lying_bed", "awake_bed", persons=2))
    client.post("/api/ingest", json=msg("hackcure/room/102/vision/staff", event="staff_leave", persons=1, durationSec=40))
    # re-vérification après FOLLOWUP_RECHECK_S (0.3 s en test) → résolu + vérifié
    r = wait_for(lambda: (lambda d: d if d["status"] == "resolved" else None)(client.get(f"/api/risks/{rid}").json()), timeout=8)
    assert r and r["verified_at"] and "FollowUpAgent" in r["resolved_by"]
    assert client.get("/api/staff/visits?room=102").json()[0]["ended_at"] is not None
    assert client.get("/api/rooms/states").json()["102"]["riskLevel"] == "none"


def test_persistent_risk_is_escalated_after_visit(client):
    client.post("/api/ingest", json=vision("103", "lying_bed", "awake_bed"))
    client.post("/api/ingest", json=vision("103", "on_floor", "fall", "floor"))
    risks = wait_for(lambda: open_risks(client, "103", "fall"))
    rid = risks[0]["id"]
    client.post("/api/ingest", json=msg("hackcure/room/103/vision/staff", event="staff_enter", persons=2))
    wait_for(lambda: client.get(f"/api/risks/{rid}").json()["status"] == "in_progress")
    # le personnel sort mais le patient est toujours au sol
    client.post("/api/ingest", json=msg("hackcure/room/103/vision/staff", event="staff_leave", persons=1, durationSec=10))
    r = wait_for(lambda: (lambda d: d if d["status"] == "escalated" else None)(client.get(f"/api/risks/{rid}").json()), timeout=8)
    assert r and r["escalated_at"] and "persistant" in r["notes"]
    notifs = client.get("/api/notifications").json()["items"]
    assert any(n["risk_id"] == rid and n["target_role"] == "duty_doctor" and "persistant" in n["title"].lower() for n in notifs)
    # nettoyage : le patient est relevé
    client.post("/api/ingest", json=vision("103", "lying_bed", "awake_bed"))
    client.patch(f"/api/risks/{rid}", json={"status": "resolved", "notes": "test"})


def test_escalation_without_any_visit(client):
    client.post("/api/ingest", json=vision("104", "lying_bed", "awake_bed"))
    client.post("/api/ingest", json=vision("104", "on_floor", "fall", "floor"))
    risks = wait_for(lambda: open_risks(client, "104", "fall"))
    rid = risks[0]["id"]
    # ESCALATION_CRITICAL_S = 2 s en test
    r = wait_for(lambda: (lambda d: d if d["status"] == "escalated" else None)(client.get(f"/api/risks/{rid}").json()), timeout=8)
    assert r and "aucune visite" in r["notes"]
    client.post("/api/ingest", json=vision("104", "lying_bed", "awake_bed"))
    client.patch(f"/api/risks/{rid}", json={"status": "resolved"})


def test_manual_resolve_request_is_verified(client):
    client.post("/api/ingest", json=msg("hackcure/room/101/vision/expression", expression="neutral", confidence=0.8))
    client.post("/api/ingest", json=msg("hackcure/room/101/vision/expression", expression="pain", confidence=0.8))
    risks = wait_for(lambda: open_risks(client, "101", "pain"))
    rid = risks[0]["id"]
    assert risks[0]["severity"] == "high"
    client.post("/api/ingest", json=msg("hackcure/room/101/vision/expression", expression="neutral", confidence=0.8))
    time.sleep(0.3)
    cur = client.get(f"/api/risks/{rid}").json()
    if cur["status"] != "resolved":  # sinon levée automatique déjà faite par le RiskAgent
        r = client.post(f"/api/risks/{rid}/resolve").json()
        assert r["status"] == "in_progress"
        cur = wait_for(lambda: (lambda d: d if d["status"] == "resolved" else None)(client.get(f"/api/risks/{rid}").json()), timeout=8)
    assert cur["status"] == "resolved"


def test_vitals_thresholds_and_auto_clear(client):
    for _ in range(3):  # anti-bruit : 3 lectures consécutives hors limites
        client.post("/api/ingest", json=msg("hackcure/room/101/device/101-ecg", type="ecg", metrics={"hr": 138, "rhythm": "tachy"}))
    risks = wait_for(lambda: open_risks(client, "101", "tachycardia"))
    assert risks and risks[0]["severity"] == "high" and risks[0]["source_agent"] == "VitalsAgent"
    rid = risks[0]["id"]
    client.post("/api/ingest", json=msg("hackcure/room/101/device/101-ecg", type="ecg", metrics={"hr": 76, "rhythm": "sinus"}))
    # V2 : un risque clinique ne se lève plus seul — la normalisation est notée, le risque attend un soignant
    r = wait_for(lambda: (lambda d: d if "à confirmer par un soignant" in d["notes"] else None)(client.get(f"/api/risks/{rid}").json()))
    assert r and r["status"] == "open"
    # équipement : perfusion presque vide → medium
    for _ in range(3):
        client.post("/api/ingest", json=msg("hackcure/room/103/device/103-iv_pump", type="iv_pump", metrics={"rateMlH": 80, "volumeLeftMl": 30, "occlusion": False}))
    risks = wait_for(lambda: open_risks(client, "103", "iv_empty"))
    assert risks and risks[0]["severity"] == "medium"
    client.post("/api/ingest", json=msg("hackcure/room/103/device/103-iv_pump", type="iv_pump", metrics={"rateMlH": 80, "volumeLeftMl": 480, "occlusion": False}))
    assert wait_for(lambda: [r for r in open_risks(client, "103", "iv_empty") if "à confirmer" in r["notes"]])


def test_environment_agent_sends_commands(client):
    # 29 °C dehors : aérer ne suffirait pas ⇒ climatisation (V2 : fenêtre seulement si l'air extérieur est nettement plus frais)
    client.post("/api/ingest", json=msg("hackcure/room/104/env", tempC=29.5, humidity=50, motion=False, doorOpen=False, outdoorC=29.0))
    rs = wait_for(lambda: (lambda d: d if d["equipment"]["ac"] == "on" else None)(client.get("/api/rooms/states").json()["104"]))
    assert rs, "la clim doit être allumée au-dessus de 27 °C"
    logs = client.get("/api/agents/logs?agent=EnvironmentAgent&room=104").json()
    assert any("clim" in l["reasoning"].lower() for l in logs)  # le journal contient aussi la note de confort rédigée par le LLM
    eq = client.get("/api/commands/equipment").json()["104"]
    assert eq["ac"]["state"] == "on" and eq["ac"]["last_command_by"] == "EnvironmentAgent"


def test_manual_command_and_permissions(client, login):
    r = client.post("/api/commands", json={"room": "101", "equipment": "window", "action": "open", "reason": "aération"})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["ack"]["state"] == "open"
    assert client.get("/api/rooms/states").json()["101"]["equipment"]["window"] == "open"
    assert client.post("/api/commands", json={"room": "101", "equipment": "laser", "action": "on"}).status_code == 400
    assert login("pharmacist").post("/api/commands", json={"room": "101", "equipment": "light", "action": "on"}).status_code == 403
    assert login("receptionist").post("/api/commands", json={"room": "101", "equipment": "light", "action": "on"}).status_code == 403
    assert login("nurse").post("/api/commands", json={"room": "101", "equipment": "light", "action": "on"}).status_code == 200


def test_risk_permissions(client, login):
    rid = client.get("/api/risks?limit=1").json()[0]["id"]
    assert login("pharmacist").get("/api/risks").status_code == 403
    assert login("receptionist").get("/api/risks").status_code == 200
    assert login("receptionist").patch(f"/api/risks/{rid}", json={"notes": "x"}).status_code == 403
    assert login("nurse").patch(f"/api/risks/{rid}", json={"notes": "vu"}).status_code == 200
    assert login("nurse").post(f"/api/risks/{rid}/steps", json={"text": "Étape manuelle"}).status_code == 201
    assert client.get("/api/agents").json()["llm_provider"] == "mock"
    assert client.get("/api/risks/summary").status_code == 200
    assert login("pharmacist").get("/api/staff").status_code == 403
    assert client.get("/api/staff").json()["on_duty"] >= 1

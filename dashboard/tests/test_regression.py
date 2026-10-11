"""
Non-régression du dashboard d'origine : `/`, `/api/patients`, `/ws` (init), `/api/demo/trigger`,
`/api/demo/reset`, `/api/mode`, `/api/yolo/event`.
"""
import json


LEGACY_KEYS = {
    "patient_id", "name", "age", "room", "room_position", "state", "fall_detected",
    "pain_detected", "confidence", "last_event_time", "alert_priority", "source",
}


def test_root_serves_dashboard(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "three-container" in r.text
    assert "/static/js/scene.js" in r.text


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_static_js_served(client):
    for name in ("patient-state.js", "scene.js", "avatars.js", "dashboard-ui.js", "demo-controller.js", "app.js"):
        assert client.get(f"/static/js/{name}").status_code == 200, name


def test_api_patients_legacy_shape(client):
    client.post("/api/demo/reset")
    r = client.get("/api/patients")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) >= {"patient_01", "patient_02", "patient_03", "patient_04"}
    p = data["patient_01"]
    assert LEGACY_KEYS <= set(p.keys())
    assert p["room"] == "101" and p["name"] == "Patient A" and p["age"] == 72
    assert data["patient_03"]["age"] == 81


def test_ws_init_then_demo_event(client):
    client.post("/api/mode", json={"mode": "demo"})
    with client.websocket_connect("/ws") as ws:
        init = json.loads(ws.receive_text())
        assert init["type"] == "init"
        assert init["mode"] in ("demo", "real")
        assert "patient_01" in init["patients"]
        assert isinstance(init["event_history"], list)

        ws.send_text(json.dumps({"type": "ping"}))
        reply = json.loads(ws.receive_text())
        for _ in range(50):  # les agents V2 diffusent en continu (diagnostics, psychologie…) : on saute leurs messages
            if reply["type"] == "pong":
                break
            reply = json.loads(ws.receive_text())
        assert reply["type"] == "pong"

        r = client.post("/api/demo/trigger", json={"patient_id": "patient_02", "event_type": "fall", "confidence": 0.93})
        assert r.status_code == 200 and r.json()["status"] == "ok"

        msg = json.loads(ws.receive_text())
        while msg["type"] != "patient_event":
            msg = json.loads(ws.receive_text())
        assert msg["patient_id"] == "patient_02"
        assert msg["event_type"] == "fall"
        assert msg["state"] == "fall_detected"
        assert msg["fall_detected"] is True and msg["pain_detected"] is False
        assert msg["alert_priority"] == "critical"
        assert msg["source"] == "simulation"

    p = client.get("/api/patients").json()["patient_02"]
    assert p["state"] == "fall_detected" and p["confidence"] == 0.93

    events = client.get("/api/events").json()
    assert events and events[0]["patient_id"] == "patient_02"


def test_event_types_and_priorities(client):
    cases = {
        "pain": ("pain_detected", "high", False, True),
        "fall_and_pain": ("fall_and_pain", "critical", True, True),
        "recover": ("normal", "none", False, False),
    }
    for ev, (state, prio, fall, pain) in cases.items():
        client.post("/api/demo/trigger", json={"patient_id": "patient_01", "event_type": ev})
        p = client.get("/api/patients").json()["patient_01"]
        assert (p["state"], p["alert_priority"], p["fall_detected"], p["pain_detected"]) == (state, prio, fall, pain), ev


def test_unknown_event_is_ignored(client):
    before = client.get("/api/patients").json()["patient_04"]["state"]
    r = client.post("/api/demo/trigger", json={"patient_id": "patient_04", "event_type": "levitate"})
    assert r.status_code == 200
    assert client.get("/api/patients").json()["patient_04"]["state"] == before


def test_reset_clears_everything(client):
    client.post("/api/demo/trigger", json={"patient_id": "patient_03", "event_type": "fall"})
    with client.websocket_connect("/ws") as ws:
        ws.receive_text()  # init
        r = client.post("/api/demo/reset")
        assert r.json()["status"] == "reset"
        types = []
        for _ in range(60):  # les agents V2 diffusent d'autres messages (prédictions, diagnostics…) entre-temps
            types.append(json.loads(ws.receive_text())["type"])
            if "reset" in types:
                break
        assert "reset" in types
    assert all(p["state"] == "normal" for p in client.get("/api/patients").json().values())
    assert client.get("/api/events").json() == []


def test_mode_switch_blocks_demo_triggers(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_text()
        r = client.post("/api/mode", json={"mode": "real"})
        assert r.json()["mode"] == "real"
        msg = json.loads(ws.receive_text())
        assert msg == {"type": "mode_change", "mode": "real"}

    r = client.post("/api/demo/trigger", json={"patient_id": "patient_01", "event_type": "fall"})
    assert r.status_code == 400

    # Les événements YOLO passent toujours (scénario A)
    r = client.post("/api/yolo/event", json={"patient_id": "patient_01", "event_type": "fall", "confidence": 0.77})
    assert r.status_code == 200
    p = client.get("/api/patients").json()["patient_01"]
    assert p["source"] == "yolo" and p["state"] == "fall_detected"

    assert client.post("/api/mode", json={"mode": "weird"}).status_code == 400
    client.post("/api/mode", json={"mode": "demo"})
    client.post("/api/demo/reset")

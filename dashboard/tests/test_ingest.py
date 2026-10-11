"""Ingestion HTTP (repli MQTT) → room_state, projection 3D, appareils, chambres."""
import json
import time

TS = "2026-10-10T22:00:00+00:00"


def msg(topic, **payload):
    return {"topic": topic, "payload": {"ts": TS, "source": "sim", **payload}}


def test_ingest_rejects_invalid(anon_client):
    r = anon_client.post("/api/ingest", json=msg("hackcure/room/101/thermal", skinTempC=36.5))
    assert r.status_code == 422
    r = anon_client.post("/api/ingest", json={"topic": "foo/bar", "payload": {}})
    assert r.status_code == 422
    r = anon_client.post("/api/ingest", json={})
    assert r.status_code == 422


def test_ingest_single_and_batch_update_room_state(client):
    r = client.post("/api/ingest", json=msg("hackcure/room/102/env", tempC=28.4, humidity=51, motion=True, doorOpen=False))
    assert r.status_code == 202 and r.json()["accepted"] == 1
    batch = {"messages": [
        msg("hackcure/room/102/thermal", skinTempC=37.4, maxTempC=37.9, calibrated=True),
        msg("hackcure/room/102/device/102-ecg", type="ecg", status="running", metrics={"hr": 91, "rhythm": "afib"}),
        msg("hackcure/room/102/device/102-spo2", type="spo2", metrics={"spo2": 95}),
        msg("hackcure/room/102/device/102-bp", type="bp", metrics={"sys": 108, "dia": 66, "map": 80}),
        {"topic": "hackcure/room/102/env", "payload": {"ts": TS, "source": "sim", "tempC": 999, "humidity": 50}},  # invalide
    ]}
    r = client.post("/api/ingest", json=batch)
    assert r.status_code == 202
    assert r.json()["accepted"] == 4 and len(r.json()["rejected"]) == 1
    rs = client.get("/api/rooms/states").json()["102"]
    assert rs["env"]["tempC"] == 28.4 and rs["skinTempC"] == 37.4 and rs["thermalCalibrated"] is True
    assert rs["vitals"]["hr"] == 91 and rs["vitals"]["spo2"] == 95 and rs["vitals"]["sys"] == 108
    assert rs["devices"]["102-ecg"]["metrics"]["rhythm"] == "afib"


def test_vision_fall_projects_to_legacy_patient_event(client):
    client.post("/api/demo/reset")
    with client.websocket_connect("/ws") as ws:
        init = json.loads(ws.receive_text())
        assert "room_states" in init
        # état normal d'abord (pas d'événement legacy émis au premier message « normal »)
        client.post("/api/ingest", json=msg("hackcure/room/103/vision/state", persons=1, patientTrackId=1, posture="lying_bed", activity="awake_bed", zone="bed", confidence=0.9))
        client.post("/api/ingest", json=msg("hackcure/room/103/vision/state", persons=1, patientTrackId=1, posture="on_floor", activity="fall", zone="floor", confidence=0.93, cvClass="patient_fallen"))
        got = {}
        for _ in range(60):  # d'autres diffusions (agents, risques, notifications) s'intercalent
            m = json.loads(ws.receive_text())
            got.setdefault(m["type"], []).append(m)
            if "patient_event" in got and any(x["room"] == "103" and x["posture"] == "on_floor" for x in got.get("room_state", [])):
                break
        ev = got["patient_event"][-1]
        assert ev["patient_id"] == "patient_03" and ev["event_type"] == "fall" and ev["source"] == "simulation"
        rs = [m for m in got["room_state"] if m["room"] == "103"][-1]
        assert rs["posture"] == "on_floor" and rs["activity"] == "fall" and rs["patient_id"] == "patient_03"

    assert client.get("/api/patients").json()["patient_03"]["state"] == "fall_detected"

    # expression douleur → fall_and_pain ; récupération → recover
    client.post("/api/ingest", json=msg("hackcure/room/103/vision/expression", expression="pain", confidence=0.8))
    assert client.get("/api/patients").json()["patient_03"]["state"] == "fall_and_pain"
    client.post("/api/ingest", json=msg("hackcure/room/103/vision/expression", expression="neutral", confidence=0.8))
    client.post("/api/ingest", json=msg("hackcure/room/103/vision/state", persons=1, patientTrackId=1, posture="lying_bed", activity="awake_bed", zone="bed", confidence=0.9))
    assert client.get("/api/patients").json()["patient_03"]["state"] == "normal"


def test_real_edge_source_marks_yolo(client):
    client.post("/api/demo/reset")
    client.post("/api/ingest", json={"topic": "hackcure/room/101/vision/state", "payload": {"ts": TS, "source": "edge-yolo", "persons": 1, "posture": "lying_bed", "activity": "awake_bed", "zone": "bed", "confidence": 0.9}})
    client.post("/api/ingest", json={"topic": "hackcure/room/101/vision/state", "payload": {"ts": TS, "source": "edge-yolo", "persons": 1, "posture": "on_floor", "activity": "fall", "zone": "floor", "confidence": 0.9}})
    p = client.get("/api/patients").json()["patient_01"]
    assert p["state"] == "fall_detected" and p["source"] == "yolo"
    assert client.get("/api/ingest/stats").json()["edge_seen"]["101"] is True
    client.post("/api/ingest", json={"topic": "hackcure/room/101/vision/state", "payload": {"ts": TS, "source": "edge-yolo", "persons": 1, "posture": "lying_bed", "activity": "awake_bed", "zone": "bed", "confidence": 0.9}})


def test_staff_and_cmd_ack(client):
    client.post("/api/ingest", json=msg("hackcure/room/104/vision/staff", event="staff_enter", persons=2))
    assert client.get("/api/rooms/states").json()["104"]["staffPresent"] is True
    client.post("/api/ingest", json=msg("hackcure/room/104/vision/staff", event="staff_leave", persons=1, durationSec=42))
    assert client.get("/api/rooms/states").json()["104"]["staffPresent"] is False
    client.post("/api/ingest", json=msg("hackcure/room/104/cmd/ack", equipment="window", action="open", ok=True, state="open"))
    room = client.get("/api/rooms/104").json()
    assert room["equipment"]["window"] == "open"
    assert room["patient"]["patient_id"] == "patient_04"


def test_devices_endpoints(client, login):
    devices = client.get("/api/devices").json()
    assert len(devices) == 36  # 9 types × 4 chambres (V2 : glucomètre)
    for _ in range(3):
        client.post("/api/ingest", json=msg("hackcure/room/101/device/101-ecg", type="ecg", metrics={"hr": 77, "rhythm": "sinus"}))
    d = [x for x in client.get("/api/devices?room=101").json() if x["type"] == "ecg"][0]
    assert d["live"] and d["metrics"]["hr"] == 77
    h = client.get("/api/devices/101-ecg/history?metric=hr&minutes=5").json()
    assert h["unit"] == "bpm" and len(h["points"]) >= 3
    assert client.get("/api/devices/nope/history?metric=hr").status_code == 404
    # le pharmacien n'a pas accès aux machines
    assert login("pharmacist").get("/api/devices").status_code == 403


def test_scenarios_api_without_embedded_sim(client):
    r = client.get("/api/demo/scenarios")
    assert r.status_code == 200
    names = {s["name"] for s in r.json()["scenarios"]}
    assert "fall_demo" in names and "nurse_resolves" in names
    assert r.json()["embedded"] is False
    assert client.post("/api/demo/scenario", json={"name": "fall_demo"}).status_code == 503

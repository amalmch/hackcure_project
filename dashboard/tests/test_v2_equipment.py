"""
Pannes d'équipement (`machine_error`, Amal 384ae87) reliées à nos appareils médicaux :
événement legacy et flux d'appareil donnent le même risque « equipment_fault », sans doublon avec la perfusion.
"""
from .test_agents import msg, open_risks, wait_for


def device(room, dtype, metrics, **extra):
    return msg(f"hackcure/room/{room}/device/{room}-{dtype}", type=dtype, metrics=metrics, **extra)


def clean(client, *rooms):
    client.post("/api/demo/reset")
    for room in rooms:  # appareils remis en service
        for dtype, metrics in (("bp", {"sys": 120, "dia": 80, "map": 93}), ("iv_pump", {"rateMlH": 80, "volumeLeftMl": 400, "occlusion": False})):
            client.post("/api/ingest", json=device(room, dtype, metrics, status="running"))
    wait_for(lambda: all(not client.get("/api/rooms/states").json()[r].get("deviceFaults") for r in rooms))


def test_machine_error_event_becomes_an_equipment_risk_on_our_device(client, login):
    clean(client, "103")
    r = client.post("/api/demo/trigger", json={"patient_id": "patient_03", "event_type": "machine_error", "machine_type": "IV Pump", "risk_level": "high", "recommendations": ["Send nurse"]})
    assert r.status_code == 200
    p = client.get("/api/patients").json()["patient_03"]                        # état legacy d'Amal (cartes, 3D)
    assert p["machine_error"] is True and p["machine_type"] == "IV Pump" and p["state"] == "machine_error" and p["alert_priority"] == "high"
    ev = client.get("/api/events").json()[0]
    assert ev["event_type"] == "machine_error" and ev["machine_error"] is True and ev["machine_type"] == "IV Pump"
    risks = wait_for(lambda: open_risks(client, "103", "equipment_fault"))
    assert risks and risks[0]["severity"] == "high" and risks[0]["source_agent"] == "VitalsAgent" and risks[0]["type_label"] == "Panne d'équipement"
    faults = client.get("/api/rooms/states").json()["103"]["deviceFaults"]      # rattaché à NOTRE pompe à perfusion
    assert faults["iv_pump"]["device"] == "103-iv_pump" and faults["iv_pump"]["name"] == "Pompe à perfusion"
    assert next(d for d in client.get("/api/devices?room=103").json() if d["type"] == "iv_pump")["fault"]["code"] == "reported"
    # pas de doublon avec les risques de perfusion ; l'infirmier est notifié
    assert not open_risks(client, "103", "iv_empty") and not open_risks(client, "103", "iv_occlusion")
    notifs = wait_for(lambda: [n for n in client.get("/api/notifications").json()["items"] if n.get("risk_id") == risks[0]["id"] and n["target_role"] == "nurse"])
    assert notifs and "Panne d'équipement" in notifs[0]["title"]
    plan = client.get(f"/api/risks/{risks[0]['id']}").json()["plan"]
    assert plan and any("salle Équipements" in s["text"] for s in plan["steps"])
    # « recover » : l'appareil est signalé réparé ; le risque attend la confirmation d'un soignant (jamais de clôture automatique)
    client.post("/api/yolo/event", json={"patient_id": "patient_03", "event_type": "recover"})
    assert client.get("/api/patients").json()["patient_03"]["machine_error"] is False
    assert wait_for(lambda: not client.get("/api/rooms/states").json()["103"]["deviceFaults"])
    assert client.get(f"/api/risks/{risks[0]['id']}").json()["status"] in ("open", "escalated", "in_progress")


def test_device_stream_fault_is_shown_on_the_device_and_mirrored_in_3d_state(client):
    clean(client, "102")
    client.post("/api/ingest", json=device("102", "bp", {"sys": 118, "dia": 76, "map": 90}, status="alarm", fault={"code": "sensor", "label": "brassard déconnecté"}))
    risks = wait_for(lambda: open_risks(client, "102", "equipment_fault"))
    assert risks and risks[0]["severity"] == "medium"                            # tensiomètre : appareil non vital
    rs = client.get("/api/rooms/states").json()["102"]
    assert rs["deviceFaults"]["bp"]["label"] == "brassard déconnecté" and rs["devices"]["102-bp"]["fault"]["code"] == "sensor"
    p = client.get("/api/patients").json()["patient_02"]                         # reflété dans l'état legacy → indicateur 3D d'Amal
    assert p["machine_error"] is True and "Tensiomètre" in p["machine_type"]
    # un second appareil en panne dans la même chambre : même risque, sévérité relevée (appareil vital)
    client.post("/api/ingest", json=device("102", "ecg", {"hr": 80, "rhythm": "sinus"}, status="alarm", fault={"code": "power"}))
    wait_for(lambda: "ecg" in client.get("/api/rooms/states").json()["102"]["deviceFaults"])
    assert len(open_risks(client, "102", "equipment_fault")) == 1
    # appareils de nouveau en service : signal levé, risque à confirmer par un soignant
    client.post("/api/ingest", json=device("102", "bp", {"sys": 118, "dia": 76, "map": 90}, status="running"))
    client.post("/api/ingest", json=device("102", "ecg", {"hr": 80, "rhythm": "sinus"}, status="running"))
    assert wait_for(lambda: not client.get("/api/rooms/states").json()["102"]["deviceFaults"])
    assert wait_for(lambda: client.get("/api/patients").json()["patient_02"]["machine_error"] is False)
    assert "appareils de nouveau en service" in (client.get(f"/api/risks/{risks[0]['id']}").json()["notes"] or "")


def test_iv_occlusion_and_empty_bag_are_not_counted_as_equipment_faults(client):
    clean(client, "104")
    for _ in range(4):
        client.post("/api/ingest", json=device("104", "iv_pump", {"rateMlH": 0, "volumeLeftMl": 300, "occlusion": True}, status="alarm", fault={"code": "occlusion"}))
    assert wait_for(lambda: open_risks(client, "104", "iv_occlusion"))
    assert not open_risks(client, "104", "equipment_fault") and not client.get("/api/rooms/states").json()["104"]["deviceFaults"]
    client.post("/api/ingest", json=device("104", "iv_pump", {"rateMlH": 80, "volumeLeftMl": 300, "occlusion": False}, status="running"))


def test_contract_scenarios_and_3d_assets(client):
    from app import contracts, equipment, resolutions
    from simulator.engine import Scenario, SimEngine

    contracts.validate("hackcure/room/101/device/101-ecg", {"ts": "t", "source": "sim", "type": "ecg", "metrics": {"hr": 70, "rhythm": "sinus"}, "fault": {"code": "power"}})
    try:
        contracts.validate("hackcure/room/101/device/101-ecg", {"ts": "t", "source": "sim", "type": "ecg", "metrics": {"hr": 70, "rhythm": "sinus"}, "fault": {"label": "sans code"}})
        raise AssertionError("une panne sans code doit être refusée")
    except contracts.ContractError:
        pass
    assert equipment.device_type("ECG Monitor") == "ecg" and equipment.device_type("Blood Pressure Monitor") == "bp" and equipment.device_type("?") == "other"
    resolutions._catalog = None
    assert resolutions.plan_for("equipment_fault")["scenario"] == "equipment_resolves" and resolutions.plan_for("equipment_fault")["role"] == "nurse"
    assert Scenario.load("machine_error_103").steps[0].action == "device_fault"
    # simulateur : l'appareil en panne publie status « alarm » + fault, puis redevient normal
    out = []
    eng = SimEngine(publish=lambda t, p: out.append((t, p)), speed=1.0)
    eng.apply("103", "device_fault", device="iv_pump", code="motor", label="défaut moteur")
    eng.tick(1.5)
    pump = [p for t, p in out if t.endswith("103-iv_pump")][-1]
    assert pump["status"] == "alarm" and pump["fault"] == {"code": "motor", "label": "défaut moteur"}
    eng.apply("103", "device_clear")
    out.clear()
    eng.tick(1.5)
    assert "fault" not in [p for t, p in out if t.endswith("103-iv_pump")][-1]
    # 3D : apports d'Amal conservés + notre bandeau (chambre et salle Équipements de l'étage 1)
    html = client.get("/").text
    assert "/static/js/equipment-faults.js" in html and 'id="demo-machine-type"' in html and 'data-event="machine_error"' in html
    assert "machErrIndicator" in client.get("/static/js/avatars.js").text and "MACHINE FAILURE" in client.get("/static/js/scene.js").text
    js = client.get("/static/js/equipment-faults.js").text
    assert "regs.EQP" in js and "deviceFaults" in js
    assert "getMachineErrorPatients" in client.get("/static/js/patient-state.js").text

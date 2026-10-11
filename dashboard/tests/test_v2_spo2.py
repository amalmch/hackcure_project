"""V2 étape 6 — SpO2 : seuils déterministes (standard et BPCO), chute rapide, NEWS2 échelle 2, oxymètre partout, scénario desaturation_103."""
from app.clinical.news2 import news2
from app.clinical.spo2 import classify, is_copd

from .test_agents import msg, open_risks, wait_for


def test_thresholds_standard_patient():
    assert classify(96)["level"] == "none"
    assert classify(93)["level"] == "attention" and classify(93)["severity"] == "medium"
    assert classify(89)["level"] == "high" and classify(89)["severity"] == "high"
    assert classify(87)["level"] == "critical" and classify(87)["severity"] == "critical"
    assert classify(None)["level"] == "none"


def test_thresholds_copd_target_88_92():
    assert is_copd({"history": "BPCO stade III sous oxygène"}) and not is_copd({"history": "HTA"})
    assert classify(90, copd=True)["level"] == "none"          # dans la cible 88–92 %
    assert classify(87, copd=True)["level"] == "attention"
    assert classify(84, copd=True)["level"] == "high"
    assert classify(82, copd=True)["level"] == "critical"
    assert "88–92" in classify(87, copd=True)["target"]


def test_rapid_drop_is_critical_only_below_target():
    assert classify(92, drop_per_min=5)["level"] == "critical"   # sous 94 % et −5 points en 1 min
    assert classify(95, drop_per_min=5)["level"] == "none"       # encore dans la cible : pas d'alerte
    assert classify(92, drop_per_min=2)["level"] == "attention"


def test_news2_scale2_for_copd():
    assert news2(spo2=90, rr=18, sbp=120, hr=80, temp=37.0).components["spo2"] == 3                      # échelle 1
    assert news2(spo2=90, rr=18, sbp=120, hr=80, temp=37.0, spo2_scale2=True).components["spo2"] == 0    # échelle 2 : dans la cible
    assert news2(spo2=97, on_oxygen=True, spo2_scale2=True).components["spo2"] == 3                      # hyperoxie sous O2
    assert news2(spo2=84, spo2_scale2=True).components["spo2"] == 2


def test_every_room_has_a_pulse_oximeter(client):
    devices = client.get("/api/devices").json()
    rows = devices if isinstance(devices, list) else devices.get("devices", [])
    rooms = {d.get("room") or d.get("room_code") for d in rows if d.get("type") == "spo2"}
    assert rooms >= {"101", "102", "103", "104"}


def spo2(room, value):
    return msg(f"hackcure/room/{room}/device/{room}-spo2", type="spo2", metrics={"spo2": value})


def test_desaturation_levels_create_graded_risks(client):
    client.post("/api/demo/reset")
    # patient standard (102) : 92 % ⇒ attention (moyen), puis 89 % ⇒ élevé, puis 86 % ⇒ critique (sévérité relevée, pas de doublon)
    for _ in range(3):
        client.post("/api/ingest", json=spo2("102", 92))
    r = wait_for(lambda: open_risks(client, "102", "hypoxemia"))
    assert r and r[0]["severity"] == "medium"
    for _ in range(3):
        client.post("/api/ingest", json=spo2("102", 86))
    assert wait_for(lambda: [x for x in open_risks(client, "102", "hypoxemia") if x["severity"] == "critical"])
    assert len(open_risks(client, "102", "hypoxemia")) == 1
    # KPI : SpO2 la plus basse
    k = client.get("/api/kpi").json()
    assert k["spo2_min"] == 86 and k["spo2_min_room"] == "102"
    # patient BPCO (103) : 90 % est dans sa cible ⇒ aucun risque ; 84 % ⇒ élevé
    before = len(open_risks(client, "103", "hypoxemia"))
    for _ in range(4):
        client.post("/api/ingest", json=spo2("103", 90))
    import time

    time.sleep(0.8)
    assert len(open_risks(client, "103", "hypoxemia")) == before
    for _ in range(3):
        client.post("/api/ingest", json=spo2("103", 84))
    r = wait_for(lambda: open_risks(client, "103", "hypoxemia"))
    assert r and r[0]["severity"] in ("high", "critical")


def test_desaturation_scenario_exists_with_resolution():
    from simulator.engine import Scenario

    names = {s["name"]: s for s in Scenario.available()}
    assert "desaturation_103" in names and names["desaturation_103"]["room"] == "103"
    assert "hypoxemia" in names["desaturation_resolves"]["resolves"]

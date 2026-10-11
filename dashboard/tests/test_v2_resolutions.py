"""
V2 étape 1 — chaque scénario a sa résolution par un soignant, et une action d'environnement ne résout
jamais un risque clinique.

Pour chaque type de risque : déclenchement → risque → « Je prends en charge » → intervention simulée
(avatar du bon rôle dans la chambre) → sortie → revérification déterministe → `resolved` + vérifié.
Le moteur de simulation est piloté par le test (temps simulé accéléré) à travers `POST /api/ingest`.
"""
import time

import pytest

from .test_agents import msg, open_risks, wait_for
from .test_integration_demo import Player


class Sim(Player):
    """Player branché comme simulateur embarqué : « Je prends en charge » y lance les résolutions."""

    def __init__(self, client, room):
        super().__init__(client, room)
        self.events = []
        self.roles_seen = set()
        self.engine.on_scenario_event = self._on_event

    def _on_event(self, kind, data):
        self.events.append((kind, data))
        if kind == "resolution_step" and (data.get("params") or {}).get("hook") in ("behavior_recover", "equipment_repaired"):
            self.client.post("/api/demo/trigger", json={"patient_id": f"patient_0{data['room'][-1]}", "event_type": "recover"})

    def play(self, seconds, step=0.5, pace=0.07):
        t = 0.0
        while t < seconds:
            self.engine.tick(step)
            t += step
            self.flush()
            role = self.client.get("/api/rooms/states").json()[self.room].get("staffRole") if int(t * 2) % 8 == 0 else None
            if role:
                self.roles_seen.add(role)
            time.sleep(pace)
        time.sleep(0.3)


@pytest.fixture()
def sim(client, monkeypatch):
    from app.sim import embedded

    created = []

    def factory(room):
        s = Sim(client, room)
        s.room = room
        monkeypatch.setattr(embedded, "engine", s.engine)
        created.append(s)
        return s

    client.post("/api/demo/reset")
    yield factory


def _fall(s):
    s.engine.apply(s.room, "fall")


def _bed_exit(s):
    s.engine.apply(s.room, "night", value=True)
    s.engine.apply(s.room, "posture", posture="standing", activity="out_of_bed", zone="floor")


def _fever(s):
    s.engine.apply(s.room, "trend", metric="temp", target=39.1, duration=2, hold=900)


def _news2(s):
    for metric, target in (("hr", 132), ("sys", 86), ("rr", 27), ("spo2", 90), ("temp", 39.3)):
        s.engine.apply(s.room, "trend", metric=metric, target=target, duration=2, hold=900)


def _desaturation(s):
    s.engine.apply(s.room, "trend", metric="spo2", target=85, duration=2, hold=900)


def _iv(s):
    s.engine.apply(s.room, "iv_volume", volume=28)


def _hypotension(s):
    s.engine.apply(s.room, "trend", metric="sys", target=82, duration=2, hold=900)


def _pain(s):
    s.engine.apply(s.room, "expression", expression="pain", confidence=0.9)


def _transfusion(s):
    s.engine.apply(s.room, "device_status", device="transfusion", status="running")
    s.engine.apply(s.room, "reaction", value=True)


def _behavior(s):
    s.client.post("/api/demo/trigger", json={"patient_id": f"patient_0{s.room[-1]}", "event_type": "behavioral_risk", "risk_level": "high", "risk_score": 0.8, "behavior_indicators": ["agitation"]})


def _device_fault(s):
    s.engine.apply(s.room, "device_fault", device="ecg", code="power", label="défaut d'alimentation")


def _machine_error(s):
    s.client.post("/api/demo/trigger", json={"patient_id": f"patient_0{s.room[-1]}", "event_type": "machine_error", "machine_type": "Blood Pressure Monitor"})


CASES = [
    # (type de risque, chambre, déclencheur, scénario de résolution, rôle intervenant)
    ("fall", "104", _fall, "fall_resolves", "nurse"),
    ("unaccompanied_bed_exit", "103", _bed_exit, "bed_exit_resolves", "nurse"),
    ("fever", "104", _fever, "fever_resolves", "duty_doctor"),
    ("news2_high", "103", _news2, "sepsis_resolves", "duty_doctor"),
    ("hypoxemia", "104", _desaturation, "desaturation_resolves", "nurse"),
    ("iv_empty", "104", _iv, "iv_resolves", "nurse"),
    ("hypotension", "104", _hypotension, "vitals_resolves", "nurse"),
    ("pain", "103", _pain, "pain_resolves", "nurse"),
    ("transfusion_reaction", "104", _transfusion, "transfusion_resolves", "duty_doctor"),
    ("behavioral_risk", "103", _behavior, "visit_resolves", "nurse"),
    ("equipment_fault", "104", _device_fault, "equipment_resolves", "nurse"),
    ("equipment_fault", "103", _machine_error, "equipment_resolves", "nurse"),
]


@pytest.mark.parametrize("rtype,room,trigger,scenario,role", CASES, ids=[f"{c[0]}-{c[1]}" for c in CASES])
def test_each_scenario_has_a_caregiver_resolution(client, login, sim, rtype, room, trigger, scenario, role):
    s = sim(room)
    s.play(3)
    trigger(s)
    s.play(8)
    risks = wait_for(lambda: [r for r in open_risks(client, room, rtype) if r["status"] in ("open", "escalated")], timeout=25)
    assert risks, f"risque {rtype} attendu en chambre {room}"
    rid = risks[0]["id"]

    # prise en charge : l'intervention simulée du bon rôle démarre
    ack = login("nurse").post(f"/api/risks/{rid}/ack").json()
    assert ack["status"] == "in_progress"
    assert ack["resolution"] and ack["resolution"]["scenario"] == scenario and ack["resolution"]["role"] == role
    assert ack["resolution"]["duration"] >= 45

    # le soignant reste visible au moins 45 s (temps simulé), puis sort
    s.play(ack["resolution"]["duration"] + 6)
    kinds = [k for k, _ in s.events]
    assert "resolution_started" in kinds and "resolution_finished" in kinds
    enter = next(d for k, d in s.events if k == "resolution_step" and d["action"] == "staff_enter")
    leave = next(d for k, d in s.events if k == "resolution_step" and d["action"] == "staff_leave")
    assert leave["at"] - enter["at"] >= 45 and enter["params"]["role"] == role
    assert role in s.roles_seen, f"avatar {role} attendu dans la chambre, vu : {s.roles_seen}"

    # sortie du soignant ⇒ revérification déterministe ⇒ résolu + vérifié
    final = wait_for(lambda: (lambda d: d if d["status"] == "resolved" else None)(client.get(f"/api/risks/{rid}").json()), timeout=15)
    assert final, f"risque non résolu : {client.get(f'/api/risks/{rid}').json()}"
    assert final["verified_at"] and "vérifié" in final["resolved_by"]
    assert client.get("/api/rooms/states").json()[room]["staffRole"] is None


def test_catalog_covers_every_risk_type(client):
    from app import resolutions
    from app.agents.plans import TYPE_LABELS

    resolutions._catalog = None
    cat = resolutions.catalog()
    environmental = {"thermal_discomfort", "room_overheat"}
    missing = [t for t in TYPE_LABELS if t not in cat and t not in environmental]
    assert not missing, f"types de risque sans scénario de résolution : {missing}"
    assert all(v["duration"] >= 50 for v in cat.values())


def test_environment_command_never_resolves_a_clinical_risk(client):
    client.post("/api/demo/reset")
    for _ in range(3):
        client.post("/api/ingest", json=msg("hackcure/room/102/device/102-thermometer", type="thermometer", metrics={"tempC": 39.2}))
    risks = wait_for(lambda: open_risks(client, "102", "fever"))
    assert risks
    rid = risks[0]["id"]
    # ouvrir la fenêtre : l'état change, la 3D le reçoit (room_state.equipment), le journal le trace…
    r = client.post("/api/commands", json={"room": "102", "equipment": "window", "action": "open", "reason": "test"}).json()
    assert r["ok"] and r["ack"]["state"] == "open"
    assert client.get("/api/rooms/states").json()["102"]["equipment"]["window"] == "open"
    logs = wait_for(lambda: [l for l in client.get("/api/agents/logs?room=102&limit=30").json() if l["agent"] == "EnvironmentAgent" and "commande de" in l["input"]])
    assert logs and "aucun risque clinique" in logs[0]["reasoning"]
    # …mais le risque clinique reste ouvert, même quand la température redescend
    for _ in range(3):
        client.post("/api/ingest", json=msg("hackcure/room/102/device/102-thermometer", type="thermometer", metrics={"tempC": 37.0}))
    time.sleep(1.2)
    d = client.get(f"/api/risks/{rid}").json()
    assert d["status"] == "open" and "à confirmer par un soignant" in d["notes"]
    client.post("/api/commands", json={"room": "102", "equipment": "window", "action": "close", "reason": "test"})


def test_real_edge_room_is_never_simulated(client, login, monkeypatch):
    from app.ingest import handler

    client.post("/api/demo/reset")
    monkeypatch.setitem(handler.edge_seen, "101", time.time())
    client.post("/api/ingest", json=msg("hackcure/room/101/call", pressed=True))
    risks = wait_for(lambda: open_risks(client, "101", "call"))
    assert risks
    ack = login("nurse").post(f"/api/risks/{risks[0]['id']}/ack").json()
    assert ack["status"] == "in_progress" and ack["resolution"] is None

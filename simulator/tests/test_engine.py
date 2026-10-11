"""Moteur de simulation : messages conformes aux contrats, scénarios, repli VitalDB."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))

from simulator.engine import DEFAULT_PROFILES, Scenario, SimEngine  # noqa: E402
from simulator.vitaldb_replay import VitalReplayer, synthetic_track  # noqa: E402


@pytest.fixture()
def validator():
    from app import contracts
    return contracts


def collect(engine, seconds=3.0, step=0.25):
    out = []
    engine.publish = lambda t, p: out.append((t, p))
    t = 0.0
    while t < seconds:
        engine.tick(step)
        t += step
    return out


def test_engine_messages_are_valid(validator):
    eng = SimEngine(publish=lambda *_: None)
    msgs = collect(eng, 3.0)
    assert msgs, "le moteur doit publier"
    kinds = set()
    for topic, payload in msgs:
        kind, groups = validator.validate(topic, payload)  # lève si invalide
        kinds.add(kind)
        json.dumps(payload)  # sérialisable
    assert {"vision_state", "device", "env", "thermal", "vision_expression"} <= kinds
    rooms = {t.split("/")[2] for t, _ in msgs}
    assert rooms == {"101", "102", "103", "104"}


def test_all_device_types_for_all_rooms(validator):
    eng = SimEngine(publish=lambda *_: None)
    msgs = collect(eng, 1.5)
    devices = {t.split("/")[-1] for t, _ in msgs if "/device/" in t}
    assert len(devices) == 36  # 9 types × 4 chambres (V2 : glucomètre)
    assert "101-iv_pump" in devices and "104-thermometer" in devices


def test_fall_demo_scenario_reaches_on_floor():
    eng = SimEngine(publish=lambda *_: None)
    eng.start_scenario("fall_demo")
    msgs = collect(eng, 20.0, 0.5)
    states = [p for t, p in msgs if t == "hackcure/room/104/vision/state"]
    postures = [s["posture"] for s in states]
    assert "standing" in postures or "walking" in postures
    assert postures[-1] == "on_floor"
    assert states[-1]["activity"] == "fall"
    expr = [p for t, p in msgs if t == "hackcure/room/104/vision/expression"]
    assert expr[-1]["expression"] == "pain"
    # tachycardie induite
    hr = [p["metrics"]["hr"] for t, p in msgs if t.endswith("104-ecg")]
    assert hr[-1] > hr[0]


def test_nurse_resolves_emits_staff_events():
    eng = SimEngine(publish=lambda *_: None)
    eng.rooms["104"].fall()
    eng.start_scenario("nurse_resolves")
    msgs = collect(eng, 30.0, 0.5)
    staff = [p["event"] for t, p in msgs if t == "hackcure/room/104/vision/staff"]
    assert staff == ["staff_enter", "staff_leave"]
    assert eng.rooms["104"].posture == "lying_bed"
    leave = [p for t, p in msgs if t == "hackcure/room/104/vision/staff"][-1]
    assert leave["durationSec"] is not None


def test_iv_empty_and_occlusion():
    eng = SimEngine(publish=lambda *_: None)
    eng.start_scenario("iv_empty")
    msgs = collect(eng, 25.0, 0.5)
    iv = [p for t, p in msgs if t.endswith("103-iv_pump")]
    assert iv[-1]["metrics"]["volumeLeftMl"] < 50
    assert iv[-1]["metrics"]["occlusion"] is True
    assert iv[-1]["status"] == "alarm"


def test_sepsis_trend_moves_vitals():
    eng = SimEngine(publish=lambda *_: None)
    eng.start_scenario("sepsis_trend")
    collect(eng, 130.0, 1.0)
    r = eng.rooms["102"]
    assert r.vitals["temp"] > 38.5
    assert r.vitals["hr"] > 110
    assert r.vitals["sys"] < 100


def test_command_ack_from_virtual_edge(validator):
    out = []
    eng = SimEngine(publish=lambda t, p: out.append((t, p)))
    eng.handle_command("102", "window", "open", command_id="c1")
    topic, payload = out[-1]
    assert topic == "hackcure/room/102/cmd/ack"
    validator.validate(topic, payload)
    assert payload["ok"] and payload["state"] == "open" and payload["commandId"] == "c1"
    assert eng.rooms["102"].equipment["window"] == "open"


def test_real_edge_disables_virtual_vision():
    eng = SimEngine(publish=lambda *_: None)
    eng.set_room_virtual("101", False)
    msgs = collect(eng, 2.0)
    assert not any(t.startswith("hackcure/room/101/vision") for t, _ in msgs)
    assert any(t.startswith("hackcure/room/101/device") for t, _ in msgs)


def test_scenarios_listed_and_loadable():
    names = {s["name"] for s in Scenario.available()}
    assert {"normal_night", "fall_demo", "sepsis_trend", "iv_empty", "nurse_resolves", "fever_101", "full_demo", "stop"} <= names
    for n in names:
        sc = Scenario.load(n)
        assert sc.steps or n == "normal_night"


def test_vitaldb_fallback_is_synthetic():
    rep = VitalReplayer(caseid=1, seconds=60, use_vitaldb=False)
    assert rep.source == "synthetic"
    v = rep.next()
    assert 40 <= v["hr"] <= 160 and 85 <= v["spo2"] <= 100
    tr = synthetic_track(30, seed=1)
    assert len(tr["hr"]) == 30 and all(d < s for d, s in zip(tr["dia"], tr["sys"]))


def test_profiles_cover_rooms():
    assert set(DEFAULT_PROFILES) == {"101", "102", "103", "104"}

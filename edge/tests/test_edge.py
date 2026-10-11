"""Edge : posture_map, zones/hystérésis, comptage de personnes, règles locales, pipeline synthétique, transport hors ligne."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))

from edge.actuators import Actuators  # noqa: E402
from edge.safety.local_rules import LocalRules  # noqa: E402
from edge.transport import HttpTransport, OfflineQueue  # noqa: E402
from edge.vision.persons import PersonTracker, Track  # noqa: E402
from edge.vision.pipeline import FakePipeline  # noqa: E402
from edge.vision.posture_map import map_to_contract, pose_rule_posture  # noqa: E402
from edge.vision.zones import ZoneTracker, point_in_polygon  # noqa: E402

BED = [(0.18, 0.35), (0.62, 0.33), (0.66, 0.85), (0.14, 0.88)]


# ─── posture_map (table 6.1) ──────────────────────────────────────────────────
@pytest.mark.parametrize("cv_class,zone,fall,still,last,expected", [
    ("patient_lying", "bed", False, 0, "none", ("lying_bed", "awake_bed", "bed")),
    ("patient_lying", "bed", False, 400, "none", ("lying_bed", "sleeping", "bed")),
    ("patient_sitting", "bed", False, 0, "none", ("sitting_bed", "awake_bed", "bed")),
    ("patient_sitting", "floor", False, 0, "none", ("sitting_chair", "out_of_bed", "floor")),
    ("patient_moving_out", "floor", False, 0, "none", ("standing", "out_of_bed", "floor")),
    ("patient_near_fall", "floor", False, 0, "none", ("standing", "out_of_bed", "floor")),
    ("patient_out", "exit", False, 0, "bed", ("absent", "out_of_room", "exit")),
    ("patient_out", "exit", False, 0, "bathroom_door", ("absent", "toilet", "exit")),
    (None, "none", False, 0, "bathroom_door", ("absent", "toilet", "none")),
    (None, "none", False, 0, "bed", ("absent", "out_of_room", "none")),
    ("patient_fallen", "floor", True, 0, "none", ("on_floor", "fall", "floor")),
    ("patient_fallen", "floor", False, 0, "none", ("standing", "out_of_bed", "floor")),
    ("falling", "floor", False, 0, "none", ("on_floor", "fall", "floor")),
    ("no_falling", "bed", False, 0, "none", ("lying_bed", "awake_bed", "bed")),
    ("pose_standing", "bathroom_door", False, 0, "none", ("standing", "out_of_bed", "bathroom_door")),
])
def test_posture_map_table(cv_class, zone, fall, still, last, expected):
    assert map_to_contract(cv_class, zone, fall_confirmed=fall, still_seconds=still, last_zone=last).as_tuple() == expected


def test_posture_map_walking_flag():
    assert map_to_contract("patient_moving_out", "floor", moving=True).posture == "walking"


def test_pose_rules():
    lying = {"left_shoulder": (100, 200), "right_shoulder": (100, 220), "left_hip": (300, 205), "right_hip": (300, 225)}
    assert pose_rule_posture(lying, 60) == "pose_lying"
    sitting = {"left_shoulder": (100, 100), "right_shoulder": (130, 100), "left_hip": (105, 200), "right_hip": (125, 200), "left_knee": (110, 215), "right_knee": (125, 215)}
    assert pose_rule_posture(sitting, 200) == "pose_sitting"
    standing = {"left_shoulder": (100, 100), "right_shoulder": (130, 100), "left_hip": (105, 200), "right_hip": (125, 200), "left_knee": (110, 300), "right_knee": (125, 300)}
    assert pose_rule_posture(standing, 400) == "pose_standing"


# ─── zones et hystérésis ─────────────────────────────────────────────────────
def test_point_in_polygon():
    assert point_in_polygon((0.4, 0.6), BED)
    assert not point_in_polygon((0.9, 0.9), BED)


def test_zone_hysteresis_2s():
    z = ZoneTracker({"bed": BED, "bathroom_door": [(0.82, 0.2), (0.98, 0.2), (0.98, 0.75), (0.82, 0.75)], "exit": [(0, 0), (0.15, 0), (0.15, 0.3), (0, 0.3)]}, hysteresis_s=2.0)
    assert z.update((0.4, 0.6), now=0.0) == "bed"  # première zone acceptée immédiatement
    assert z.update((0.75, 0.6), now=0.5) == "bed"  # sol depuis 0.5 s : pas encore
    assert z.update((0.75, 0.6), now=1.9) == "bed"
    assert z.update((0.75, 0.6), now=2.6) == "floor"  # persistance ≥ 2 s
    assert z.last_known == "bed"
    assert z.update((0.4, 0.6), now=3.0) == "floor"  # retour lit : hystérésis aussi
    assert z.update((0.9, 0.5), now=3.5) == "floor"  # candidat changé → compteur relancé
    assert z.update((0.9, 0.5), now=5.6) == "bathroom_door"
    assert z.update(None, now=6.0) == "bathroom_door"
    assert z.update(None, now=8.5) == "none"
    assert z.last_known == "bathroom_door"


# ─── comptage de personnes / personnel ───────────────────────────────────────
def test_person_tracker_staff_events():
    pt = PersonTracker(BED, min_persist_frames=2)
    patient = Track(1, (150, 180, 350, 400), "patient_lying", 0.9)
    nurse = Track(2, (420, 150, 520, 420), None, 0.8)
    w, h = 640, 480
    assert pt.update([patient], w, h, now=0.0) == []
    assert pt.update([patient], w, h, now=0.5) == []
    assert pt.patient_id == 1 and pt.persons == 1
    assert pt.update([patient, nurse], w, h, now=1.0) == []  # 1 image : pas encore
    ev = pt.update([patient, nurse], w, h, now=1.5)
    assert ev and ev[0].event == "staff_enter" and ev[0].persons == 2
    assert [t.track_id for t in pt.staff_tracks([patient, nurse])] == [2]
    pt.update([patient], w, h, now=30.0)
    ev = pt.update([patient], w, h, now=30.5)
    assert ev and ev[0].event == "staff_leave" and ev[0].duration_s == pytest.approx(29.0, abs=0.6)
    # réassignation : le patient disparaît, une autre piste est dans le lit
    other = Track(7, (160, 190, 340, 390), "patient_lying", 0.9)
    assert pt.patient_track([other], w, h).track_id == 7 and pt.patient_id == 7


# ─── règles locales (sans réseau) ────────────────────────────────────────────
def test_local_rules_fall_and_call_and_climate():
    published = []
    act = Actuators({})
    rules = LocalRules(act, lambda t, p: published.append((t, p)), "101", {"buzzer_seconds": 0.01, "climate_hot_c": 27, "climate_cold_c": 19}, source="edge-fake")
    rules.night_override = True
    assert rules.on_fall(now=100.0) == ["buzzer", "nightlight"]
    assert published[-1][0] == "hackcure/room/101/safety/alarm" and published[-1][1]["reason"] == "fall"
    assert act.nightlight.state == "on"
    # pendant l'alarme chute, le serveur ne peut pas éteindre la veilleuse
    ok, state, err = rules.on_command("light", "off", None, "owner", now=110.0)
    assert not ok and "local_rule" in err
    ok, state, _ = rules.on_command("light", "off", None, "owner", now=200.0)
    assert ok and state == "off"
    assert rules.on_call(now=300.0) == ["buzzer", "nightlight"]
    assert published[-1][1]["reason"] == "call"
    # lever nocturne → veilleuse
    act.nightlight.off(); rules.manual_until.clear()
    assert rules.on_bed_exit(now=400.0) == ["nightlight"]
    rules.night_override = False
    act.nightlight.off()
    assert rules.on_bed_exit(now=500.0) == []
    # climat
    act.window.set(True)
    assert set(rules.on_env(28.5, now=600.0)) == {"ac:on", "window:closed"}
    assert act.ac.state == "on" and act.window.state == "closed"
    assert "ac:off" in rules.on_env(22.0, now=700.0)
    assert "heater:on" in rules.on_env(17.0, now=800.0)
    # une commande manuelle gèle la règle climat 10 min
    rules.on_command("ac", "on", None, "infirmier", now=900.0)
    assert rules.on_env(17.0, now=901.0) == []
    assert "heater:on" in rules.on_env(17.0, now=1600.0) or act.heater.state == "on"


# ─── pipeline synthétique → messages conformes aux contrats ──────────────────
def test_fake_pipeline_cycle_produces_fall_and_staff():
    pipe = FakePipeline(640, 480, speed=1.0)
    t0 = pipe.t0
    classes, persons, falls = [], [], []
    for s in range(0, 90):
        r = pipe.process(np.zeros((480, 640, 3), np.uint8), t0 + s)
        classes.append(r.tracks[0].cls)
        persons.append(len(r.tracks))
        falls.append(bool(r.fall_confirmed.get(1)))
    assert {"patient_lying", "patient_sitting", "patient_moving_out", "patient_fallen"} <= set(classes)
    assert max(persons) == 2
    assert any(falls) and not falls[0]


def test_edge_end_to_end_fake_messages_validate():
    """Boucle complète (--fake) : les messages publiés respectent les contrats du serveur."""
    from app import contracts  # dashboard/app
    from edge.main import Edge, load_config
    import argparse

    cfg = load_config(ROOT / "edge" / "config" / "room101.yaml")
    cfg["mqtt"]["host"] = ""
    cfg["server"]["url"] = "http://127.0.0.1:1"
    cfg["rules"]["offline_queue_file"] = None
    cfg["thermal"]["calibration_file"] = None
    args = argparse.Namespace(room="101", fake=True, broker=None, server=None, no_thermal=False, stream_port=0, show=False)
    edge = Edge(cfg, args)
    edge.transport.flush = lambda force=False: False  # pas de réseau
    sent = []
    edge.transport.publish = lambda topic, payload, critical=False: sent.append((topic, payload))
    frame = np.zeros((480, 640, 3), np.uint8)
    t0 = edge.pipeline.t0
    for s in range(0, 130):
        edge.handle_frame(frame, t0 + s * 0.5)
    kinds = set()
    for topic, payload in sent:
        kind, _ = contracts.validate(topic, payload)
        kinds.add(kind)
    assert {"vision_state", "vision_expression", "thermal", "env", "vision_staff"} <= kinds
    states = [p for t, p in sent if t.endswith("/vision/state")]
    assert any(s["activity"] == "fall" and s["posture"] == "on_floor" for s in states)
    assert any(s["source"] == "edge-fake" for s in states)
    alarms = [p for t, p in sent if t.endswith("/safety/alarm")]
    falls = [a for a in alarms if a["reason"] == "fall"]  # la nuit, une alarme « lever nocturne » précède la chute
    assert falls and "buzzer" in falls[0]["localActionTaken"]
    ok, state, err = edge._on_command("window", "open", None, "owner", "c1")
    assert ok and state == "open"


# ─── transport HTTP hors ligne ───────────────────────────────────────────────
def test_http_transport_offline_queue(tmp_path):
    q = tmp_path / "queue.jsonl"
    t = HttpTransport("http://127.0.0.1:1", "101", queue_file=str(q))
    t.publish("hackcure/room/101/vision/state", {"ts": "x", "source": "edge-fake"})
    t.publish("hackcure/room/101/safety/alarm", {"ts": "x", "source": "edge-fake", "reason": "fall", "localActionTaken": []}, critical=True)
    assert t.online is False
    assert len(t.queue) == 1  # seule l'alarme est conservée hors ligne
    assert json.loads(q.read_text(encoding="utf-8").splitlines()[0])["topic"].endswith("/safety/alarm")
    q2 = OfflineQueue(str(q))
    assert len(q2) == 1 and q2.drain()[0]["payload"]["reason"] == "fall" and len(q2) == 0


def test_behavior_publisher_is_optional_and_follows_the_contract():
    import json

    import numpy as np

    from edge.vision.behavior import BehaviorPublisher, build_behavior

    assert build_behavior({"behavior": {"enabled": False}}) is None
    assert BehaviorPublisher(None, "101").step(np.zeros((480, 640, 3), np.uint8), (10, 10, 100, 200), "standing", 0.9, False, False, 1.0) is None
    analyzer = build_behavior({})                       # sans poids ni PyTorch : analyse temporelle seule, sans erreur
    assert analyzer is not None and analyzer.mode == "temporal"
    pub = BehaviorPublisher(analyzer, "101")
    frame = np.zeros((480, 640, 3), np.uint8)
    first = pub.step(frame, (100, 100, 200, 300), "patient_lying", 0.9, False, True, 10.0)
    assert first and first["riskLevel"] == "low" and first["transformer"] is False
    assert pub.step(frame, (100, 100, 200, 300), "patient_lying", 0.9, False, True, 10.1) is None      # échantillonnage
    assert pub.step(frame, (100, 100, 200, 300), "patient_lying", 0.9, False, True, 11.0) is None      # pas de changement
    schema = json.loads((ROOT / "contracts" / "schemas" / "vision_behavior.json").read_text(encoding="utf-8"))
    assert set(schema["required"]) - {"ts", "source"} <= set(first)


# ─── intégrité des trames : signature au moment de l'envoi (V3) ──────────────
class _FakeRequests:
    """Remplace `requests` : enregistre les lots envoyés, ou simule une coupure."""

    def __init__(self):
        self.sent, self.down = [], False

    def post(self, url, json=None, headers=None, timeout=None):
        if self.down:
            raise ConnectionError("coupure simulée")
        self.sent.append(json["messages"])
        return type("R", (), {"status_code": 202})()


def test_http_transport_signs_at_send_time(tmp_path, monkeypatch):
    from contracts import integrity as prim

    monkeypatch.delenv("EDGE_HMAC_KEY", raising=False)
    key, topic = "cle-edge-test", "hackcure/room/101/vision/state"
    t = HttpTransport("http://127.0.0.1:1", "101", queue_file=str(tmp_path / "q.jsonl"), hmac_key=key)
    t.requests = fake = _FakeRequests()
    p1, p2 = {"ts": prim.now_iso(), "source": "edge-fake", "posture": "lying_bed"}, {"ts": prim.now_iso(), "source": "edge-fake", "posture": "standing"}
    t.publish(topic, p1)
    t.publish(topic, p2)
    assert t.flush(force=True) is True
    a, b = (m["payload"] for m in fake.sent[0])
    assert "sig" not in p1 and "seq" not in p1  # le payload d'origine n'est pas modifié
    assert prim.verify(topic, a, key) and prim.verify(topic, b, key) and b["seq"] > a["seq"] and a["ts"] == p1["ts"] and "measuredAt" not in a
    # sans clé : rien n'est ajouté (mode démo du serveur)
    plain = HttpTransport("http://127.0.0.1:1", "101")
    plain.requests = fake2 = _FakeRequests()
    plain.publish(topic, p1)
    plain.flush(force=True)
    assert fake2.sent[0][0]["payload"] == p1 and fake2.sent[0][0]["payload"] is p1


def test_offline_queue_is_restamped_and_resigned(tmp_path, monkeypatch):
    from contracts import integrity as prim

    monkeypatch.delenv("EDGE_HMAC_KEY", raising=False)
    key, q = "cle-edge-test", tmp_path / "q.jsonl"
    t = HttpTransport("http://127.0.0.1:1", "101", queue_file=str(q), hmac_key=key)
    t.requests = fake = _FakeRequests()
    fake.down = True
    old_ts = "2026-10-10T22:00:00+00:00"  # mesure faite pendant la coupure, bien plus de 30 s avant le renvoi
    alarm_topic = "hackcure/room/101/safety/alarm"
    t.publish(alarm_topic, {"ts": old_ts, "source": "edge-fake", "reason": "fall", "localActionTaken": ["buzzer"]}, critical=True)
    assert t.online is False and len(t.queue) == 1
    stored = json.loads(q.read_text(encoding="utf-8").splitlines()[0])["payload"]
    assert "sig" not in stored and "seq" not in stored and stored["ts"] == old_ts  # la file garde la mesure d'origine, non signée
    fake.down = False
    t.publish("hackcure/room/101/env", {"ts": prim.now_iso(), "source": "edge-fake", "tempC": 22.0})
    assert t.flush(force=True) is True and len(t.queue) == 0
    sent = [m for batch in fake.sent for m in batch]
    alarm = next(m["payload"] for m in sent if m["topic"] == alarm_topic)
    env = next(m["payload"] for m in sent if m["topic"].endswith("/env"))
    assert alarm["measuredAt"] == old_ts and alarm["ts"] != old_ts and alarm["reason"] == "fall"  # ré-horodatée à l'envoi
    assert abs(prim.parse_ts(alarm["ts"]) - prim.parse_ts(prim.now_iso())) < 5
    assert prim.verify(alarm_topic, alarm, key) and prim.verify("hackcure/room/101/env", env, key) and "measuredAt" not in env
    assert len({alarm["seq"], env["seq"]}) == 2


def test_build_transport_reads_the_key_from_env_then_config(monkeypatch):
    from edge.transport import build_transport

    cfg = {"mqtt": {"host": ""}, "server": {"url": "http://127.0.0.1:1"}, "security": {"hmac_key": "cle-du-yaml"}}
    monkeypatch.delenv("EDGE_HMAC_KEY", raising=False)
    t, kind = build_transport(cfg, "101")
    assert kind == "http" and t.signer.enabled and t.signer.key == "cle-du-yaml"
    monkeypatch.setenv("EDGE_HMAC_KEY", "cle-de-l-environnement")  # prioritaire sur le fichier
    assert build_transport(cfg, "101")[0].signer.key == "cle-de-l-environnement"
    monkeypatch.delenv("EDGE_HMAC_KEY")
    assert build_transport({"mqtt": {"host": ""}, "server": {"url": "http://127.0.0.1:1"}}, "101")[0].signer.enabled is False

"""Validation des contrats JSON Schema (contracts/schemas) et de la correspondance topic → schéma."""
import pytest

from app import contracts

TS = "2026-10-10T22:00:00+00:00"


def base(**kw):
    return {"ts": TS, "source": "sim", **kw}


VALID = [
    ("hackcure/room/101/vision/state", base(persons=1, patientTrackId=3, posture="lying_bed", activity="sleeping", zone="bed", confidence=0.91, cvClass="patient_lying")),
    ("hackcure/room/101/vision/state", base(persons=0, posture="absent", activity="out_of_room", zone="none", confidence=0.0)),
    ("hackcure/room/104/vision/staff", base(event="staff_enter", persons=2)),
    ("hackcure/room/104/vision/staff", base(event="staff_leave", persons=1, durationSec=95.5)),
    ("hackcure/room/101/vision/expression", base(expression="pain", confidence=0.7)),
    ("hackcure/room/101/thermal", base(skinTempC=36.8, maxTempC=37.2, calibrated=False)),
    ("hackcure/room/101/env", base(tempC=22.5, humidity=45, motion=True, doorOpen=False)),
    ("hackcure/room/101/call", base(pressed=True)),
    ("hackcure/room/102/device/102-iv_pump", base(type="iv_pump", metrics={"rateMlH": 80, "volumeLeftMl": 420, "occlusion": False})),
    ("hackcure/room/102/device/102-bp", base(type="bp", metrics={"sys": 120, "dia": 80, "map": 93})),
    ("hackcure/room/102/device/102-ecg", base(type="ecg", metrics={"hr": 72, "rhythm": "sinus"})),
    ("hackcure/room/102/device/102-spo2", base(type="spo2", metrics={"spo2": 97})),
    ("hackcure/room/102/device/102-thermometer", base(type="thermometer", metrics={"tempC": 37.1})),
    ("hackcure/room/102/device/102-oxygen", base(type="oxygen", metrics={"flowLMin": 2})),
    ("hackcure/room/102/device/102-transfusion", base(type="transfusion", metrics={"rateMlH": 120, "volumeLeftMl": 200, "reaction": False})),
    ("hackcure/room/102/device/102-nutrition_pump", base(type="nutrition_pump", metrics={"rateMlH": 60, "volumeLeftMl": 500})),
    ("hackcure/room/101/safety/alarm", base(reason="fall", localActionTaken=["buzzer", "nightlight"])),
    ("hackcure/room/101/cmd/window", base(action="open", requestedBy="EnvironmentAgent", reason="tempC 28.1 > 27")),
    ("hackcure/room/101/cmd/ack", base(equipment="window", action="open", ok=True, state="open")),
    ("hackcure/sim/scenario", base(name="fall_demo")),
]

INVALID = [
    ("hackcure/room/101/vision/state", base(persons=1, posture="flying", activity="sleeping", zone="bed", confidence=0.9)),
    ("hackcure/room/101/vision/state", base(persons=1, posture="lying_bed", activity="sleeping", zone="bed", confidence=1.4)),
    ("hackcure/room/101/vision/state", {"persons": 1, "posture": "lying_bed", "activity": "sleeping", "zone": "bed", "confidence": 0.5}),
    ("hackcure/room/101/thermal", base(skinTempC=36.8, maxTempC=37.2)),
    ("hackcure/room/102/device/102-bp", base(type="bp", metrics={"sys": 120})),
    ("hackcure/room/102/device/102-iv_pump", base(type="iv_pump", metrics={"rateMlH": 80, "volumeLeftMl": 420})),
    ("hackcure/room/101/cmd/window", base(action="explode", requestedBy="x", reason="y")),
    ("hackcure/room/101/cmd/ack", base(equipment="window", action="open", ok=True)),
    ("hackcure/sim/scenario", base(name="unknown_scenario")),
    ("hackcure/room/101/vision/staff", base(event="staff_enter")),
]


@pytest.mark.parametrize("topic,payload", VALID)
def test_valid_messages(topic, payload):
    name, groups = contracts.validate(topic, payload)
    assert name
    if topic.startswith("hackcure/room/"):
        assert groups["room"] in ("101", "102", "103", "104")


@pytest.mark.parametrize("topic,payload", INVALID)
def test_invalid_messages(topic, payload):
    with pytest.raises(contracts.ContractError):
        contracts.validate(topic, payload)


def test_unknown_topic():
    assert contracts.parse_topic("hackcure/room/101/unknown") is None
    with pytest.raises(contracts.ContractError):
        contracts.validate("foo/bar", {})


def test_every_schema_file_is_mapped():
    mapped = {name for _, name in contracts._TOPIC_RULES}
    assert set(contracts.all_schema_names()) == mapped


def test_cmd_ack_takes_precedence_over_cmd():
    assert contracts.parse_topic("hackcure/room/101/cmd/ack")[0] == "cmd_ack"
    assert contracts.parse_topic("hackcure/room/101/cmd/heater") == ("cmd", {"room": "101", "equipment": "heater"})

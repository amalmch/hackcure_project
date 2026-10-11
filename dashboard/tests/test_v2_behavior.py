"""
Analyse comportementale optionnelle (Amal 12e1eb2) : contrat `vision/behavior`, camera_loop fusionné,
VisionAgent → risque, facteur du PsychAgent.
"""
import importlib.util
import sys
from pathlib import Path

from .test_agents import msg, open_risks, wait_for

ROOT = Path(__file__).resolve().parents[2]


def behavior(room, level, score, indicators, **extra):
    return msg(f"hackcure/room/{room}/vision/behavior", riskLevel=level, riskScore=score, indicators=indicators, **extra)


def test_vision_behavior_contract_feeds_the_behavioral_risk_path(client):
    client.post("/api/demo/reset")
    client.post("/api/ingest", json=behavior("102", "low", 0.1, []))                       # calme : rien
    assert client.get("/api/patients").json()["patient_02"]["risk_level"] == "none" and not open_risks(client, "102", "behavioral_risk")
    r = client.post("/api/ingest", json=behavior("102", "high", 0.75, ["instability_pattern"], recommendations=["Dispatch nurse"], transformer=False))
    assert r.status_code in (200, 202)
    p = wait_for(lambda: (lambda x: x if x["risk_level"] == "high" else None)(client.get("/api/patients").json()["patient_02"]))
    assert p and p["behavior_indicators"] == ["instability_pattern"] and p["fall_detected"] is False
    risks = wait_for(lambda: open_risks(client, "102", "behavioral_risk"))
    assert risks and risks[0]["severity"] == "high" and risks[0]["source_agent"] == "VisionAgent"
    assert client.get("/api/rooms/states").json()["102"]["behavior"]["indicators"] == ["instability_pattern"]
    # retour au calme : état remis à zéro, le risque attend la confirmation d'un soignant
    client.post("/api/ingest", json=behavior("102", "low", 0.1, []))
    assert wait_for(lambda: client.get("/api/patients").json()["patient_02"]["risk_level"] == "none")
    assert client.post("/api/ingest", json=behavior("102", "panic", 0.5, [])).status_code == 422


def test_psych_score_uses_behavior_indicators():
    from app.clinical import psych

    base = psych.compute({"expr": {"total": 0}})
    res = psych.compute({"expr": {"total": 0}, "behavior": {"agitation": 3, "immobility": 4}})
    assert res["anxiety"]["score"] > base["anxiety"]["score"] and any("agitation observée 3 fois" in f for f in res["anxiety"]["factors"])
    assert any("immobilité prolongée" in f for f in res["depression"]["factors"])
    assert psych.compute({"expr": {"total": 0}, "behavior": {"agitation": 1}})["anxiety"]["score"] == base["anxiety"]["score"]


def test_psych_agent_collects_behavior_signals(client):
    from app.agents import manager

    client.post("/api/demo/reset")
    for _ in range(2):
        client.post("/api/demo/trigger", json={"patient_id": "patient_04", "event_type": "behavioral_risk", "risk_level": "moderate", "risk_score": 0.5, "behavior_indicators": ["agitation_detected"]})
    agent = manager.get("PsychAgent")
    assert wait_for(lambda: agent.sig("104").behavior_counts()["agitation"] >= 2)


def test_camera_loop_keeps_the_contract_format():
    from app import contracts

    spec = importlib.util.spec_from_file_location("camera_loop_merged", ROOT / "dashboard" / "camera_loop.py")
    cam = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cam)                         # import sans caméra, sans YOLO, sans PyTorch
    src = (ROOT / "dashboard" / "camera_loop.py").read_text(encoding="utf-8")
    assert "BehaviorAnalyzer" in src and "/api/ingest" in src and "/api/yolo/event" in src and "from src.transformer.model import" not in src
    analyzer = sys.modules["src.behavior"].BehaviorAnalyzer(use_transformer=False)
    ev = analyzer.update("patient_02", "falling", 0.93, velocity=0.2)
    msgs = cam.contract_messages(ev, "102", "sad")
    kinds = [contracts.validate(m["topic"], m["payload"])[0] for m in msgs]
    assert kinds == ["vision_state", "vision_expression", "vision_behavior"]
    assert msgs[0]["payload"]["posture"] == "on_floor" and msgs[0]["payload"]["source"] == "camera_loop"
    assert cam.legacy_payload(ev)["event_type"] == "fall"
    for _ in range(3):
        calm = analyzer.update("patient_09", "no_falling", 0.9, velocity=0.02)
    assert cam.legacy_payload(calm)["event_type"] == "recover" and cam.legacy_payload(calm) is None   # « recover » une seule fois

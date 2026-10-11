"""
Test d'intégration automatisé (FIN DU TRAVAIL) : scénario `fall_demo` puis `nurse_resolves` joués par le
vrai moteur de simulation à travers `POST /api/ingest` ⇒ risque critical créé, notification émise,
`StaffVisit` enregistré, risque `resolved` après vérification du FollowUpAgent.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simulator.engine import SimEngine  # noqa: E402


def wait_for(fn, timeout=8.0, interval=0.15):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    return last


class Player:
    """Fait avancer le moteur de simulation en envoyant chaque message au serveur (lots)."""

    def __init__(self, client, room="104"):
        self.client = client
        self.buffer = []
        self.engine = SimEngine(publish=lambda t, p: self.buffer.append({"topic": t, "payload": p}), rooms=[room], speed=1.0)
        self.engine.rooms[room].autonomous = False

    def play(self, seconds, step=0.5, pace=0.25):
        """`pace` = temps réel par pas simulé : l'hystérésis du VisionAgent (1 s) et le FollowUpAgent utilisent l'horloge réelle."""
        t = 0.0
        while t < seconds:
            self.engine.tick(step)
            t += step
            self.flush()
            time.sleep(pace)
        time.sleep(0.4)

    def flush(self):
        while self.buffer:
            batch, self.buffer = self.buffer[:200], self.buffer[200:]
            r = self.client.post("/api/ingest", json={"messages": batch})
            assert r.status_code == 202, r.text


def test_fall_demo_then_nurse_resolves(client):
    client.post("/api/demo/reset")
    p = Player(client, "104")

    # 1) fall_demo : lever nocturne puis chute en 104 (chute à t = 15 s)
    p.engine.start_scenario("fall_demo")
    p.play(22)
    risks = wait_for(lambda: [r for r in client.get("/api/risks?room=104&open_only=1").json() if r["type"] == "fall"])
    assert risks, "la chute doit créer un risque"
    fall = risks[0]
    assert fall["severity"] == "critical" and fall["status"] in ("open", "escalated")  # escaladé si personne ne vient (délai de test : 2 s)
    rs = client.get("/api/rooms/states").json()["104"]
    assert rs["posture"] == "on_floor" and rs["riskLevel"] == "critical"
    assert client.get("/api/patients").json()["patient_04"]["state"] in ("fall_detected", "fall_and_pain")
    notifs = client.get("/api/notifications").json()["items"]
    assert any(n["risk_id"] == fall["id"] for n in notifs), "notification émise"
    plan = wait_for(lambda: (lambda d: d["plan"] if d.get("plan") else None)(client.get(f"/api/risks/{fall['id']}").json()))
    assert plan and 3 <= len(plan["steps"]) <= 6
    assert [r for r in client.get("/api/risks?room=104").json() if r["type"] in ("unaccompanied_bed_exit", "bed_exit")], "le lever doit aussi être détecté"

    # 2) nurse_resolves : infirmier entre (t = 0), patient réinstallé (t = 14), infirmier sort (t = 22)
    p.engine.start_scenario("nurse_resolves")
    p.play(10)
    r = wait_for(lambda: (lambda d: d if d["status"] == "in_progress" else None)(client.get(f"/api/risks/{fall['id']}").json()))
    assert r, "risque en cours pendant la visite"
    visits = client.get("/api/staff/visits?room=104").json()
    assert visits and visits[0]["ended_at"] is None and visits[0]["risk_id"] == fall["id"], "StaffVisit enregistré"
    client.patch(f"/api/risks/{fall['id']}/steps/{plan['steps'][0]['id']}", json={"done": True})
    p.play(20)
    assert client.get("/api/staff/visits?room=104").json()[0]["ended_at"] is not None
    assert client.get("/api/rooms/states").json()["104"]["posture"] == "lying_bed"

    # 3) re-vérification (FOLLOWUP_RECHECK_S = 0.3 s en test) → résolu + vérifié
    r = wait_for(lambda: (lambda d: d if d["status"] == "resolved" else None)(client.get(f"/api/risks/{fall['id']}").json()), timeout=10)
    assert r and r["verified_at"] and "FollowUpAgent" in r["resolved_by"]
    # V2 : d'autres risques cliniques détectés pendant la chute (NEWS2, tachycardie) restent ouverts jusqu'à leur propre vérification
    assert not [x for x in client.get("/api/risks?room=104&open_only=1").json() if x["type"] == "fall"]
    assert client.get("/api/patients").json()["patient_04"]["state"] == "normal"
    logs = client.get("/api/agents/logs?room=104&limit=100").json()
    assert {l["agent"] for l in logs} >= {"VisionAgent", "RiskAgent", "FollowUpAgent"}
    assert any("vérifié" in (l["output"] or "") for l in logs if l["agent"] == "FollowUpAgent")

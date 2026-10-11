"""
Test d'intégration `full_demo_v2` (V2, étape 10).

Le vrai scénario YAML est joué par le moteur de simulation (temps simulé accéléré) à travers `POST /api/ingest` ;
les gestes des humains (étapes `hook`) sont joués par le pilote automatique `app/demo_v2.py` à travers l'API,
comme en démonstration. Enchaînement vérifié : admission par ambulance → questionnaire → fièvre vraie (bilan
clinique, biologique, confort) → rappel de médicament → prédiction de sepsis → chute → résolutions.
"""
import asyncio
import time
from datetime import datetime, timezone

from .test_agents import wait_for
from .test_v2_resolutions import Sim


class DemoSim(Sim):
    """Moteur piloté par le test, avec les 4 chambres ; les gestes `demo_*` passent par l'API (jeton de service)."""

    def __init__(self, client, service):
        super().__init__(client, "104")
        from simulator.engine import SimEngine

        self.engine = SimEngine(publish=lambda t, p: self.buffer.append({"topic": t, "payload": p}), speed=1.0)
        for r in self.engine.rooms.values():
            r.autonomous = False
        self.engine.on_scenario_event = self._on_event
        self.service = service

    def _on_event(self, kind, data):
        from app import demo_v2

        self.events.append((kind, data))
        hook = str((data.get("params") or {}).get("hook", ""))
        if kind == "scenario_step" and hook.startswith("demo_"):
            params = {"room": str(data.get("room")), **data["params"]}

            async def call(method, url, json):
                r = self.service.request(method, url, json=json)
                try:
                    return r.status_code, r.json()
                except ValueError:
                    return r.status_code, None

            asyncio.run(demo_v2.run(hook, params, call))
        elif kind == "resolution_step" and hook == "administer_due":
            from app.sim import embedded

            embedded._run_hook(hook, str(data.get("room")))

    def play(self, seconds, step=0.5, pace=0.1):
        t = 0.0
        while t < seconds:
            self.engine.tick(step)
            t += step
            self.flush()
            time.sleep(pace)


def test_full_demo_v2_end_to_end(client, server, monkeypatch):
    from fastapi.testclient import TestClient

    from app import demo_v2
    from app.sim import embedded

    service = TestClient(server.app)
    service.headers.update({"Authorization": "Bearer test-service-token"})
    client.post("/api/demo/reset")
    # état de départ propre : la patiente de la 104 est hospitalisée, aucune mission en cours
    if not next(p for p in client.get("/api/records").json() if p["patient_id"] == "patient_04")["room"]:
        client.post("/api/records/patient_04/admit", json={"room": "104", "reason": "Suites de prothèse de hanche", "referring_doctor": "Dr Nour Khelifi"})
    for m in client.get("/api/ambulances").json()["missions"]:
        if m["status"] in ("en_route", "arrived"):
            client.post(f"/api/ambulances/missions/{m['id']}/cancel")
    demo_v2.journal.clear()
    before = {m["id"] for m in client.get("/api/ambulances").json()["missions"]}
    started = datetime.now(timezone.utc).isoformat()
    sim = DemoSim(client, service)
    monkeypatch.setattr(embedded, "engine", sim.engine)
    monkeypatch.setattr(embedded, "_real_edge_rooms", set())  # aucun edge réel : les 4 chambres sont simulées (un test précédent a pu parler pour la 101)
    sc = sim.engine.start_scenario("full_demo_v2")
    assert 360 <= sc.duration <= 480, "full_demo_v2 doit durer 6 à 8 minutes"

    # 1) admission par ambulance : sortie, départ, chambre réservée, arrivée, installation
    sim.play(40)
    hooks = {j["hook"]: j["result"] for j in demo_v2.journal}
    assert "chambre libre" in hooks["demo_discharge"] or "déjà sorti" in hooks["demo_discharge"]
    assert "chambre 104 réservée" in hooks["demo_ambulance"], hooks
    mission = wait_for(lambda: next((m for m in client.get("/api/ambulances").json()["missions"] if m["id"] not in before and m["patient_id"] == "patient_04" and m["status"] == "admitted"), None), timeout=40)
    assert mission, "la patiente doit être installée en chambre 104"

    # 2) questionnaire d'admission rempli sur la tablette
    sim.play(60)
    assert wait_for(lambda: (client.get("/api/psych/patient_04").json()["questionnaire"] or {}).get("status") == "completed", timeout=15), ([j for j in demo_v2.journal if j["hook"] == "demo_questionnaire"], client.get("/api/psych/patient_04").json()["questionnaire"])

    # 3) fièvre vraie en 101 : bilan clinique, bilan biologique validé, confort ensuite, résultats versés au dossier
    sim.play(80)
    path = wait_for(lambda: next((p for p in client.get("/api/fever?room=101").json() if p["stage"] in ("lab_ordered", "lab_results", "resolved")), None), timeout=15)
    assert path and path["exam_done_by"] and path["labs_validated_by"] and "confort" in path["comfort_note"].lower(), [j for j in demo_v2.journal if "fever" in j["hook"]]
    assert wait_for(lambda: client.get(f"/api/fever/{path['id']}").json()["results"], timeout=10)

    # 4) ordonnance de traitement → plan d'administration → prise administrée
    sim.play(50)
    given = wait_for(lambda: [d for d in client.get("/api/care-plan?room=101").json()["given"] if "Paracétamol" in d["label"]], timeout=10)
    assert given, [j for j in demo_v2.journal if j["hook"] in ("demo_treatment_order", "demo_give_dose")]

    # 5) prédiction de sepsis en 102, 6) chute en 103, puis résolutions par les soignants
    sim.play(260)
    hooks = [j for j in demo_v2.journal if j["hook"] == "demo_ack"]
    # fièvre, sepsis et chute sont pris en charge ; le passage du psychiatre dépend du score de bien-être (pas de risque ⇒ rien à faire)
    assert len(hooks) == 5 and all("pris en charge" in h["result"] for h in hooks[:4]), hooks
    assert "equipment_fault" in hooks[1]["result"] and "infirmier" in hooks[1]["result"], hooks[1]   # panne de machine en 104
    preds = client.get("/api/predictions/patient_02").json()["history"]
    assert any(h["risk"] >= 60 for h in preds["sepsis"] + preds["deterioration"]), "prédiction de sepsis / détérioration élevée attendue en 102"

    def state():  # risques de la démo : la chute (103) et la fièvre (101), résolus et vérifiés pendant ce passage
        rows = [r for r in client.get("/api/risks?limit=200").json() if (r["room"], r["type"]) in (("103", "fall"), ("101", "fever"))]
        return {(r["room"], r["type"]) for r in rows if (r["resolved_at"] or "") >= started}, [(r["id"], r["room"], r["type"], r["status"], r["detected_at"], r["resolved_at"], r["notes"]) for r in rows if not r["resolved_at"]]

    assert wait_for(lambda: state()[0] == {("103", "fall"), ("101", "fever")}, timeout=30), " ; ".join(map(str, state()[1]))
    # la panne de machine (tensiomètre de la 104) est levée par l'infirmier, puis vérifiée
    eq = [r for r in client.get("/api/risks?limit=200").json() if r["room"] == "104" and r["type"] == "equipment_fault" and (r["resolved_at"] or "") >= started]
    assert eq and "vérifié" in eq[0]["resolved_by"], [r for r in client.get("/api/risks?limit=200").json() if r["type"] == "equipment_fault"]
    assert not client.get("/api/rooms/states").json()["104"]["deviceFaults"]
    kinds = [k for k, _ in sim.events]
    assert kinds.count("resolution_started") >= 4 and "scenario_finished" in kinds
    # chaque geste simulé est passé par l'API, et un compte rendu d'intervention attend la signature
    assert {j["hook"] for j in demo_v2.journal} == set(demo_v2.HOOKS)
    assert wait_for(lambda: [r for r in client.get("/api/interventions?status=draft").json() if r["content"]], timeout=10)
    # les tests suivants retrouvent un séjour neuf en 104 (questionnaire d'admission à remplir)
    client.post("/api/records/patient_04/discharge")
    assert client.post("/api/records/patient_04/admit", json={"room": "104", "reason": "Suites de prothèse de hanche", "referring_doctor": "Dr Nour Khelifi"}).status_code in (200, 201)

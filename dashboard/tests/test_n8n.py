"""
Orchestration n8n côté plateforme : jeton de service, endpoints appelés par les workflows, acquittement,
délégation à n8n et repli automatique sur les agents locaux. Aucun vrai n8n n'est contacté (N8N_ENABLED=0).
"""
import time

import pytest
from fastapi.testclient import TestClient

from .test_agents import open_risks, vision, wait_for

SERVICE = {"Authorization": "Bearer test-service-token"}


@pytest.fixture()
def service(server):
    """Client sans cookie, authentifié comme n8n par le jeton de service."""
    c = TestClient(server.app)
    c.headers.update(SERVICE)
    return c


def make_fall(client, room):
    client.post("/api/demo/reset")
    client.post("/api/ingest", json=vision(room, "lying_bed", "awake_bed"))
    client.post("/api/ingest", json=vision(room, "on_floor", "fall", "floor"))
    risks = wait_for(lambda: open_risks(client, room, "fall"))
    assert risks, "risque chute attendu"
    return risks[0]


def test_service_token_gives_owner_access(anon_client, service):
    assert anon_client.get("/api/rooms/101/state").status_code == 401
    assert anon_client.get("/api/rooms/101/state", headers={"Authorization": "Bearer mauvais-jeton"}).status_code == 401
    r = service.get("/api/rooms/101/state")
    assert r.status_code == 200 and "open_risks" in r.json() and "vitals" in r.json()
    assert service.get("/api/auth/me").json()["role"] == "owner"


def test_structured_events_require_auth(anon_client, service):
    assert anon_client.get("/api/events").status_code == 200  # historique legacy : reste ouvert
    assert anon_client.get("/api/events?hours=12").status_code == 401
    d = service.get("/api/events?hours=12").json()
    assert {"risks", "state_events", "moods", "visits", "rooms"} <= set(d)
    assert service.get("/api/events?since=pas-une-date").status_code == 400


def test_plan_ack_escalate_resolve_flow(client, service, login):
    r = make_fall(client, "103")
    rid = r["id"]
    # plan déposé par risk-triage
    body = {"explanation": "Chute au sol, FC 124 bpm.", "steps": [{"text": "Évaluer la conscience"}, {"text": "Mesurer les constantes"}, "Prévenir le médecin"],
            "llm_provider": "anthropic claude-sonnet-5-5 (n8n)", "resume_url": "http://127.0.0.1:9/webhook-waiting/1/risk-ack"}
    assert login("pharmacist").post(f"/api/risks/{rid}/plan", json=body).status_code == 403
    d = service.post(f"/api/risks/{rid}/plan", json=body).json()
    assert d["handled_by"] == "n8n" and d["explanation"] == "Chute au sol, FC 124 bpm."
    assert [s["text"] for s in d["plan"]["steps"]] == ["Évaluer la conscience", "Mesurer les constantes", "Prévenir le médecin"]
    assert d["plan"]["llm_provider"] == "anthropic claude-sonnet-5-5 (n8n)"
    # contrôle déterministe joint à l'état de la chambre (garde-fou de risk-verify)
    checks = {x["id"]: x["auto_check"] for x in service.get("/api/rooms/103/state").json()["open_risks"]}
    assert checks[rid]["ok"] is False
    # sans acquittement : escalade
    e = service.post(f"/api/risks/{rid}/escalate", json={"reason": "Aucune prise en charge en 2 min", "source": "n8n:risk-triage"}).json()
    assert e["escalated"] is True and e["status"] == "escalated" and e["escalated_at"]
    # « Je prends en charge » (n8n désactivé dans les tests : pas de reprise)
    a = login("nurse").post(f"/api/risks/{rid}/ack").json()
    assert a["status"] == "in_progress" and a["acknowledged_at"] and a["n8n_resumed"] is None
    # une escalade tardive est ignorée : le risque est pris en charge
    e2 = service.post(f"/api/risks/{rid}/escalate", json={"reason": "tardif"}).json()
    assert e2["escalated"] is False and e2["status"] == "in_progress"
    # verdict de risk-verify
    v = service.post(f"/api/risks/{rid}/resolve", json={"verified": True, "justification": "Patient assis au lit, FC 82 bpm.", "source": "n8n:risk-verify"}).json()
    assert v["status"] == "resolved" and v["verified_at"] and "n8n:risk-verify" in v["resolved_by"]
    assert not [x for x in client.get("/api/risks?room=103&open_only=1").json() if x["id"] == rid]


def test_plan_fallback_is_labelled_and_persistent_escalates(client, service):
    r = make_fall(client, "104")
    d = service.post(f"/api/risks/{r['id']}/plan", json={"steps": ["a", "b", "c"], "fallback": True}).json()
    assert "secours (LLM indisponible)" in d["plan"]["llm_provider"]
    p = service.post(f"/api/risks/{r['id']}/persistent", json={"justification": "Patient toujours au sol.", "source": "n8n:risk-verify"}).json()
    assert p["status"] == "escalated" and "risque persistant" in p["notes"]
    notifs = [n for n in client.get("/api/notifications").json()["items"] if n["risk_id"] == r["id"]]
    assert any(n["title"].startswith("Risque persistant") and n["target_role"] == "duty_doctor" for n in notifs)


def test_n8n_execution_log_appears_in_agents_panel(client, service):
    r = service.post("/api/agents/log", json={"agent": "risk-triage", "room": "101", "input": "webhook risk-created", "reasoning": "JSON validé", "output": "plan envoyé", "duration_ms": "8421"})
    assert r.status_code == 201
    logs = client.get("/api/agents/logs?room=101&limit=20").json()
    mine = [l for l in logs if l["agent"] == "n8n:risk-triage"]
    assert mine and mine[0]["duration_ms"] == 8421 and mine[0]["output"] == "plan envoyé"
    info = client.get("/api/agents").json()["n8n"]
    assert info["status"] == "disabled" and info["workflows"]["n8n:risk-triage"]["runs"] >= 1 and info["workflows"]["n8n:risk-triage"]["last_run"]


def test_shift_report_and_pharmacy_alerts(client, service):
    r = service.post("/api/shift-reports", json={"content": "# Rapport de garde\n\n## Chambre 101", "hours": 12, "source": "n8n:shift-report"})
    assert r.status_code == 201 and r.json()["print_url"] == f"/print/shift/{r.json()['id']}"
    assert client.get(f"/api/shift-reports/{r.json()['id']}").json()["author"] == "n8n:shift-report"
    d30, d60 = service.get("/api/pharmacy/alerts?days=30").json(), service.get("/api/pharmacy/alerts").json()
    assert d30["days"] == 30 and len(d30["expiring"]) <= len(d60["expiring"]) and "low_stock" in d30


def test_risk_is_delegated_to_n8n_when_online(client, monkeypatch):
    from app import n8n

    sent = []

    async def fake_probe(force=False):
        return True

    async def fake_send(name, payload, attempts=3):
        sent.append((name, payload))
        return True

    monkeypatch.setattr(n8n.settings, "n8n_enabled", True)
    monkeypatch.setattr(n8n, "probe", fake_probe)
    monkeypatch.setattr(n8n, "send_event", fake_send)
    r = make_fall(client, "102")
    ev = wait_for(lambda: [p for n, p in sent if n == "risk-created" and p["risk"]["id"] == r["id"]])
    assert ev, "le webhook risk-created doit être appelé"
    p = ev[0]
    assert p["risk"]["severity"] == "critical" and p["wait_seconds"] == 2 and p["platform_url"]
    assert p["patient"]["allergies"] is not None and "fall_risk" in p["patient"] and "age" in p["patient"]
    assert {"vitals", "vision", "staff_on_duty", "treatments"} <= set(p)
    # n8n orchestre : ni plan local, ni escalade locale par le FollowUpAgent (délai de test : 2 s)
    time.sleep(3.0)
    full = client.get(f"/api/risks/{r['id']}").json()
    assert full["handled_by"] == "n8n" and full["plan"] is None and full["status"] == "open"
    # sortie du personnel ⇒ webhook staff-left (risk-verify), pas de re-vérification locale
    client.post("/api/ingest", json=vision("102", "on_floor", "fall", "floor", persons=2))
    wait_for(lambda: client.get(f"/api/risks/{r['id']}").json()["status"] == "in_progress")
    client.post("/api/ingest", json=vision("102", "lying_bed", "awake_bed", "bed", persons=1))
    left = wait_for(lambda: [p for n, p in sent if n == "staff-left"])
    assert left and left[0]["room"] == "102" and r["id"] in left[0]["risk_ids"] and left[0]["recheck_seconds"] >= 0
    time.sleep(1.5)
    assert client.get(f"/api/risks/{r['id']}").json()["status"] == "in_progress"


def test_local_fallback_when_n8n_is_down(client, monkeypatch):
    from app import n8n

    monkeypatch.setattr(n8n.settings, "n8n_enabled", True)
    monkeypatch.setattr(n8n.settings, "n8n_base_url", "http://127.0.0.1:9")  # rien n'écoute
    monkeypatch.setattr(n8n, "_last_probe", 0.0)
    r = make_fall(client, "101")
    full = wait_for(lambda: (lambda d: d if d.get("plan") and d["plan"]["steps"] else None)(client.get(f"/api/risks/{r['id']}").json()), timeout=10)
    assert full and full["handled_by"] == "local" and 3 <= len(full["plan"]["steps"]) <= 6
    assert client.get("/api/n8n/status").json()["status"] == "offline"
    logs = client.get("/api/agents/logs?room=101&limit=30").json()
    assert any("n8n indisponible" in l["reasoning"] for l in logs if l["agent"] == "RiskAgent")


def test_every_agent_has_a_workflow_and_a_local_fallback(client):
    """Étape 9 V2 : un workflow n8n par agent, importable (fichier JSON sans secret), avec repli local."""
    import json
    from pathlib import Path

    from app import orchestration
    from app.agents import manager
    from app.agents.specs import SPECS, agent_map, build_prompt, validate

    rows = client.get("/api/agents/map").json()["rows"]
    assert len(rows) == len(agent_map()) >= 15
    agents_with_workflow = {r["agent"] for r in rows}
    assert {cls.name for cls in manager.AGENT_CLASSES} <= agents_with_workflow, "chaque agent doit avoir son workflow"
    folder = Path(__file__).resolve().parents[2] / "n8n" / "workflows"
    for r in rows:
        wf = json.loads((folder / f"{r['workflow']}.json").read_text(encoding="utf-8"))
        text = json.dumps(wf)
        assert wf["name"] == r["workflow"] and "sk-ant" not in text and "Bearer " not in text and r["trigger"]
        assert any(n["type"] == "n8n-nodes-base.webhook" and n["parameters"]["authentication"] == "headerAuth" for n in wf["nodes"])
    for name, s in SPECS.items():
        assert name in orchestration._handlers, f"gestionnaire manquant pour {name}"
        system, user = build_prompt(name, {"exemple": 1})
        assert "JAMAIS" in system and "JSON" in user
        assert validate(name, s["mock"]({})) is None or s["required"], name          # la réponse de secours est exploitable
        assert validate(name, None) is not None

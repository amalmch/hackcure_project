"""
V3, étape 2 — pseudonymisation : aucun nom de patient ne sort de la plateforme (LLM, n8n, Telegram, journaux),
et l'interface ne sert l'identité complète qu'aux rôles qui ont `view_identity`.
"""
import asyncio
import json
import logging

from .test_agents import msg, open_risks, vision, wait_for


def patient_names(client):
    """Noms, prénoms et noms complets de tous les patients (vus par le propriétaire)."""
    out = set()
    for p in client.get("/api/records").json():
        out |= {p["first_name"], p["last_name"], f"{p['first_name']} {p['last_name']}"}
    return {n for n in out if n and len(n) >= 3}


def leaks(names, text):
    """Noms présents comme mots entiers (« Test » dans « Testostérone » n'est pas une fuite)."""
    import re

    return sorted(n for n in names if re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", text))


def test_scrub_replaces_identity_fields_and_free_text(client):
    from app import privacy

    privacy.invalidate()
    rec = next(p for p in client.get("/api/records").json() if p["patient_id"] == "patient_03")
    full = f"{rec['first_name']} {rec['last_name']}"
    out = privacy.scrub({"patient": {"patient_id": "patient_03", "full_name": full, "first_name": rec["first_name"], "last_name": rec["last_name"], "birth_date": "1945-06-15", "age": 81, "sex": "M", "history": "BPCO"},
                         "note": f"{full} (81 ans) est tombé ; prévenir la famille de M. {rec['last_name']}."})
    p = out["patient"]
    assert p["full_name"] == rec["code"] and p["last_name"] == "" and p["birth_date"] == "1945" and p["pseudonyme"] == rec["code"]
    assert p["age"] == 81 and p["sex"] == "M" and p["history"] == "BPCO"                       # les données cliniques restent
    assert full not in out["note"] and rec["last_name"] not in out["note"] and rec["code"] in out["note"]
    assert privacy.text("Alimentation entérale, Mohamedia") == "Alimentation entérale, Mohamedia"  # pas de remplacement à l'intérieur d'un mot


def test_no_patient_name_leaves_the_platform(client, caplog, monkeypatch):
    from app import n8n, privacy
    from app.notify import telegram

    names = patient_names(client)
    assert len(names) >= 8
    client.post("/api/demo/reset")
    privacy.invalidate()
    privacy.sent.clear()
    caplog.set_level(logging.INFO)
    # une chute en 103 : risque, plan demandé au LLM, notifications (dont Telegram), journal des agents
    client.post("/api/ingest", json=vision("103", "lying_bed", "awake_bed"))
    client.post("/api/ingest", json=vision("103", "on_floor", "fall", zone="floor"))
    risks = wait_for(lambda: open_risks(client, "103", "fall"))
    assert risks
    assert wait_for(lambda: client.get(f"/api/risks/{risks[0]['id']}").json().get("plan"), timeout=10)
    # une fièvre en 101 (parcours fièvre : autre agent, autre prompt), un rapport de garde, un rapport médecin
    for _ in range(4):
        client.post("/api/ingest", json=msg("hackcure/room/101/device/101-thermometer", type="thermometer", metrics={"tempC": 39.2}))
    wait_for(lambda: open_risks(client, "101", "fever"))
    client.post("/api/shift-reports/generate", json={"hours": 12})
    # webhook n8n : capturé à la sortie (n8n est coupé dans les tests)
    posted = []

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            posted.append(json)
            return type("R", (), {"status_code": 200, "text": "ok"})()

    monkeypatch.setattr(n8n, "enabled", lambda: True)
    monkeypatch.setattr(n8n.httpx, "AsyncClient", FakeClient)
    full = client.get(f"/api/risks/{risks[0]['id']}").json()
    assert full["patient_name"] in names                                                        # en interne, le nom est bien là
    asyncio.run(n8n.send_event("risk-triage", {"event": "risk", "risk": full, "patient": {"patient_id": full["patient_id"], "full_name": full["patient_name"], "age": 81}}))
    asyncio.run(telegram.send_telegram(f"<b>Chute</b> — {full['patient_name']} — chambre 103"))
    assert posted and not leaks(names, json.dumps(posted, ensure_ascii=False)) and "PAT-" in json.dumps(posted)
    wait_for(lambda: any(c == "llm" for c, _ in privacy.sent))
    channels = {c for c, _ in privacy.sent}
    assert {"llm", "n8n", "telegram"} <= channels, channels
    for channel, text in list(privacy.sent):
        assert not leaks(names, text), (channel, leaks(names, text), text[:300])
    # journaux du serveur
    logging.getLogger("hackcure.test").info("Patient %s réinstallé au lit", full["patient_name"])
    assert not leaks(names, caplog.text), leaks(names, caplog.text)
    assert "PAT-" in caplog.text


def test_switch_disables_outbound_pseudonymisation(client, monkeypatch):
    from app import privacy

    rec = client.get("/api/records").json()[0]
    full = f"{rec['first_name']} {rec['last_name']}"
    privacy.invalidate()
    assert full not in privacy.outbound("llm", f"Patient {full}")
    monkeypatch.setenv("PSEUDONYMIZE_OUTBOUND", "0")
    assert full in privacy.outbound("llm", f"Patient {full}")


def test_identity_is_only_served_to_roles_that_need_it(client, login):
    from app import privacy
    from app.auth import PERMISSIONS

    assert PERMISSIONS["view_identity"] == {"receptionist", "nurse", "duty_doctor", "general_doctor", "owner", "psychiatrist"}
    privacy.invalidate()
    names = patient_names(client)
    pharma = login("pharmacist")
    seen = 0
    for url in ("/api/pharmacy/treatments", "/api/pharmacy/medications", "/api/pharmacy/alerts", "/api/dossier/patient_01", "/api/dossier/patient_01/profile",
                "/api/treatment-orders", "/api/patients", "/api/rooms/states", "/api/notifications", "/api/risks?limit=50", "/api/records"):
        r = pharma.get(url)
        if r.status_code == 200:
            seen += 1
            assert not leaks(names, r.text), (url, leaks(names, r.text))
    assert seen >= 3
    # les rôles soignants gardent l'identité complète
    for role in ("nurse", "general_doctor", "receptionist"):
        assert leaks(names, login(role).get("/api/records").text), role
    # WebSocket : un client sans identité reçoit la version pseudonymisée
    assert privacy.for_role("pharmacist", {"patient_name": next(iter(sorted(names, key=len, reverse=True)))})["patient_name"] not in names
    assert privacy.for_role("nurse", {"patient_name": "X Y"}) == {"patient_name": "X Y"}

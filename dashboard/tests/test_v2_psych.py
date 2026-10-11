"""V2 étape 7 — psychologie : rôle psychiatre, questionnaire d'admission (PHQ-9, GAD-7, sommeil), alerte de l'item 9, score continu, prescriptions."""
import time

import pytest

from app.clinical.psych import QUESTIONNAIRES, compute, score_answers

from .test_agents import msg, open_risks, vision, wait_for


# ── règles ───────────────────────────────────────────────────────────────────
def test_questionnaire_scoring_and_item9_alert():
    assert len(QUESTIONNAIRES["phq9"]["items"]) == 9 and len(QUESTIONNAIRES["gad7"]["items"]) == 7 and len(QUESTIONNAIRES["sleep"]["items"]) == 6
    low = score_answers({"phq9": [0] * 9, "gad7": [0] * 7, "sleep": [0] * 6})
    assert low["phq9"]["level"] == "minimal" and not low["q9_positive"]
    s = score_answers({"phq9": [2, 2, 2, 2, 2, 2, 2, 1, 0], "gad7": [2, 2, 2, 1, 1, 1, 1], "sleep": [3, 3, 2, 2, 1, 1]})
    assert s["phq9"] == {"score": 15, "max": 27, "level": "modérément sévère"} and s["gad7"]["level"] == "modéré" and s["sleep"]["level"] == "sévère"
    # item 9 positif : alerte quel que soit le score total
    q9 = score_answers({"phq9": [0, 0, 0, 0, 0, 0, 0, 0, 1], "gad7": [0] * 7, "sleep": [0] * 6})
    assert q9["phq9"]["score"] == 1 and q9["phq9"]["level"] == "minimal" and q9["q9_positive"]
    with pytest.raises(ValueError):
        score_answers({"phq9": [0] * 8, "gad7": [0] * 7, "sleep": [0] * 6})


def test_continuous_score_combines_factors_and_is_not_a_diagnosis():
    calm = compute({"questionnaire": None, "expr": {"total": 0}, "vitals": {"hr": 72}, "history": ""})
    assert calm["wellbeing"] == 100 and calm["level"] == "faible"
    obs = compute({"questionnaire": None, "expr": {"sad": 40, "pain": 30, "fear": 20, "total": 100}, "night_exits": 3, "night_toilets": 3, "sleep_hours": 3.5, "vitals": {"hr": 106, "sys": 168, "tempC": 38.4},
                   "history": "anxiété réactionnelle, deuil du conjoint"})
    assert obs["wellbeing"] < calm["wellbeing"] and obs["insomnia"]["level"] in ("modéré", "élevé")
    assert any("lever" in f for f in obs["anxiety"]["factors"]) and any("tristesse" in f for f in obs["depression"]["factors"]) and any("sommeil" in f for f in obs["insomnia"]["factors"])
    full = compute({"questionnaire": score_answers({"phq9": [3] * 8 + [2], "gad7": [3] * 7, "sleep": [3] * 6}), "expr": {"total": 0}, "vitals": {}})
    assert full["wellbeing"] < 30 and full["depression"]["level"] == "élevé" and full["q9_positive"]
    assert all(0 <= full[k]["score"] <= 100 for k in ("depression", "anxiety", "insomnia"))


# ── rôle psychiatre ──────────────────────────────────────────────────────────
def test_psychiatrist_sees_the_whole_platform_and_writes_psychology(login):
    psy = login("psychiatrist")
    me = psy.get("/api/auth/me").json()
    assert me["role"] == "psychiatrist" and {"view_psychology", "write_psychology", "view_medical_record", "write_medical_record", "view_diagnostics", "view_clinical", "view_patients"} <= set(me["permissions"])
    for url in ("/api/rooms/states", "/api/risks", "/api/records", "/api/pharmacy/medications", "/api/dossier/patients", "/api/diagnostics/patient_01", "/api/care-plan", "/api/psych/patients", "/api/treatment-orders", "/api/fever"):
        assert psy.get(url).status_code == 200, url
    rx = psy.post("/api/psych/patient_02/prescriptions", json={"type": "Entretiens de soutien", "frequency": "2 fois par semaine", "goals": "Réduire l'anxiété liée à l'hospitalisation", "instructions": "Prévenir avant chaque soin, favoriser les visites."})
    assert rx.status_code == 201 and rx.json()["author"] == "psychiatre"
    nurse, doctor = login("nurse"), login("general_doctor")
    # infirmier : lecture seule (état et consignes), sans le détail des réponses
    d = nurse.get("/api/psych/patient_02").json()
    assert d["scope"] == "consignes" and d["items"] is None and any(p["instructions"].startswith("Prévenir") for p in d["prescriptions"])
    assert nurse.post("/api/psych/patient_02/prescriptions", json={"type": "x"}).status_code == 403
    assert doctor.post("/api/psych/patient_02/prescriptions", json={"type": "x"}).status_code == 403
    assert doctor.get("/api/psych/patient_02").json()["scope"] == "full"
    assert login("receptionist").get("/api/psych/patients").status_code == 403 and login("pharmacist").get("/api/psych/patients").status_code == 403


# ── questionnaire d'admission sur tablette ───────────────────────────────────
def answers(q9=0):
    return {"phq9": [1, 2, 1, 2, 1, 1, 1, 0, q9], "gad7": [1, 1, 2, 1, 0, 1, 0], "sleep": [2, 2, 1, 2, 1, 1]}


def test_admission_questionnaire_is_offered_once_the_patient_is_in_bed(client, anon_client):
    client.post("/api/demo/reset")
    client.post("/api/ingest", json=vision("101", "lying_bed", "awake_bed"))
    d = wait_for(lambda: (lambda x: x if x["questionnaire"] else None)(client.get("/api/psych/patient_01").json()), timeout=10)
    assert d and d["questionnaire"]["status"] == "pending"
    url = d["questionnaire"]["url"]
    logs = client.get("/api/agents/logs?agent=PsychAgent&room=101&limit=200").json()
    assert any("Questionnaire d'admission créé" in l["reasoning"] for l in logs)                # l'infirmier est aussi notifié (lien tablette)
    # page tablette : publique, par jeton
    page = anon_client.get(url)
    assert page.status_code == 200 and "Questionnaire de bien-être" in page.text
    token = url.rsplit("/", 1)[1]
    form = anon_client.get(f"/api/psych/questionnaire/{token}").json()
    assert [len(s["items"]) for s in form["sections"]] == [9, 7, 6] and form["first_name"] == "Mohamed" and len(form["scale"]) == 4
    assert anon_client.get("/patient/questionnaire/jeton-invalide").status_code == 404
    assert anon_client.post(f"/api/psych/questionnaire/{token}", json={"phq9": [0] * 3, "gad7": [0] * 7, "sleep": [0] * 6}).status_code == 400
    assert anon_client.post(f"/api/psych/questionnaire/{token}", json=answers()).json()["status"] == "completed"
    assert anon_client.post(f"/api/psych/questionnaire/{token}", json=answers()).status_code == 409
    d = wait_for(lambda: (lambda x: x if x["latest"] and x["latest"]["inputs"]["questionnaire"] else None)(client.get("/api/psych/patient_01").json()), timeout=10)
    assert d and d["questionnaire"]["scores"]["phq9"]["score"] == 9 and d["questionnaire"]["answers"]["phq9"][1] == 2
    assert any("PHQ-9 à 9/27" in f for f in d["latest"]["depression"]["factors"]) and d["latest"]["conduct"] and "jamais un diagnostic" in d["disclaimer"]
    assert not open_risks(client, "101", "psych_alert")


def test_phq9_item9_triggers_an_immediate_alert(client, anon_client):
    client.post("/api/demo/reset")
    client.post("/api/ingest", json=vision("104", "lying_bed", "awake_bed"))
    d = wait_for(lambda: (lambda x: x if x["questionnaire"] else None)(client.get("/api/psych/patient_04").json()), timeout=10)
    token = d["questionnaire"]["url"].rsplit("/", 1)[1]
    low = {"phq9": [0, 0, 0, 0, 0, 0, 0, 0, 1], "gad7": [0] * 7, "sleep": [0] * 6}          # score total minimal, mais item 9 positif
    assert anon_client.post(f"/api/psych/questionnaire/{token}", json=low).status_code == 200
    risks = wait_for(lambda: open_risks(client, "104", "psych_alert"), timeout=10)
    assert risks and risks[0]["severity"] == "critical" and risks[0]["source_agent"] == "PsychAgent"
    notifs = [n for n in client.get("/api/notifications").json()["items"] if "idées suicidaires" in n["title"] and n["room"] == "104"]
    assert {n["target_role"] for n in notifs} >= {"psychiatrist", "duty_doctor"} and all(n["level"] == "critical" for n in notifs)
    assert client.get("/api/psych/patients").json()[3]["q9_positive"] is True
    from app import resolutions

    resolutions._catalog = None
    assert resolutions.plan_for("psych_alert") == {**resolutions.plan_for("psych_alert"), "scenario": "psych_resolves", "role": "psychiatrist"}


def test_low_wellbeing_notifies_nurses_psychiatrist_and_gp(client, anon_client):
    client.post("/api/demo/reset")
    client.post("/api/ingest", json=vision("103", "lying_bed", "awake_bed"))
    d = wait_for(lambda: (lambda x: x if x["questionnaire"] else None)(client.get("/api/psych/patient_03").json()), timeout=10)
    token = d["questionnaire"]["url"].rsplit("/", 1)[1]
    for _ in range(12):                                                                       # expressions tristes observées par la vision
        client.post("/api/ingest", json=msg("hackcure/room/103/vision/expression", expression="sad", confidence=0.8))
    high = {"phq9": [3, 3, 2, 3, 2, 2, 2, 1, 0], "gad7": [2, 2, 2, 2, 1, 1, 1], "sleep": [3, 3, 2, 3, 2, 2]}
    anon_client.post(f"/api/psych/questionnaire/{token}", json=high)
    d = wait_for(lambda: (lambda x: x if x["latest"] and x["latest"]["wellbeing"] < 50 and x["latest"].get("ai") else None)(client.get("/api/psych/patient_03").json()), timeout=12)
    assert d, "score sous le seuil attendu, avec explication"
    assert d["latest"]["depression"]["level"] == "élevé" and any("tristesse" in f for f in d["latest"]["depression"]["factors"]) and "pas d'un diagnostic" in d["latest"]["ai"]["explanation"]
    notifs = [n for n in client.get("/api/notifications").json()["items"] if "Bien-être psychologique bas — chambre 103" in n["title"]]
    assert {n["target_role"] for n in notifs} >= {"nurse", "psychiatrist", "general_doctor"} and any("Conduite à tenir" in n["body"] for n in notifs)
    assert wait_for(lambda: open_risks(client, "103", "psych_low_wellbeing"))
    row = next(p for p in client.get("/api/psych/patients").json() if p["patient_id"] == "patient_03")
    assert row["wellbeing"] < 50 and row["questionnaire"] == "completed" and row["levels"]["depression"] == "élevé"
    assert len(client.get("/api/psych/patient_03").json()["history"]) >= 1

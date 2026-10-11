"""V2 étape 5 — ambulances : trajet simulé et ETA, réservation automatique de la chambre adaptée, suivi GPS réel par jeton, arrivée et admission."""
import time

from app import ambulance as geo

from .test_agents import wait_for


def test_route_geometry_speed_and_eta():
    pts = geo.ROUTES["marsa"]["points"]
    total = geo.route_length_m(pts)
    assert 6000 < total < 12000 and pts[-1] == (geo.CLINIC["lat"], geo.CLINIC["lon"])
    lat, lon, heading, remaining = geo.position_at(pts, total / 2)
    assert abs(remaining - total / 2) < 1 and min(p[0] for p in pts) <= lat <= max(p[0] for p in pts) and 0 <= heading < 360
    assert geo.position_at(pts, total * 2)[3] == 0.0
    speeds = [geo.speed_kmh(i / 20, seed=3) for i in range(21)]
    assert min(speeds) >= 14 and max(speeds) - min(speeds) > 10                       # vitesse variable
    assert geo.eta_seconds(3000, 50) < geo.eta_seconds(6000, 50)
    assert geo.haversine_m((36.8380, 10.2390), (36.8380, 10.2390)) == 0
    # chambre adaptée : préférence par type d'urgence parmi les chambres libres
    assert geo.choose_room("cardio", ["104", "102"]) == "102" and geo.choose_room("trauma", ["101", "104"]) == "104" and geo.choose_room("cardio", []) is None


def test_no_free_room_blocks_the_dispatch(client):
    r = client.post("/api/ambulances/missions", json={"new_patient": {"first_name": "Test", "last_name": "Complet", "age": 50}, "reason": "douleur thoracique", "emergency_type": "cardio", "severity": 1})
    assert r.status_code == 409 and "Aucune chambre libre" in r.json()["detail"]
    assert client.get("/api/ambulances").json()["free_rooms"] == []


def test_ambulance_mission_reserves_a_room_then_admits_the_patient(client, login, anon_client):
    client.post("/api/demo/reset")
    # la chambre 104 est libérée (sortie de la patiente), puis elle revient en ambulance
    assert client.post("/api/records/patient_04/discharge").status_code == 200
    info = client.get("/api/ambulances").json()
    assert info["free_rooms"] == ["104"] and {"cardio", "trauma", "stroke", "respiratory", "obstetric"} <= set(info["types"]) and info["routes"]["marsa"]["km"] > 5
    assert client.get("/api/rooms/states").json()["104"]["vacant"] is True
    body = {"patient_id": "patient_04", "reason": "Chute à domicile, douleur de hanche droite", "emergency_type": "trauma", "severity": 2, "vitals": {"hr": 96, "sys": 138, "spo2": 97}, "mode": "sim", "route": "proche"}
    assert login("pharmacist").post("/api/ambulances/missions", json=body).status_code == 403
    m = login("receptionist").post("/api/ambulances/missions", json=body).json()
    mid = m["id"]
    # départ ⇒ chambre réservée immédiatement, équipe prévenue avec la préparation
    assert m["status"] == "en_route" and m["reserved_room"] == "104" and m["eta_seconds"] > 0 and m["preparation"]["materiel"] and m["track_url"].startswith("/ambulance/track/")
    rs = client.get("/api/rooms/states").json()["104"]
    assert rs["reservation"]["mission_id"] == mid and rs["reservation"]["label"].startswith("Réservée — arrivée dans")
    notifs = [n for n in client.get("/api/notifications").json()["items"] if "Ambulance en route — chambre 104 réservée" in n["title"]]
    assert {n["target_role"] for n in notifs} >= {"nurse", "duty_doctor"} and "Préparer" in notifs[0]["body"]
    assert client.get("/api/ambulances").json()["free_rooms"] == []                              # la chambre n'est plus disponible
    assert wait_for(lambda: (lambda x: x if x["ai"] else None)(next(i for i in client.get("/api/ambulances").json()["missions"] if i["id"] == mid)), timeout=8)   # briefing IA
    # l'ambulance avance : position et ETA mises à jour en continu (trajet accéléré en test)
    first = next(i for i in client.get("/api/ambulances").json()["missions"] if i["id"] == mid)
    moved = wait_for(lambda: (lambda x: x if x["progress"] > first["progress"] + 0.05 or x["status"] != "en_route" else None)(next(i for i in client.get("/api/ambulances").json()["missions"] if i["id"] == mid)), timeout=10)
    assert moved and (moved["remaining_m"] < first["remaining_m"] or moved["status"] != "en_route")
    # arrivée (ETA à zéro) ⇒ transfert ⇒ patient installé, admission créée, chambre plus « réservée »
    done = wait_for(lambda: (lambda x: x if x["status"] == "admitted" else None)(next(i for i in client.get("/api/ambulances").json()["missions"] if i["id"] == mid)), timeout=40)
    assert done and done["admission_id"] and done["arrived_at"]
    rec = next(p for p in client.get("/api/records").json() if p["patient_id"] == "patient_04")
    assert rec["room"] == "104"
    rs = client.get("/api/rooms/states").json()["104"]
    assert rs["reservation"] is None and rs["patient_id"] == "patient_04" and rs["posture"] == "lying_bed"
    assert any("Patient installé — chambre 104" in n["title"] for n in client.get("/api/notifications").json()["items"])
    logs = client.get("/api/agents/logs?agent=AmbulanceAgent&limit=20").json()
    assert any("admission #" in l["output"] for l in logs) and any("Réservée — arrivée dans" in l["output"] for l in logs)


def test_real_gps_tracking_page_moves_the_ambulance(client, anon_client):
    client.post("/api/records/patient_03/discharge")
    m = client.post("/api/ambulances/missions", json={"patient_id": "patient_03", "reason": "Dyspnée aiguë", "emergency_type": "respiratory", "severity": 1, "mode": "gps"}).json()
    token = m["track_url"].rsplit("/", 1)[1]
    assert m["reserved_room"] == "103" and m["mode"] == "gps"
    page = anon_client.get(m["track_url"])
    assert page.status_code == 200 and "navigator.geolocation" in page.text and anon_client.get("/ambulance/track/jeton-faux").status_code == 404
    assert anon_client.get(f"/api/ambulances/track/{token}").json()["room"] == "103"
    # le téléphone envoie sa position : l'ambulance se déplace sur la carte, l'ETA suit
    far = anon_client.post(f"/api/ambulances/track/{token}", json={"lat": 36.8500, "lon": 10.2700, "speed_kmh": 42}).json()
    near = anon_client.post(f"/api/ambulances/track/{token}", json={"lat": 36.8400, "lon": 10.2430, "speed_kmh": 30}).json()
    assert far["status"] == "en_route" and near["remaining_m"] < far["remaining_m"] and near["eta_minutes"] < far["eta_minutes"]
    cur = next(i for i in client.get("/api/ambulances").json()["missions"] if i["id"] == m["id"])
    assert abs(cur["lat"] - 36.8400) < 1e-6 and len(cur["route"]) == 2
    assert anon_client.post(f"/api/ambulances/track/{token}", json={"lat": 136.0, "lon": 10.0}).status_code == 400
    # arrivée déclarée depuis le téléphone
    anon_client.post(f"/api/ambulances/track/{token}", json={"lat": geo.CLINIC["lat"], "lon": geo.CLINIC["lon"], "arrived": True})
    done = wait_for(lambda: (lambda x: x if x["status"] in ("arrived", "admitted") else None)(next(i for i in client.get("/api/ambulances").json()["missions"] if i["id"] == m["id"])), timeout=10)
    assert done
    assert wait_for(lambda: next(i for i in client.get("/api/ambulances").json()["missions"] if i["id"] == m["id"])["status"] == "admitted", timeout=15)
    assert next(p for p in client.get("/api/records").json() if p["patient_id"] == "patient_03")["room"] == "103"

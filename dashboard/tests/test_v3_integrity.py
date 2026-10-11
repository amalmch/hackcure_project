"""
V3, étape 5 — intégrité des trames IoT : numéro de séquence, horodatage et signature HMAC-SHA256.

Avec une clé (`EDGE_HMAC_KEY`) : trame valide acceptée ; signature fausse, rejeu, trame trop ancienne ou non signée rejetées
et comptées (`GET /api/integrity`). Sans clé (défaut, mode démo) : tout est accepté et l'API l'annonce.
Chaque test remet l'état à zéro (clé, compteurs, séquences) : les autres tests envoient des trames non signées et datées.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingest import integrity  # noqa: E402
from contracts import integrity as prim  # noqa: E402

from .test_agents import TS, msg  # noqa: E402

KEY = "cle-de-test-0123456789abcdef"
TOPIC = "hackcure/room/104/env"


def iso(offset_s: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_s)).isoformat()


def env_payload(ts=None, **extra):
    return {"ts": ts or iso(), "source": "sim", "tempC": 22.0, "humidity": 45.0, "motion": False, "doorOpen": False, **extra}


def signed(seq, ts=None, topic=TOPIC, key=KEY, **extra):
    return {"topic": topic, "payload": prim.sign(topic, env_payload(ts, **extra), key, seq)}


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Pas de clé et compteurs à zéro avant ET après chaque test de ce fichier."""
    monkeypatch.delenv("EDGE_HMAC_KEY", raising=False)
    monkeypatch.delenv("FRAME_MAX_AGE_S", raising=False)
    monkeypatch.delenv("FRAME_MAX_FUTURE_S", raising=False)
    integrity.reset()
    yield
    integrity.reset()


@pytest.fixture()
def enforced(monkeypatch):
    monkeypatch.setenv("EDGE_HMAC_KEY", KEY)
    yield KEY


# ─── primitives pures (contracts/integrity.py) ───────────────────────────────
def test_primitives_canonical_sign_verify():
    assert prim.canonical({"b": 1, "a": {"é": [1, 2.5, None, True]}}) == '{"a":{"é":[1,2.5,null,true]},"b":1}'
    payload = env_payload()
    out = prim.sign(TOPIC, payload, KEY, 7)
    assert "sig" not in payload and "seq" not in payload  # l'original n'est pas modifié
    assert out["seq"] == 7 and len(out["sig"]) == 64 and out["sig"] == out["sig"].lower()
    assert prim.verify(TOPIC, out, KEY)
    assert not prim.verify(TOPIC, out, "autre-cle")
    assert not prim.verify("hackcure/room/103/env", out, KEY)  # le topic est signé
    assert not prim.verify(TOPIC, {**out, "tempC": 39.0}, KEY)  # contenu modifié
    assert not prim.verify(TOPIC, {**out, "seq": 8}, KEY)  # séquence modifiée
    assert not prim.verify(TOPIC, {k: v for k, v in out.items() if k != "sig"}, KEY)
    assert prim.sign(TOPIC, dict(reversed(list(payload.items()))), KEY, 7)["sig"] == out["sig"]  # l'ordre des clés ne compte pas
    # même résultat que la formule documentée
    import hashlib
    import hmac
    import json

    body = {k: v for k, v in out.items() if k != "sig"}
    expected = hmac.new(KEY.encode(), (TOPIC + "\n" + json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)).encode("utf-8"), hashlib.sha256).hexdigest()
    assert out["sig"] == expected


def test_signer_sequence_restamp_and_no_key(monkeypatch):
    s = prim.Signer(KEY, start=10)
    a, b = s.sign(TOPIC, env_payload()), s.sign(TOPIC, env_payload())
    assert (a["seq"], b["seq"]) == (11, 12) and prim.verify(TOPIC, a, KEY) and prim.verify(TOPIC, b, KEY)
    old = env_payload(ts=TS)
    r = s.sign(TOPIC, old, restamp=True)
    assert r["measuredAt"] == TS and r["ts"] != TS and r["seq"] == 13 and prim.verify(TOPIC, r, KEY) and old["ts"] == TS
    assert prim.Signer(KEY).next_seq() > 1_600_000_000_000  # démarre à l'heure courante (ms) : un redémarrage repart au-dessus
    lazy = prim.Signer()  # clé lue dans l'environnement à chaque message
    p = env_payload()
    assert lazy.sign(TOPIC, p) is p and not lazy.enabled  # sans clé : rien n'est ajouté
    monkeypatch.setenv("EDGE_HMAC_KEY", KEY)
    assert lazy.enabled and prim.verify(TOPIC, lazy.sign(TOPIC, p), KEY)


# ─── mode démo (défaut) ──────────────────────────────────────────────────────
def test_demo_mode_accepts_everything_and_says_so(client, anon_client):
    r = client.post("/api/ingest", json=msg(TOPIC, tempC=22.0, humidity=45.0, motion=False, doorOpen=False))  # non signée, horodatage ancien
    assert r.status_code == 202 and r.json()["rejected"] == []
    r = client.post("/api/ingest", json={"topic": TOPIC, "payload": {**env_payload(), "seq": 1, "sig": "00" * 32}})  # signature fausse : non vérifiée sans clé
    assert r.status_code == 202
    d = client.get("/api/integrity").json()
    assert d["mode"] == "demo" and d["keyConfigured"] is False and "démo" in d["warning"]
    assert d["counters"]["unverified"] == 2 and d["counters"]["accepted"] == 2 and d["counters"]["verified"] == 0 and d["counters"]["rejected"] == 0
    assert d["lastRejection"] is None and d["recentRejections"] == []
    assert anon_client.get("/api/integrity").status_code == 401  # lecture clinique authentifiée


# ─── mode vérification (clé configurée) ──────────────────────────────────────
def test_valid_frame_accepted(client, enforced):
    r = client.post("/api/ingest", json=signed(1))
    assert r.status_code == 202 and r.json()["accepted"] == 1 and r.json()["rejected"] == []
    assert client.post("/api/ingest", json=signed(2)).status_code == 202
    d = client.get("/api/integrity").json()
    assert d["mode"] == "enforced" and d["keyConfigured"] is True and d["warning"] is None and d["algorithm"] == "HMAC-SHA256" and d["maxAgeS"] == 30
    assert d["counters"]["verified"] == 2 and d["counters"]["accepted"] == 2 and d["counters"]["rejected"] == 0
    assert d["senders"] == [{"sender": "sim@104", "lastSeq": 2, "accepted": 2, "lastAcceptedAt": d["senders"][0]["lastAcceptedAt"]}]


def test_wrong_signature_rejected(client, enforced):
    forged = signed(1, key="mauvaise-cle")
    r = client.post("/api/ingest", json=forged)
    assert r.status_code == 401 and r.json()["detail"][0]["reason"] == "bad_signature"
    tampered = signed(2)
    tampered["payload"]["tempC"] = 41.0  # contenu modifié après signature
    assert client.post("/api/ingest", json=tampered).status_code == 401
    moved = signed(3)
    moved["topic"] = "hackcure/room/103/env"  # trame rejouée vers une autre chambre
    assert client.post("/api/ingest", json=moved).json()["detail"][0]["reason"] == "bad_signature"
    d = client.get("/api/integrity").json()
    assert d["counters"]["byReason"]["bad_signature"] == 3 and d["counters"]["rejected"] == 3 and d["counters"]["verified"] == 0
    assert d["lastRejection"]["reason"] == "bad_signature" and d["lastRejection"]["topic"] == "hackcure/room/103/env" and d["lastRejection"]["at"]
    assert len(d["recentRejections"]) == 3


def test_replay_rejected(client, enforced):
    frame = signed(10)
    assert client.post("/api/ingest", json=frame).status_code == 202
    r = client.post("/api/ingest", json=frame)  # la même trame, rejouée
    assert r.status_code == 401 and r.json()["detail"][0]["reason"] == "replay"
    assert client.post("/api/ingest", json=signed(9)).status_code == 401  # séquence plus basse
    assert client.post("/api/ingest", json=signed(11)).status_code == 202  # la suite passe
    assert client.post("/api/ingest", json=signed(1, topic="hackcure/room/103/env")).status_code == 202  # autre émetteur : son propre compteur
    d = client.get("/api/integrity").json()
    assert d["counters"]["byReason"]["replay"] == 2 and d["counters"]["verified"] == 3
    assert {s["sender"]: s["lastSeq"] for s in d["senders"]} == {"sim@104": 11, "sim@103": 1}


def test_too_old_or_future_rejected(client, enforced):
    r = client.post("/api/ingest", json=signed(1, ts=iso(-45)))  # > 30 s
    assert r.status_code == 401 and r.json()["detail"][0]["reason"] == "stale"
    assert client.post("/api/ingest", json=signed(2, ts=TS)).status_code == 401  # horodatage constant des autres tests
    assert client.post("/api/ingest", json=signed(3, ts=iso(+60))).status_code == 401  # trop en avance
    assert client.post("/api/ingest", json=signed(4, ts=iso(-10))).status_code == 202  # dans la fenêtre
    d = client.get("/api/integrity").json()
    assert d["counters"]["byReason"]["stale"] == 3 and d["counters"]["verified"] == 1


def test_unsigned_rejected_when_key_set(client, enforced):
    r = client.post("/api/ingest", json={"topic": TOPIC, "payload": env_payload()})
    assert r.status_code == 401 and r.json()["detail"][0]["reason"] == "unsigned"
    assert client.post("/api/ingest", json={"topic": TOPIC, "payload": env_payload(seq=1)}).status_code == 401  # seq sans sig
    assert client.post("/api/ingest", json={"topic": TOPIC, "payload": env_payload(sig="ab" * 32)}).status_code == 401  # sig sans seq
    # lot mixte : 202, la trame refusée est listée avec sa raison ; un contrat invalide reste un 422
    r = client.post("/api/ingest", json={"messages": [signed(1), {"topic": TOPIC, "payload": env_payload()}]})
    assert r.status_code == 202 and r.json()["accepted"] == 1 and r.json()["rejected"][0]["reason"] == "unsigned"
    assert client.post("/api/ingest", json={"topic": "hackcure/room/104/vision/state", "payload": {"ts": iso(), "source": "sim"}}).status_code == 422
    d = client.get("/api/integrity").json()
    assert d["counters"]["byReason"]["unsigned"] == 4 and d["counters"]["verified"] == 1 and d["lastRejection"]["label"] == "trame non signée"


def test_restart_rule_and_exemptions(enforced, monkeypatch):
    clock = {"t": 1_800_000_000.0}
    monkeypatch.setattr(integrity, "_now", lambda: clock["t"])

    def frame(seq):
        ts = datetime.fromtimestamp(clock["t"], timezone.utc).isoformat()
        return prim.sign(TOPIC, env_payload(ts=ts), KEY, seq)

    assert integrity.check(TOPIC, frame(1000), "mqtt").status == "verified"
    low = frame(5)
    v = integrity.check(TOPIC, low, "mqtt")  # émetteur actif il y a un instant : séquence plus basse = rejeu
    assert not v.ok and v.reason == "replay"
    clock["t"] += 31  # plus de 30 s de silence : un émetteur redémarré repart d'une séquence basse
    assert integrity.check(TOPIC, low, "mqtt").reason == "stale"  # l'ancienne trame, elle, est devenue trop vieille
    assert integrity.check(TOPIC, frame(5), "mqtt").status == "verified"
    assert integrity.check(TOPIC, frame(5), "mqtt").reason == "replay" and integrity.senders["sim@104"]["last_seq"] == 5
    # émis par le serveur : commandes et scénario exemptés, mais pas l'acquittement d'un edge
    cmd = {"ts": "x", "source": "server", "action": "open"}
    assert integrity.check("hackcure/room/104/cmd/window", cmd, "mqtt").status == "exempt"
    assert integrity.check("hackcure/sim/scenario", {"name": "fall_demo"}, "mqtt").status == "exempt"
    assert integrity.check("hackcure/room/104/cmd/ack", cmd, "virtual").status == "exempt"  # edge virtuel interne au serveur
    assert integrity.check("hackcure/room/104/cmd/ack", cmd, "http").reason == "unsigned"
    assert integrity.snapshot()["counters"]["exempt"] == 3
    monkeypatch.setenv("FRAME_MAX_AGE_S", "120")
    assert integrity.snapshot()["maxAgeS"] == 120


def test_rejection_ring_buffer_keeps_20(enforced):
    for i in range(25):
        integrity.check(TOPIC, env_payload(n=i), "mqtt")
    snap = integrity.snapshot()
    assert snap["counters"]["rejected"] == 25 and len(snap["recentRejections"]) == 20 and snap["recentRejections"][0] == snap["lastRejection"]


# ─── simulateur : trames signées quand la clé est définie ────────────────────
def test_simulator_frames_signed_and_accepted(client, enforced):
    from simulator.engine import SimEngine

    buffer = []
    engine = SimEngine(publish=lambda t, p: buffer.append({"topic": t, "payload": p}), rooms=["104"], speed=1.0)  # clé lue dans EDGE_HMAC_KEY
    engine.rooms["104"].autonomous = False
    engine.tick(0.5)
    engine.tick(0.5)
    engine.handle_command("104", "light", "on", None, "cmd-integrity")  # l'acquittement de l'edge virtuel est signé lui aussi
    assert len(buffer) > 5 and any(m["topic"].endswith("/cmd/ack") for m in buffer)
    seqs = [m["payload"]["seq"] for m in buffer]
    assert seqs == sorted(set(seqs)) and all(prim.verify(m["topic"], m["payload"], KEY) for m in buffer)
    r = client.post("/api/ingest", json={"messages": buffer})  # après un aller-retour JSON, comme sur le réseau
    assert r.status_code == 202 and r.json()["rejected"] == [] and r.json()["accepted"] == len(buffer)
    assert client.post("/api/ingest", json={"messages": buffer}).status_code == 401  # le lot rejoué est refusé en entier
    d = client.get("/api/integrity").json()
    assert d["counters"]["verified"] == len(buffer) and d["counters"]["byReason"]["replay"] == len(buffer)
    # transport direct du simulateur embarqué (`via="embedded"`) : vérifié comme les autres
    engine.tick(1.0)
    fresh = buffer[len(seqs):]
    assert fresh and all(integrity.check(m["topic"], m["payload"], "embedded").status == "verified" for m in fresh)


def test_simulator_adds_nothing_without_key():
    from simulator.engine import SimEngine

    out = []
    engine = SimEngine(publish=lambda t, p: out.append(p), rooms=["104"])
    engine.tick(1.0)
    assert out and all("sig" not in p and "seq" not in p for p in out)

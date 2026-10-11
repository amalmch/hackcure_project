"""Simulateur : signature des trames (séquence + HMAC-SHA256) quand une clé est fournie, rien sinon."""
from contracts import integrity as prim
from simulator.engine import SimEngine

KEY = "cle-sim-test"


def run(engine, seconds=3.0, step=0.5):
    t = 0.0
    while t < seconds:
        engine.tick(step)
        t += step


def test_no_key_no_extra_fields(monkeypatch):
    monkeypatch.delenv("EDGE_HMAC_KEY", raising=False)
    out = []
    eng = SimEngine(publish=lambda t, p: out.append((t, p)))
    run(eng)
    assert out and all("seq" not in p and "sig" not in p for _, p in out)


def test_explicit_key_signs_every_message_with_increasing_seq(monkeypatch):
    monkeypatch.delenv("EDGE_HMAC_KEY", raising=False)
    out = []
    eng = SimEngine(publish=lambda t, p: out.append((t, p)), hmac_key=KEY)
    run(eng)
    eng.handle_command("102", "window", "open", None, "c-1")
    assert len(out) > 20 and all(prim.verify(t, p, KEY) for t, p in out)
    seqs = [p["seq"] for _, p in out]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert any(t.endswith("/cmd/ack") for t, _ in out)


def test_key_from_environment_and_still_valid_contracts(monkeypatch):
    from app import contracts

    monkeypatch.setenv("EDGE_HMAC_KEY", KEY)
    out = []
    eng = SimEngine(publish=lambda t, p: out.append((t, p)), rooms=["104"])
    run(eng, seconds=2.0)
    assert out
    for topic, payload in out:
        contracts.validate(topic, payload)  # `seq` et `sig` sont des champs supplémentaires admis par les schémas
        assert prim.verify(topic, payload, KEY)

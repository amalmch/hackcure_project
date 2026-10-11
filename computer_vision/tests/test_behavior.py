"""
Analyse comportementale optionnelle (apports d'Amal 12e1eb2) : sans PyTorch, sans backbone ou sans poids entraînés,
le repli est automatique et silencieux ; rien n'est téléchargé.
"""
import random
import sys
from pathlib import Path

CV_DIR = Path(__file__).resolve().parents[1]
if str(CV_DIR) not in sys.path:
    sys.path.insert(0, str(CV_DIR))

from src import behavior  # noqa: E402
from src.behavior import BehaviorAnalyzer, load_transformer, transformer_status  # noqa: E402
from src.temporal.agent_adapter import InterventionAgentAdapter  # noqa: E402


def test_transformer_is_optional_and_never_downloads(tmp_path, monkeypatch):
    ok, why = transformer_status(tmp_path / "absent.pt")
    assert ok is False and "poids" in why
    assert load_transformer(weights=tmp_path / "absent.pt") is None
    # poids présents mais backbone absent du cache (ou PyTorch absent) : toujours un repli, jamais d'appel réseau
    fake = tmp_path / "best_transformer.pt"
    fake.write_bytes(b"x")
    try:
        import torch

        monkeypatch.setattr(torch.hub, "get_dir", lambda: str(tmp_path / "hub"))
        monkeypatch.setattr(torch.hub, "load", lambda *a, **k: (_ for _ in ()).throw(AssertionError("téléchargement interdit")))
    except ImportError:
        pass
    ok, why = transformer_status(fake)
    assert ok is False and ("backbone" in why or "PyTorch" in why)
    assert load_transformer(weights=fake) is None
    assert BehaviorAnalyzer().mode == "temporal"


def test_inference_module_has_no_hard_dependency_on_the_transformer():
    src = (CV_DIR / "src" / "inference.py").read_text(encoding="utf-8")
    assert "load_transformer" in src and "\nimport torch" not in src and "from .transformer.model import" not in src
    assert "torch.hub.load" not in (CV_DIR / "src" / "behavior.py").read_text(encoding="utf-8").replace("original = torch.hub.load", "").replace("torch.hub.load = ", "")


def test_temporal_analysis_levels():
    random.seed(4)
    b = BehaviorAnalyzer(use_transformer=False)
    for _ in range(20):
        e = b.update("p1", "patient_lying", 0.9, velocity=0.001)
    # l'analyseur d'Amal signale l'immobilité ; au lit c'est du repos : pas un risque comportemental
    assert e["evidence"] == ["prolonged_immobility"] and e["behavioral_level"] == "low"
    for _ in range(20):
        e = b.update("p1", "patient_sitting", 0.9, velocity=random.choice([0.0, 0.3]), resting=False)
    assert "agitation_detected" in e["evidence"] and e["behavioral_level"] == "moderate" and e["recommendations"]
    # une chute est un événement à part : le niveau strictement comportemental ne la double pas
    e = b.update("p1", "falling", 0.95, velocity=0.2)
    assert e["event_type"] == "fall" and e["risk_level"] == "critical" and e["behavioral_level"] == "low"
    assert e["transformer"] is False and e["transformer_analysis"] is None


def test_adapter_makes_no_http_call_without_url(monkeypatch):
    monkeypatch.delenv("INTERVENTION_AGENT_URL", raising=False)
    a = InterventionAgentAdapter()
    assert a.agent_service_url is None
    recs = a.request_recommendation({"risk_level": "high", "evidence": ["instability_pattern"], "event_type": "behavioral_risk"})
    assert recs and "instability" in recs[0].lower()
    assert behavior.RESTING_STATES >= {"patient_lying", "lying_bed"}

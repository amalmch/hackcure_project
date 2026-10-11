"""Étape V3-1 : fichiers Docker (structure vérifiée sans démon Docker)."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_is_slim_non_root_with_healthcheck():
    d = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.11-slim" in d and "USER hackcure" in d and "HEALTHCHECK" in d and "healthcheck.py" in d
    assert d.index("USER hackcure") < d.index("CMD")            # le serveur ne tourne jamais en root
    assert "COPY .env" not in d and ".env" in (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert (ROOT / "dashboard" / "healthcheck.py").exists()


def test_compose_has_platform_broker_and_optional_n8n():
    c = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    s = c["services"]
    assert {"platform", "mosquitto", "n8n"} <= set(s)
    p = s["platform"]
    assert p["restart"] == "unless-stopped" and "hackcure-data:/data" in p["volumes"] and p["environment"]["MQTT_HOST"] == "mosquitto"
    assert p["env_file"][0] == {"path": ".env", "required": False}   # la plateforme démarre même sans .env
    assert s["n8n"]["profiles"] == ["n8n"] and any("n8n-data" in v for v in s["n8n"]["volumes"])
    assert {"hackcure-data", "n8n-data"} <= set(c["volumes"])
    for name in ("run-docker.ps1", "run-docker.sh"):
        assert (ROOT / "scripts" / name).exists()


def test_healthcheck_probe_reports_failure_when_nothing_listens(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("hc", ROOT / "dashboard" / "healthcheck.py")
    hc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hc)
    monkeypatch.setenv("PORT", "1")          # rien n'écoute : la sonde renvoie 1 sans lever d'exception
    assert hc.main() == 1

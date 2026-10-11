"""Fixtures pytest : client HTTP + WebSocket sur l'application FastAPI (base SQLite temporaire)."""
import os
import sys
from pathlib import Path

import pytest

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

# Base de test isolée, auth active (les tests se connectent explicitement)
_TEST_DB = DASHBOARD_DIR / "tests" / "_test_clinic.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"
os.environ.setdefault("EMBEDDED_SIM", "0")
os.environ.setdefault("MQTT_ENABLED", "0")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("AUTH_REQUIRED", "1")
os.environ.setdefault("DEMO_PASSWORD", "hackcure2026")
os.environ.setdefault("FOLLOWUP_RECHECK_S", "0.3")
os.environ.setdefault("ESCALATION_CRITICAL_S", "2")
os.environ.setdefault("ESCALATION_HIGH_S", "3")
os.environ.setdefault("ESCALATION_MEDIUM_S", "4")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("VITALS_TICK_S", "1")
os.environ.setdefault("FEVER_LAB_DELAY_S", "0.6")
os.environ.setdefault("THERMAL_RECHECK_S", "0.6")
os.environ.setdefault("MED_RELAUNCH_S", "1")
os.environ.setdefault("MED_ESCALATE_S", "2.5")
os.environ.setdefault("MED_DUE_WINDOW_S", "900")
os.environ.setdefault("DIAGNOSTICS_TICK_S", "1")
os.environ.setdefault("PSYCH_TICK_S", "1")
os.environ.setdefault("PREDICTION_TICK_S", "1")
os.environ.setdefault("PREDICTION_MIN_SPAN_S", "20")
os.environ.setdefault("AMBULANCE_TIME_SCALE", "60")
os.environ.setdefault("AMBULANCE_INSTALL_S", "1")
os.environ.setdefault("N8N_ENABLED", "0")  # jamais de vrai n8n ni de vraie API pendant les tests
os.environ["PLATFORM_SERVICE_TOKEN"] = "test-service-token"
os.environ["N8N_WEBHOOK_SECRET"] = "test-webhook-secret"

USERNAMES = {
    "pharmacist": "pharmacien",
    "receptionist": "receptionniste",
    "nurse": "infirmier",
    "duty_doctor": "medecin_garde",
    "general_doctor": "medecin",
    "owner": "owner",
    "psychiatrist": "psychiatre",
}


@pytest.fixture(scope="session")
def app():
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(_TEST_DB) + suffix)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass
    from app.main import app as fastapi_app
    return fastapi_app


@pytest.fixture(scope="session")
def server(app):
    """Un seul cycle de vie (lifespan) pour toute la session de tests."""
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


def _login(client, role: str):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"username": USERNAMES[role], "password": "hackcure2026"})
    assert r.status_code == 200, r.text
    client.cookies.set("hackcure_token", r.json()["token"])
    return client


@pytest.fixture()
def anon_client(server):
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    yield c


@pytest.fixture()
def client(server):
    """Client connecté en propriétaire (tous les droits)."""
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    _login(c, "owner")
    yield c


@pytest.fixture()
def login(server):
    """Fabrique : `login(role)` → client connecté avec ce rôle."""
    from fastapi.testclient import TestClient

    def _factory(role: str):
        c = TestClient(server.app)
        return _login(c, role)

    return _factory

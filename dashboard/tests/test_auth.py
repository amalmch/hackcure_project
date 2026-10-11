"""Authentification JWT et permissions par rôle (section 11)."""
import pytest

ROLES = ["pharmacist", "receptionist", "nurse", "duty_doctor", "general_doctor", "owner"]
USERNAMES = {
    "pharmacist": "pharmacien",
    "receptionist": "receptionniste",
    "nurse": "infirmier",
    "duty_doctor": "medecin_garde",
    "general_doctor": "medecin",
    "owner": "owner",
}


def test_login_sets_cookie_and_me(anon_client):
    r = anon_client.post("/api/auth/login", json={"username": "infirmier", "password": "hackcure2026"})
    assert r.status_code == 200
    assert "hackcure_token" in r.cookies
    me = anon_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "nurse"
    assert "manage_risks" in me.json()["permissions"]
    assert "write_medical_docs" not in me.json()["permissions"]
    anon_client.post("/api/auth/logout")
    anon_client.cookies.clear()
    assert anon_client.get("/api/auth/me").status_code == 401


def test_bad_password(anon_client):
    r = anon_client.post("/api/auth/login", json={"username": "owner", "password": "wrong"})
    assert r.status_code == 401


def test_root_redirects_to_login_when_anonymous(anon_client):
    r = anon_client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"].startswith("/login")
    assert anon_client.get("/login").status_code == 200


def test_bearer_token_accepted(anon_client):
    token = anon_client.post("/api/auth/login", json={"username": "owner", "password": "hackcure2026"}).json()["token"]
    anon_client.cookies.clear()
    r = anon_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["role"] == "owner"


@pytest.mark.parametrize("role", ROLES)
def test_permission_matrix(role, login):
    from app.auth import PERMISSIONS, permissions_for

    perms = set(permissions_for(role))
    doctors = {"duty_doctor", "general_doctor", "owner"}
    assert ("edit_pharmacy" in perms) == (role == "pharmacist" or role in doctors)
    assert ("view_clinical" in perms) == (role != "pharmacist")
    assert ("manage_risks" in perms) == (role == "nurse" or role in doctors)
    assert ("write_medical_docs" in perms) == (role in doctors)
    assert ("create_patients" in perms) == (role == "receptionist" or role in doctors)
    assert ("manage_users" in perms) == (role == "owner")
    assert set(PERMISSIONS) >= perms


def test_users_endpoint_owner_only(login):
    for role in ROLES:
        c = login(role)
        r = c.get("/api/users")
        assert (r.status_code == 200) == (role == "owner"), role


def test_owner_user_crud(login):
    c = login("owner")
    r = c.post("/api/users", json={"username": "test_nurse", "password": "x", "role": "nurse", "full_name": "Test"})
    assert r.status_code == 201
    uid = r.json()["id"]
    assert c.post("/api/users", json={"username": "test_nurse", "password": "x", "role": "nurse"}).status_code == 409
    assert c.post("/api/users", json={"username": "zz", "password": "x", "role": "alien"}).status_code == 400
    r = c.patch(f"/api/users/{uid}", json={"active": False, "role": "pharmacist"})
    assert r.json()["active"] is False and r.json()["role"] == "pharmacist"
    assert c.delete(f"/api/users/{uid}").status_code == 204
    assert c.get("/api/users").status_code == 200


def test_login_is_audited(login):
    c = login("owner")
    from app.db import session_scope
    from app.models import AuditLog
    from sqlmodel import select

    with session_scope() as s:
        rows = s.exec(select(AuditLog).where(AuditLog.action == "login")).all()
        assert any(r.user == "owner" for r in rows)

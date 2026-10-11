import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    response = await client.post("/api/v1/auth/login", json={
        "email": "mohamed@example.com",
        "password": "Test123!@#"
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "mohamed@example.com"

@pytest.mark.asyncio
async def test_login_invalid_password(client: AsyncClient):
    response = await client.post("/api/v1/auth/login", json={
        "email": "mohamed@example.com",
        "password": "WrongPassword!"
    })
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_patient_profile(client: AsyncClient, auth_headers):
    headers = await auth_headers(client)
    response = await client.get("/api/v1/patients/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["first_name"] == "Mohamed"
    assert data["last_name"] == "Trabelsi"
    assert "allergies" in data
